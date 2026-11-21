"""Quorum server: zero dependencies (Python 3.9+ stdlib only).

    python3 backend/server.py          -> http://localhost:8000
"""
import json
import os
import re
import sys
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _load_env_file():
    """Load quorum/.env (KEY=value lines) without overriding real env vars."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file()
import agents  # noqa: E402
import llm  # noqa: E402
import model  # noqa: E402
import tracing  # noqa: E402
from tracing import Trace, prism_enabled  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")
SCENARIO_DIR = os.path.join(ROOT, "data", "scenarios")
SCENARIO_ORDER = ["acme", "brightpath", "loop", "northwind"]
PORT = int(os.environ.get("PORT", "8000"))
TURN_DELAY = float(os.environ.get("QUORUM_TURN_DELAY", "0.9"))  # dramatic pause in mock mode


def scenario_ids():
    found = {f[:-5] for f in os.listdir(SCENARIO_DIR) if f.endswith(".json")}
    return [s for s in SCENARIO_ORDER if s in found] + sorted(found - set(SCENARIO_ORDER))


LEVER_LIMITS = {  # key: (min, max, step)
    "engineers": (0, 20, 1),
    "marketing_budget": (0, 3_000_000, 50_000),
    "price_change": (-0.3, 0.5, 0.05),
    "cost_cut": (0, 250_000, 10_000),
    "fundraise": (0, 20_000_000, 250_000),
}


def clean_lever(key, value):
    lo, hi, step = LEVER_LIMITS[key]
    v = max(lo, min(hi, float(value or 0)))
    v = round(v / step) * step
    return int(v) if key == "engineers" else round(v, 4)


def option_label(o):
    parts = []
    if o.get("engineers"):
        n = int(o["engineers"])
        parts.append(f"Hire {n} engineer{'s' if n != 1 else ''}")
    if o.get("marketing_budget"):
        parts.append(f"{agents.money(o['marketing_budget'])} marketing")
    if o.get("price_change"):
        p = o["price_change"]
        parts.append(f"{'Raise' if p > 0 else 'Cut'} prices {abs(round(p * 100))}%")
    if o.get("cost_cut"):
        parts.append(f"Cut costs {agents.money(o['cost_cut'])}/mo")
    if o.get("fundraise"):
        parts.append(f"Raise {agents.money(o['fundraise'])}")
    if parts == [f"{agents.money(o.get('marketing_budget', 0))} marketing"]:
        parts[0] += " push"
    label = " + ".join(parts) if parts else "Keep the cash"
    return label[0].upper() + label[1:]


def load_data(scenario_id=None, options=None):
    sid = scenario_id if scenario_id in scenario_ids() else scenario_ids()[0]
    with open(os.path.join(SCENARIO_DIR, f"{sid}.json")) as f:
        d = json.load(f)
    if options:  # user-edited or drafted options from the UI
        d["options"] = [{"id": o["id"], **{k: clean_lever(k, o.get(k)) for k in LEVER_LIMITS}}
                        for o in options if o.get("id") in OPTION_IDS]
    for o in d["options"]:
        o["label"] = option_label(o)
    return d


OPTION_IDS = ("A", "B", "C", "D")


# ----------------------------------------------------------------- option drafting
def draft_options(data, question):
    """Ask Nicrron to turn a free-text question into 2-4 options the model can simulate.
    Returns {"ok": True, "options": [...], "note": str} or {"ok": False, "reason": str}."""
    if llm.provider_name() != "nicrron":
        return {"ok": False, "reason": "Drafting options needs Nicrron. Set QUORUM_PROVIDER=nicrron in quorum/.env."}
    c = data["company"]
    system = (
        "You turn a company's financial question into options for a board meeting. The financial model simulates five levers per option; "
        "leave a lever at 0 when the option doesn't use it:\n"
        "- engineers: whole number of engineers to hire (0 to 20)\n"
        "- marketing_budget: US dollars of marketing spend over 6 months (0 to 3000000)\n"
        "- price_change: fraction change to prices, e.g. 0.15 for +15%, -0.1 for -10% (-0.3 to 0.5)\n"
        "- cost_cut: US dollars per month of operating costs removed, e.g. layoffs or vendor savings (0 to 60% of monthly operating expenses)\n"
        "- fundraise: US dollars of new investment raised now (0 to 20000000)\n"
        "Return ONLY a JSON object, no prose, in one of two shapes:\n"
        '{"supported": true, "options": [{"engineers": 0, "marketing_budget": 0, "price_change": 0, "cost_cut": 0, "fundraise": 0}, ...], "note": "<one short sentence on how you read the question>"}\n'
        '{"supported": false, "reason": "<one short sentence: what the question asks that these five levers cannot represent>"}\n'
        "Rules: 2 to 4 options, all different, covering the real alternatives in the question. Use amounts the question names exactly. "
        "Otherwise size options for this company: new spend over 24 months (engineers x engineer cost x 24 + marketing) should stay under half the cash; "
        "'a few' engineers means 2 to 4, 'a team' 5 to 8; a layoff of N% means cost_cut = N% of monthly operating expenses. "
        "Include a combined option when the question weighs two levers against each other. "
        "Use supported=false only if the question is mainly about something none of the five levers represent (offices, acquisitions, legal, product strategy)."
    )
    user = (f"Company: {c['name']} ({c['sector']}), cash {agents.money(c['cash'])}, MRR {agents.money(c['mrr'])}, "
            f"monthly operating expenses {agents.money(c['monthly_opex'])}, {c['headcount']} people, "
            f"engineer cost {agents.money(data['assumptions']['eng_monthly_cost'])} per month.\nQuestion: {question}")
    t0 = time.time()
    try:
        text, meta = llm.chat(system, user, max_tokens=400, temperature=0.2)
    except Exception as e:
        return {"ok": False, "reason": f"Nicrron call failed: {e}"}
    tracing.trace_single("Quorum Option Drafter", "quorum-option-drafter", system, user, text, meta,
                         int((time.time() - t0) * 1000), {"scenario": data.get("id"), "question": question})
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        out = json.loads(m.group(0)) if m else None
    except ValueError:
        out = None
    if not isinstance(out, dict):
        return {"ok": False, "reason": "Couldn't read options from the model's reply. Try rephrasing the question."}
    if not out.get("supported", True):
        return {"ok": False, "reason": out.get("reason") or "The model can only simulate hiring, marketing, pricing, cost cuts and fundraising."}
    opts, seen = [], set()
    for o in out.get("options") or []:
        try:
            vals = {k: clean_lever(k, o.get(k)) for k in LEVER_LIMITS}
        except (TypeError, ValueError):
            continue
        if vals["cost_cut"] > c["monthly_opex"] * 0.6:
            vals["cost_cut"] = clean_lever("cost_cut", c["monthly_opex"] * 0.6)
        sig = tuple(vals.values())
        if sig in seen:
            continue
        seen.add(sig)
        opts.append({"id": OPTION_IDS[len(opts)], **vals})
        if len(opts) == len(OPTION_IDS):
            break
    if len(opts) < 2:
        return {"ok": False, "reason": "The model gave fewer than two distinct options. Try a more specific question."}
    for o in opts:
        o["label"] = option_label(o)
    return {"ok": True, "options": opts, "note": out.get("note", "")}


# ----------------------------------------------------------------- voicing
def voice_turn(turn, facts, transcript, data, guardrails, ceo_note):
    """Ask the LLM to say the planned position in character. Returns (text, span_fields)."""
    agent = agents.AGENTS[turn["agent"]]
    fact_sheet = "\n".join(f"[{f['id']}] {f['text']}: {f['value']}" for f in facts)
    history = "\n".join(f"{agents.AGENTS[t['agent']]['name']}: {t['text']}" for t in transcript) or "(meeting just opened)"
    backs = f"Option {turn['backs']}" if turn["backs"] else "no option"

    system = (f"You are the {agent['name']} of {data['company']['name']} in a board meeting. {agent['mandate']} "
              "Speak in first person, sharp and conversational, at most 55 words. No lists, no markdown.")
    if guardrails:
        system += (" HARD RULE: use only figures that appear on the fact sheet, written exactly as shown. "
                   "Never invent or estimate a number.")
        if turn["tone"] == "verdict":
            stance = (f"You are announcing the board's decision: {backs}." if turn["backs"]
                      else "You are announcing that no option passes and the company holds its cash.")
        elif turn["backs"]:
            stance = f"Your position: you back {backs}. Do not say you back or recommend any other option."
        else:
            stance = "Do not back, recommend or rule on any option in this line."
        user = (f"FACT SHEET\n{fact_sheet}\n\nTRANSCRIPT\n{history}\n\n"
                f"{stance} The points you must make (rephrase in your own voice, keep every figure exact):\n"
                f"{turn['text']}")
    else:
        # "Before" mode for PRISM: the agent improvises freely.
        note = f"\nCEO's note to the board: {ceo_note}" if ceo_note else ""
        user = (f"Company: {json.dumps(data['company'])}\nQuestion: {data['question']}{note}\n\n"
                f"TRANSCRIPT\n{history}\n\nGive your view.")
        if turn["tone"] == "verdict":
            user += " You are deciding. Start with 'Decision: Option X' where X is A, B or C."

    span = {"prompt_system": system, "prompt_user": user}
    try:
        text, meta = llm.chat(system, user)
    except Exception as e:
        span.update(llm_error=str(e))
        text, meta = None, {"provider": "error"}
    span.update(llm_meta=meta, llm_raw=text)

    if text is None:  # mock provider or LLM failure: grounded script
        return turn["text"], span

    text = re.sub(r"\s*\[F\d+\]", "", text).strip()
    if guardrails:
        extra = " ".join([data["question"], f"{round(data['assumptions']['stress_mrr_shock'] * 100)}%"] + [o["label"] for o in data["options"]]
                         + [agents.money(o["marketing_budget"]) for o in data["options"]])
        bad = agents.ungrounded_numbers(text, facts, extra)
        span["ungrounded"] = bad
        backed = set(re.findall(r"\b(?:back(?:ing)?|support(?:ing)?|recommend(?:ing)?|approv(?:e|ing)|go(?:ing)? with|choose|choosing|decision:?)\s+(?:for\s+)?option\s+([ABC])\b", text, re.I))
        backed = {b.upper() for b in backed}
        off_position = bool(backed - {turn["backs"]}) if turn["backs"] else bool(backed)
        span["backed_in_text"] = sorted(backed)
        reasons = []
        if bad:
            reasons.append("ungrounded figure: " + ", ".join(bad))
        if off_position:
            reasons.append(f"backed {', '.join(sorted(backed))} instead of {turn['backs'] or 'no option'}")
        if reasons:
            span["grounding_failed"] = True
            span["blocked_reason"] = "; ".join(reasons)
            return turn["text"], span
    return text, span


# ----------------------------------------------------------------- handler
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=FRONTEND, **kw)

    def log_message(self, fmt, *args):
        if "/api/" in self.path:
            sys.stderr.write("[quorum] " + fmt % args + "\n")

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/api/scenarios":
            out = []
            for sid in scenario_ids():
                d = load_data(sid)
                out.append({"id": sid, "name": d["company"]["name"], "sector": d["company"]["sector"]})
            return self._json(out)
        if path == "/api/scenario":
            sid = dict(p.split("=", 1) for p in query.split("&") if "=" in p).get("id")
            d = load_data(sid)
            return self._json({**d, "agents": agents.AGENTS, "provider": llm.provider_name(), "prism": prism_enabled()})
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/evaluate":
            req = self._body()
            d = load_data(req.get("scenario"), req.get("options"))
            return self._json({**model.evaluate(d, req.get("overrides")), "labels": {o["id"]: o["label"] for o in d["options"]}})
        if self.path == "/api/draft-options":
            req = self._body()
            q = (req.get("question") or "").strip()
            if not q:
                return self._json({"ok": False, "reason": "Type a question first."})
            return self._json(draft_options(load_data(req.get("scenario")), q[:500]))
        if self.path == "/api/deliberate":
            return self._deliberate(self._body())
        self._json({"error": "not found"}, 404)

    # Server-sent events stream of the board meeting
    def _send(self, event, data):
        self.wfile.write(f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n".encode())
        self.wfile.flush()

    def _deliberate(self, req):
        data = load_data(req.get("scenario"), req.get("options"))
        if req.get("question"):
            data["question"] = req["question"]
        ceo_note = (req.get("ceo_note") or "").strip()
        guardrails = req.get("guardrails", True)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        trace = Trace("board_meeting", {"provider": llm.provider_name(), "model": llm.NICRRON_MODEL if llm.provider_name() == "nicrron" else None, "guardrails": guardrails,
                                        "ceo_note": ceo_note, "overrides": req.get("overrides"),
                                        "scenario": data.get("id"), "options": data["options"]})
        try:
            ev = model.evaluate(data, req.get("overrides"))
            facts, _ = agents.build_facts(data, ev)
            trace.span("financial_model", "tool", input=req.get("overrides"),
                       output={k: v for k, v in ev.items() if k != "options"},
                       options=[{k: v for k, v in o.items() if k != "cash_curve"} for o in ev["options"]])
            self._send("facts", {"facts": facts, "metrics": ev})

            turns, votes = agents.plan_turns(data, ev, ceo_note)
            transcript = []
            llm_winner = None
            for i, t in enumerate(turns):
                self._send("thinking", {"agent": t["agent"], "index": i})
                t0 = time.time()
                text, span = voice_turn(t, facts, transcript, data, guardrails, ceo_note)
                if llm.provider_name() == "mock":
                    time.sleep(TURN_DELAY)
                if not guardrails and t["tone"] == "verdict":
                    m = re.search(r"Option\s*([ABC])", text)
                    llm_winner = m.group(1) if m else None
                out = {**t, "text": text, "index": i, "grounding_failed": bool(span.get("grounding_failed")),
                       "blocked_reason": span.get("blocked_reason")}
                transcript.append(out)
                trace.span(f"turn:{t['agent']}", "agent", agent=t["agent"], agent_name=agents.AGENTS[t["agent"]]["name"], planned=t["text"],
                           backs=t["backs"], facts=t["facts"], final=text,
                           latency_s=round(time.time() - t0, 3), **span)
                self._send("turn", out)

            winner = ev["winner"] if guardrails else (llm_winner or ev["winner"])
            if not guardrails:
                votes = {**votes, "chair": winner}
            trace_info = trace.finish({"winner": winner, "model_winner": ev["winner"], "votes": votes})
            self._send("verdict", {"winner": winner, "model_winner": ev["winner"], "votes": votes,
                                   "trace": trace_info})
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as e:
            self._send("error", {"message": str(e)})
        self._send("done", {})


if __name__ == "__main__":
    print(f"Quorum running at http://localhost:{PORT}  (provider: {llm.provider_name()}, PRISM: {'on' if prism_enabled() else 'off'})")
    ThreadingHTTPServer((os.environ.get("HOST", "127.0.0.1"), PORT), Handler).serve_forever()
