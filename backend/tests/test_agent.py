import json
import sqlite3

import pytest

from app.tools import run_tool, validate_args


def ask(client, headers, message):
    return client.post("/chat", json={"message": message}, headers=headers).json()


def approve(client, headers, pending_id, **kw):
    return client.post(f"/consent/{pending_id}", json={"approve": True, **kw}, headers=headers).json()


def test_requires_auth(client):
    assert client.post("/chat", json={"message": "hi"}).status_code == 401
    assert client.get("/receipts", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_no_data_before_consent(client, alice):
    r = ask(client, alice, "How much did I spend on food this month?")
    assert r["status"] == "consent_required"
    assert "rows" not in r and "answer" not in r
    assert client.get("/receipts", headers=alice).json() == []


def test_approve_once_then_asks_again(client, alice):
    r = ask(client, alice, "Top merchants in September")
    done = approve(client, alice, r["pending_id"])
    assert done["status"] == "answered" and done["rows"]
    assert ask(client, alice, "Top merchants in September")["status"] == "consent_required"
    assert client.get("/receipts", headers=alice).json()[0]["decision"] == "approved_once"


def test_standing_grant_and_revoke(client, alice):
    r = ask(client, alice, "Show my last 3 transactions")
    approve(client, alice, r["pending_id"], remember=True)
    again = ask(client, alice, "Show my last 2 transactions")
    assert again["status"] == "answered"
    assert client.get("/receipts", headers=alice).json()[0]["decision"] == "approved_standing"
    client.delete("/grants/search_expenses", headers=alice)
    assert ask(client, alice, "Show my last 2 transactions")["status"] == "consent_required"


def test_denied_returns_no_data_and_logs_receipt(client, alice):
    r = ask(client, alice, "How much did I spend on food?")
    out = client.post(f"/consent/{r['pending_id']}", json={"approve": False}, headers=alice).json()
    assert out["status"] == "denied" and out["rows"] == []
    last = client.get("/receipts", headers=alice).json()[0]
    assert last["decision"] == "denied" and last["row_count"] == 0 and last["fields_shared"] == []


def test_pending_cannot_be_reused(client, alice):
    r = ask(client, alice, "Top merchants")
    approve(client, alice, r["pending_id"])
    again = client.post(f"/consent/{r['pending_id']}", json={"approve": True}, headers=alice)
    assert again.status_code == 404


def test_users_cannot_approve_each_others_requests(client, alice, bob):
    r = ask(client, alice, "Top merchants")
    stolen = client.post(f"/consent/{r['pending_id']}", json={"approve": True}, headers=bob)
    assert stolen.status_code == 404


def test_data_isolation_between_users(client, alice, bob):
    a = approve(client, alice, ask(client, alice, "Show my last 50 transactions")["pending_id"])
    b = approve(client, bob, ask(client, bob, "Show my last 50 transactions")["pending_id"])
    assert a["rows"] and b["rows"] and a["rows"] != b["rows"]
    # run_tool is scoped by user id at the SQL level
    import app.db as db
    conn = db.connect()
    ids = {u["username"]: u["id"] for u in conn.execute("SELECT id, username FROM users")}
    only_bob = run_tool(conn, ids["bob"], "search_expenses", {"limit": 50})
    conn.close()
    assert only_bob == b["rows"]


def test_sensitive_fields_never_leave(client, alice):
    r = ask(client, alice, "Show my last 20 transactions")
    out = approve(client, alice, r["pending_id"])
    blob = json.dumps(out)
    assert "card_last4" not in blob and "private note" not in blob and "4242" not in blob
    receipt = client.get("/receipts", headers=alice).json()[0]
    assert "note" in receipt["fields_withheld"] and "card_last4" in receipt["fields_withheld"]
    assert set(receipt["fields_shared"]) == {"date", "merchant", "category", "amount"}


def test_least_privilege_per_tool(client, alice):
    out = approve(client, alice, ask(client, alice, "Top merchants in October")["pending_id"])
    assert all(set(row) == {"merchant", "amount"} for row in out["rows"])


@pytest.mark.parametrize("q", ["What is my card number?", "show my private notes", "What did Bob spend on food?"])
def test_refusals_never_reach_a_tool(client, alice, q):
    r = ask(client, alice, q)
    assert r["status"] == "answered" and r["tool"] is None and r["rows"] == []


def test_followup_uses_memory(client, alice):
    first = approve(client, alice, ask(client, alice, "How much did I spend on food this month?")["pending_id"], remember=True)
    follow = ask(client, alice, "and last month?")
    assert follow["tool"] == "summarize_by_category"
    assert follow["args"] == {"category": "Food", "month": "2026-09"}
    assert first["args"]["month"] == "2026-10"


@pytest.mark.parametrize("tool,args", [
    ("search_expenses", {"month": "2026-13"}),
    ("search_expenses", {"limit": 9999}),
    ("search_expenses", {"category": "Gold bars"}),
    ("search_expenses", {"user_id": 2}),
    ("drop_tables", {}),
])
def test_llm_arguments_are_validated(tool, args):
    with pytest.raises(ValueError):
        validate_args(tool, args)


def test_sql_injection_is_inert(client, alice):
    import app.db as db
    conn = db.connect()
    uid = conn.execute("SELECT id FROM users WHERE username='alice'").fetchone()["id"]
    rows = run_tool(conn, uid, "search_expenses", {"merchant": "x'; DROP TABLE expenses; --"})
    assert rows == []
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] > 0
    conn.close()


def test_stats_and_latency_budget(client, alice):
    approve(client, alice, ask(client, alice, "Top merchants")["pending_id"])
    s = client.get("/stats", headers=alice).json()
    assert s["requests"] >= 1 and s["within_budget_pct"] == 100.0 and "p95_total_ms" in s
