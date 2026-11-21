"""LLM provider adapter.

QUORUM_PROVIDER=mock     -> no network; agents speak their grounded script (default)
QUORUM_PROVIDER=nicrron  -> agents are voiced by a model served through Nicrron

Nicrron (https://api.nicrron.ai/v1) is OpenAI-compatible: POST /chat/completions,
GET /models. Configure NICRRON_API_KEY, NICRRON_BASE_URL, NICRRON_MODEL in quorum/.env.
Note: anthropic/claude-haiku-5-5 returned empty content for our prompts; openai/gpt-4.1-mini works.
"""
import json
import os
import urllib.request

PROVIDER = os.environ.get("QUORUM_PROVIDER", "mock").lower()
NICRRON_BASE_URL = os.environ.get("NICRRON_BASE_URL", "").rstrip("/")
NICRRON_API_KEY = os.environ.get("NICRRON_API_KEY", "")
NICRRON_MODEL = os.environ.get("NICRRON_MODEL", "")


def provider_name():
    return PROVIDER if PROVIDER == "nicrron" and NICRRON_BASE_URL else "mock"


def chat(system, user, max_tokens=220, temperature=0.6):
    """Return (text, meta). Raises on transport errors; caller falls back."""
    if provider_name() != "nicrron":
        return None, {"provider": "mock"}
    return _nicrron_chat(system, user, max_tokens, temperature)


def _nicrron_chat(system, user, max_tokens, temperature):
    body = {
        "model": NICRRON_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        f"{NICRRON_BASE_URL}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {NICRRON_API_KEY}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        out = json.loads(resp.read())
    choice = out["choices"][0]
    text = (choice.get("message") or {}).get("content")
    if not text:
        raise RuntimeError(f"empty reply from {NICRRON_MODEL} (finish_reason={choice.get('finish_reason')})")
    text = text.strip()
    return text, {"provider": "nicrron", "model": NICRRON_MODEL, "usage": out.get("usage")}
