"""Tracing for PRISM by Block Convey.

Each board meeting is one PRISM session:
  * one trace per agent turn (POST /api/traces), with the agent's prompt,
    its final line, latency, and metadata: cited facts, position, whether the
    grounding check blocked an ungrounded figure;
  * one trajectory for the whole meeting (POST /api/trajectories): the model
    run, every turn in order, and the verdict as the final answer;
  * a session-end marker.

Payloads match prismtrace-sdk 0.6.0 (PRISMtrace.trace_llm / submit_trajectory /
end_session), sent with the standard library so the server needs no installs.
Everything is also written to quorum/traces/<id>.json.

Config (environment or quorum/.env): PRISMTRACE_API_KEY, PRISM_PROJECT_ID,
optional PRISMTRACE_HOST.
"""
import json
import os
import threading
import time
import urllib.request
import uuid

TRACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "traces")
DEFAULT_HOST = "https://api.prism.blockconvey.com"


def _cfg():
    return {
        "key": os.environ.get("PRISMTRACE_API_KEY", ""),
        "project": os.environ.get("PRISM_PROJECT_ID", ""),
        "host": (os.environ.get("PRISMTRACE_HOST") or DEFAULT_HOST).rstrip("/"),
    }


def prism_enabled():
    c = _cfg()
    return bool(c["key"] and c["project"])


class Trace:
    def __init__(self, name, metadata=None):
        self.id = time.strftime("quorum-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.name = name
        self.metadata = metadata or {}
        self.spans = []
        self.started = time.time()

    def span(self, name, kind, **fields):
        s = {"span_id": uuid.uuid4().hex[:12], "name": name, "kind": kind, "ts": time.time(), **fields}
        self.spans.append(s)
        return s

    def finish(self, output):
        payload = {"trace_id": self.id, "name": self.name, "metadata": self.metadata,
                   "started": self.started, "duration_s": round(time.time() - self.started, 3),
                   "output": output, "spans": self.spans}
        os.makedirs(TRACE_DIR, exist_ok=True)
        with open(os.path.join(TRACE_DIR, f"{self.id}.json"), "w") as f:
            json.dump(payload, f, indent=2, default=str)
        exported = prism_enabled()
        if exported:
            # Send in the background so the verdict isn't held up by the network.
            threading.Thread(target=_export_to_prism, args=(payload,), daemon=False).start()
        return {"trace_id": self.id, "exported_to_prism": exported,
                "flags": sum(1 for s in self.spans if s.get("grounding_failed"))}


# ------------------------------------------------------------------ PRISM export
def _post(path, body):
    c = _cfg()
    req = urllib.request.Request(
        c["host"] + path, data=json.dumps(body, default=str).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-prismtrace-key": c["key"]})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except Exception as e:  # tracing must never break the app
        print(f"[prism] {path} failed: {e}")
        return None


def _export_to_prism(t):
    c = _cfg()
    meta = t["metadata"]
    session_id = t["trace_id"]
    common = {"scenario": meta.get("scenario"), "guardrails": meta.get("guardrails"),
              "ceo_note": meta.get("ceo_note") or None, "provider": meta.get("provider"),
              "overrides": meta.get("overrides"), "session_id": session_id}
    model_name = meta.get("model") or ("quorum-scripted" if meta.get("provider") == "mock" else meta.get("provider"))

    steps = []
    for s in t["spans"]:
        if s["kind"] == "tool":
            steps.append({"step_type": "tool_call", "tool_name": "financial_model", "label": "Run financial model",
                          "input_summary": json.dumps(s.get("input") or {}),
                          "output_summary": json.dumps({"winner": s["output"].get("winner"),
                                                        "options": s.get("options")}, default=str)[:4000],
                          "status": "success"})
            continue
        agent = s.get("agent")
        sent = _post("/api/traces", {
            "project_id": c["project"],
            "trace_id": f"{session_id}-{len(steps):02d}-{agent}",
            "model": model_name,
            "input_messages": [{"role": "system", "content": s.get("prompt_system", "")},
                               {"role": "user", "content": s.get("prompt_user", "")}],
            "output_message": s.get("final", ""),
            "latency_ms": int((s.get("latency_s") or 0) * 1000),
            "token_count_input": ((s.get("llm_meta") or {}).get("usage") or {}).get("prompt_tokens", 0),
            "token_count_output": ((s.get("llm_meta") or {}).get("usage") or {}).get("completion_tokens", 0),
            "agent_id": f"quorum-{agent}",
            "agent_name": f"Quorum {s.get('agent_name') or agent}",
            "session_id": session_id,
            "metadata": {**common, "backs": s.get("backs"), "cited_facts": s.get("facts"),
                         "grounding_failed": bool(s.get("grounding_failed")),
                         "ungrounded_figures": s.get("ungrounded") or [],
                         "blocked_reason": s.get("blocked_reason"),
                         "backed_in_text": s.get("backed_in_text"),
                         "planned_line": s.get("planned"), "llm_raw": s.get("llm_raw"),
                         "llm_error": s.get("llm_error")},
        })
        steps.append({"step_type": "reasoning", "label": f"{s.get('agent_name') or agent} speaks",
                      "input_summary": f"backs {s.get('backs') or 'none'}; cites {', '.join(s.get('facts') or [])}",
                      "output_summary": s.get("final", ""),
                      "duration_ms": int((s.get("latency_s") or 0) * 1000),
                      "status": "error" if s.get("grounding_failed") else "success"})
        if sent is None:
            break

    out = t["output"]
    steps.append({"step_type": "final_answer", "label": "Board decision",
                  "output_summary": json.dumps({"decision": out.get("winner") or "no go",
                                                "model_decision": out.get("model_winner"),
                                                "votes": out.get("votes")})})
    _post("/api/trajectories", {
        "project_id": c["project"], "conversation_id": session_id, "request_id": session_id,
        "agent_id": "quorum-board", "agent_name": "Quorum Board",
        "steps": steps, "total_duration_ms": int(t["duration_s"] * 1000),
        "final_status": "success" if out.get("winner") == out.get("model_winner") else "error",
        "model": model_name,
    })
    _post("/api/traces", {
        "project_id": c["project"], "model": "session-tracker", "input_messages": [],
        "output_message": "Session ended", "latency_ms": 0, "session_id": session_id,
        "agent_id": "quorum-board", "agent_name": "Quorum Board",
        "metadata": {"session_end": True, "session_id": session_id, "session_end_reason": "meeting adjourned"},
    })
    print(f"[prism] exported meeting {session_id} ({len(steps)} steps)")


def trace_single(agent_name, agent_id, system, user, output, meta, latency_ms, metadata=None):
    """Send one standalone LLM call (e.g. option drafting) to PRISM in the background."""
    if not prism_enabled():
        return
    c = _cfg()
    usage = (meta or {}).get("usage") or {}
    body = {"project_id": c["project"], "model": (meta or {}).get("model") or "unknown",
            "input_messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "output_message": output or "", "latency_ms": latency_ms,
            "token_count_input": usage.get("prompt_tokens", 0), "token_count_output": usage.get("completion_tokens", 0),
            "agent_id": agent_id, "agent_name": agent_name, "metadata": metadata or {}}
    threading.Thread(target=_post, args=("/api/traces", body), daemon=False).start()
