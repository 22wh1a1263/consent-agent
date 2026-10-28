"""Tool registry. Each tool declares exactly which fields it may reveal
(least privilege) and which fields are always withheld from the LLM."""
import re
from typing import Any

from .db import CATEGORIES

WITHHELD_ALWAYS = ["note", "card_last4"]

TOOLS: dict[str, dict[str, Any]] = {
    "search_expenses": {
        "description": "List individual expenses, optionally filtered by month, category or merchant.",
        "params": {
            "month": "YYYY-MM (optional)",
            "category": f"one of {CATEGORIES} (optional)",
            "merchant": "merchant name (optional)",
            "limit": "max rows, 1-50 (default 10)",
        },
        "fields": ["date", "merchant", "category", "amount"],
    },
    "summarize_by_category": {
        "description": "Total spend per category, optionally for one month or one category.",
        "params": {"month": "YYYY-MM (optional)", "category": f"one of {CATEGORIES} (optional)"},
        "fields": ["category", "amount"],
    },
    "top_merchants": {
        "description": "Merchants ranked by total spend, optionally for one month.",
        "params": {"month": "YYYY-MM (optional)", "limit": "1-20 (default 5)"},
        "fields": ["merchant", "amount"],
    },
}

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def validate_args(tool: str, args: dict) -> dict:
    """Validate and normalise tool arguments. The LLM is untrusted input."""
    if tool not in TOOLS:
        raise ValueError(f"unknown tool: {tool}")
    allowed = set(TOOLS[tool]["params"])
    clean: dict[str, Any] = {}
    for key, value in (args or {}).items():
        if key not in allowed:
            raise ValueError(f"unexpected argument: {key}")
        if value is None:
            continue
        if key == "month":
            if not isinstance(value, str) or not _MONTH_RE.match(value):
                raise ValueError("month must look like 2026-10")
        elif key == "category":
            match = next((c for c in CATEGORIES if c.lower() == str(value).lower()), None)
            if not match:
                raise ValueError(f"category must be one of {CATEGORIES}")
            value = match
        elif key == "merchant":
            value = str(value).strip()[:60]
        elif key == "limit":
            value = int(value)
            cap = 20 if tool == "top_merchants" else 50
            if not 1 <= value <= cap:
                raise ValueError(f"limit must be 1-{cap}")
        clean[key] = value
    return clean


def _where(user_id: int, args: dict) -> tuple[str, list]:
    clauses, params = ["user_id = ?"], [user_id]  # <- isolation: always scoped to the caller
    if args.get("month"):
        clauses.append("substr(date, 1, 7) = ?")
        params.append(args["month"])
    if args.get("category"):
        clauses.append("category = ?")
        params.append(args["category"])
    if args.get("merchant"):
        clauses.append("merchant LIKE ?")
        params.append(f"%{args['merchant']}%")
    return " AND ".join(clauses), params


def run_tool(conn, user_id: int, tool: str, args: dict) -> list[dict]:
    args = validate_args(tool, args)
    where, params = _where(user_id, args)
    if tool == "search_expenses":
        limit = args.get("limit", 10)
        rows = conn.execute(
            f"SELECT date, merchant, category, amount FROM expenses WHERE {where} "
            "ORDER BY date DESC, id DESC LIMIT ?",
            params + [limit],
        ).fetchall()
    elif tool == "summarize_by_category":
        rows = conn.execute(
            f"SELECT category, ROUND(SUM(amount), 2) AS amount FROM expenses WHERE {where} "
            "GROUP BY category ORDER BY amount DESC",
            params,
        ).fetchall()
    else:  # top_merchants
        limit = args.get("limit", 5)
        rows = conn.execute(
            f"SELECT merchant, ROUND(SUM(amount), 2) AS amount FROM expenses WHERE {where} "
            "GROUP BY merchant ORDER BY amount DESC LIMIT ?",
            params + [limit],
        ).fetchall()
    return redact(tool, [dict(r) for r in rows])


def redact(tool: str, rows: list[dict]) -> list[dict]:
    """Second line of defence: only fields declared for the tool can leave this function."""
    allowed = set(TOOLS[tool]["fields"])
    return [{k: v for k, v in row.items() if k in allowed} for row in rows]
