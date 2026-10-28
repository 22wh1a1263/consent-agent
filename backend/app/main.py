"""Consent-Gated Personal Agent: API.

Flow: /chat plans a tool call (no data touched) -> if the tool isn't approved the API returns
`consent_required` -> the user approves via /consent/{id} -> only then does the tool run, with
only the fields it is allowed to reveal. Every decision is written to /receipts.
"""
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import llm
from .db import connect, init_db
from .planner import plan as make_plan
from .planner import template_answer
from .tools import TOOLS, WITHHELD_ALWAYS, run_tool, validate_args

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me-use-a-long-random-value-in-prod")
LATENCY_BUDGET_MS = float(os.environ.get("LATENCY_BUDGET_MS", "1500"))
ALL_FIELDS = ["date", "merchant", "category", "amount", "note", "card_last4"]

@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(title="Consent-Gated Personal Agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


def ref_date() -> date:
    raw = os.environ.get("REFERENCE_DATE")
    return date.fromisoformat(raw) if raw else date.today()


def ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


# ---------------- auth (demo: username only, no password) ----------------

class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=40)


@app.post("/auth/login")
def login(body: LoginBody):
    conn = connect()
    row = conn.execute("SELECT id, username FROM users WHERE username = ?", (body.username.lower(),)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Unknown demo user. Try alice or bob.")
    token = jwt.encode(
        {"sub": str(row["id"]), "username": row["username"],
         "exp": datetime.now(timezone.utc) + timedelta(hours=12)},
        JWT_SECRET, algorithm="HS256",
    )
    return {"token": token, "username": row["username"]}


def current_user(authorization: str = Header(default="")) -> dict:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    try:
        data = jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
        return {"id": int(data["sub"]), "username": data["username"]}
    except Exception:
        raise HTTPException(401, "Invalid or expired token")


# ---------------- core flow ----------------

class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class ConsentBody(BaseModel):
    approve: bool
    remember: bool = False  # standing approval for this tool until revoked


def _history(conn, user_id: int, n: int = 6) -> list[dict]:
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, n)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def _remember(conn, user_id: int, role: str, content: str) -> None:
    conn.execute("INSERT INTO messages (user_id, role, content) VALUES (?,?,?)", (user_id, role, content))


def _metric(conn, user_id, tool, plan_ms=0.0, tool_ms=0.0, llm_ms=0.0):
    conn.execute(
        "INSERT INTO metrics (user_id, tool, plan_ms, tool_ms, llm_ms, total_ms) VALUES (?,?,?,?,?,?)",
        (user_id, tool, plan_ms, tool_ms, llm_ms, round(plan_ms + tool_ms + llm_ms, 2)),
    )


def _receipt(conn, user_id, tool, args, decision, row_count):
    shared = TOOLS[tool]["fields"] if decision != "denied" else []
    withheld = [f for f in ALL_FIELDS if f not in shared]
    conn.execute(
        "INSERT INTO receipts (user_id, tool, args_json, decision, fields_shared_json, fields_withheld_json, row_count) "
        "VALUES (?,?,?,?,?,?,?)",
        (user_id, tool, json.dumps(args), decision, json.dumps(shared), json.dumps(withheld), row_count),
    )


def _execute(conn, user: dict, question: str, tool: str, args: dict, decision: str, plan_ms: float, source: str):
    t0 = time.perf_counter()
    rows = run_tool(conn, user["id"], tool, args)
    tool_ms = ms(t0)

    t1 = time.perf_counter()
    answer = llm.compose(question, tool, args, rows) if llm.enabled() else None
    if answer is None:
        answer = template_answer(tool, args, rows)
    llm_ms = ms(t1)

    _receipt(conn, user["id"], tool, args, decision, len(rows))
    _metric(conn, user["id"], tool, plan_ms, tool_ms, llm_ms)
    _remember(conn, user["id"], "assistant", answer)
    conn.commit()
    return {
        "status": "answered", "answer": answer, "tool": tool, "args": args, "rows": rows,
        "planner": source, "timings_ms": {"plan": plan_ms, "tool": tool_ms, "llm": llm_ms,
                                          "total": round(plan_ms + tool_ms + llm_ms, 2)},
    }


