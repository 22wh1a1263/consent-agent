"""Optional LLM layer (any OpenAI-compatible API; defaults to Groq).

Set LLM_API_KEY to enable. Without it the app runs fully offline with the rule planner.
The LLM never sees raw database rows: only the fields a tool is allowed to reveal,
and only after the user approves that tool call.
"""
import json
import os
from datetime import date

import httpx

from .tools import TOOLS, validate_args

MAX_HISTORY = 6  # context handling: only the last few turns are sent to the model


def enabled() -> bool:
    return bool(os.environ.get("LLM_API_KEY"))


def _post(payload: dict) -> dict:
    base = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    resp = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
        json={"model": os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile"), "temperature": 0, **payload},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def _tool_schemas() -> list[dict]:
    schemas = []
    for name, spec in TOOLS.items():
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": {
                    "type": "object",
                    "properties": {p: {"type": "string", "description": d} for p, d in spec["params"].items()},
                    "additionalProperties": False,
                },
            },
        })
    return schemas


def plan(message: str, history: list[dict], ref: date) -> dict | None:
    """Ask the model to pick a tool. Returns None on any failure so the caller can fall back."""
    system = (
        "You help a user query their own expenses using tools. You cannot see any data yourself. "
        f"Today is {ref.isoformat()}. Pick the single best tool; if none fits, answer briefly in plain text. "
        "Never ask for card digits or private notes."
    )
    msgs = [{"role": "system", "content": system}]
    msgs += [{"role": m["role"], "content": m["content"]} for m in history[-MAX_HISTORY:]]
    msgs.append({"role": "user", "content": message})
    try:
        data = _post({"messages": msgs, "tools": _tool_schemas(), "tool_choice": "auto"})
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if calls:
            name = calls[0]["function"]["name"]
            args = validate_args(name, json.loads(calls[0]["function"].get("arguments") or "{}"))
            return {"tool": name, "args": args}
        return {"tool": None, "reply": (msg.get("content") or "").strip() or "I can help with your expenses."}
    except Exception:
        return None


def compose(question: str, tool: str, args: dict, rows: list[dict]) -> str | None:
    """Write the final answer from the minimal, approved rows. None on failure."""
    try:
        data = _post({
            "messages": [
                {"role": "system", "content": "Answer the user's question using ONLY the JSON rows given. "
                                              "Amounts are in Indian rupees. Be brief and plain."},
                {"role": "user", "content": f"Question: {question}\nTool: {tool} {json.dumps(args)}\n"
                                            f"Rows: {json.dumps(rows)}"},
            ]
        })
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None