@app.post("/chat")
def chat(body: ChatBody, user: dict = Depends(current_user)):
    conn = connect()
    try:
        state = conn.execute("SELECT last_plan_json FROM session_state WHERE user_id = ?", (user["id"],)).fetchone()
        last_plan = json.loads(state["last_plan_json"]) if state and state["last_plan_json"] else None
        history = _history(conn, user["id"])

        t0 = time.perf_counter()
        plan, source = make_plan(body.message, history, last_plan, ref_date())
        plan_ms = ms(t0)
        _remember(conn, user["id"], "user", body.message)

        if not plan.get("tool"):
            reply = plan["reply"]
            _remember(conn, user["id"], "assistant", reply)
            _metric(conn, user["id"], None, plan_ms)
            conn.commit()
            return {"status": "answered", "answer": reply, "tool": None, "rows": [], "planner": source,
                    "timings_ms": {"plan": plan_ms, "tool": 0, "llm": 0, "total": plan_ms}}

        tool, args = plan["tool"], validate_args(plan["tool"], plan.get("args", {}))
        conn.execute(
            "INSERT INTO session_state (user_id, last_plan_json) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET last_plan_json = excluded.last_plan_json",
            (user["id"], json.dumps({"tool": tool, "args": args})),
        )

        granted = conn.execute("SELECT 1 FROM grants WHERE user_id = ? AND tool = ?", (user["id"], tool)).fetchone()
        if granted:
            return _execute(conn, user, body.message, tool, args, "approved_standing", plan_ms, source)

        pending_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO pending (id, user_id, question, tool, args_json, plan_ms, source) VALUES (?,?,?,?,?,?,?)",
            (pending_id, user["id"], body.message, tool, json.dumps(args), plan_ms, source),
        )
        conn.commit()
        fields = TOOLS[tool]["fields"]
        return {
            "status": "consent_required", "pending_id": pending_id, "tool": tool, "args": args,
            "fields_requested": fields,
            "fields_withheld": [f for f in ALL_FIELDS if f not in fields],
            "message": f"To answer this I need to read your expenses ({', '.join(fields)}). Allow it?",
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@app.post("/consent/{pending_id}")
def consent(pending_id: str, body: ConsentBody, user: dict = Depends(current_user)):
    conn = connect()
    try:
        # Scoped to the caller: another user's pending id simply doesn't exist for you.
        row = conn.execute(
            "SELECT * FROM pending WHERE id = ? AND user_id = ? AND status = 'pending'", (pending_id, user["id"])
        ).fetchone()
        if not row:
            raise HTTPException(404, "No pending request with that id")
        tool, args = row["tool"], json.loads(row["args_json"])

        if not body.approve:
            conn.execute("UPDATE pending SET status = 'denied' WHERE id = ?", (pending_id,))
            _receipt(conn, user["id"], tool, args, "denied", 0)
            answer = "Okay, I didn't access your data."
            _remember(conn, user["id"], "assistant", answer)
            conn.commit()
            return {"status": "denied", "answer": answer, "tool": tool, "rows": []}

        conn.execute("UPDATE pending SET status = 'approved' WHERE id = ?", (pending_id,))
        if body.remember:
            conn.execute("INSERT OR IGNORE INTO grants (user_id, tool) VALUES (?, ?)", (user["id"], tool))
        decision = "approved_standing" if body.remember else "approved_once"
        return _execute(conn, user, row["question"], tool, args, decision, row["plan_ms"], row["source"])
    finally:
        conn.close()


# ---------------- receipts, grants, stats ----------------

@app.get("/receipts")
def receipts(user: dict = Depends(current_user)):
    conn = connect()
    rows = conn.execute("SELECT * FROM receipts WHERE user_id = ? ORDER BY id DESC LIMIT 100", (user["id"],)).fetchall()
    conn.close()
    return [
        {"id": r["id"], "tool": r["tool"], "args": json.loads(r["args_json"]), "decision": r["decision"],
         "fields_shared": json.loads(r["fields_shared_json"]), "fields_withheld": json.loads(r["fields_withheld_json"]),
         "row_count": r["row_count"], "ts": r["ts"]}
        for r in rows
    ]


@app.get("/grants")
def grants(user: dict = Depends(current_user)):
    conn = connect()
    rows = conn.execute("SELECT tool, created_at FROM grants WHERE user_id = ?", (user["id"],)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.delete("/grants/{tool}")
def revoke(tool: str, user: dict = Depends(current_user)):
    conn = connect()
    conn.execute("DELETE FROM grants WHERE user_id = ? AND tool = ?", (user["id"], tool))
    conn.commit()
    conn.close()
    return {"revoked": tool}


@app.get("/stats")
def stats(user: dict = Depends(current_user)):
    conn = connect()
    rows = conn.execute("SELECT * FROM metrics WHERE user_id = ?", (user["id"],)).fetchall()
    conn.close()
    n = len(rows)
    if n == 0:
        return {"requests": 0, "budget_ms": LATENCY_BUDGET_MS}
    totals = sorted(r["total_ms"] for r in rows)
    p95 = totals[min(n - 1, int(0.95 * n))]
    by_tool: dict[str, int] = {}
    for r in rows:
        by_tool[r["tool"] or "none"] = by_tool.get(r["tool"] or "none", 0) + 1
    avg = lambda k: round(sum(r[k] for r in rows) / n, 2)
    return {
        "requests": n, "avg_total_ms": avg("total_ms"), "p95_total_ms": p95,
        "avg_plan_ms": avg("plan_ms"), "avg_tool_ms": avg("tool_ms"), "avg_llm_ms": avg("llm_ms"),
        "budget_ms": LATENCY_BUDGET_MS,
        "within_budget_pct": round(100 * sum(1 for t in totals if t <= LATENCY_BUDGET_MS) / n, 1),
        "by_tool": by_tool,
    }


@app.get("/health")
def health():
    return {"ok": True, "llm": llm.enabled()}
