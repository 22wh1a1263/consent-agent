"""Turns a user question into a tool call.

Two planners share one interface:
  * rules  - offline, deterministic (used for tests/evals and as a fallback)
  * LLM    - used when LLM_API_KEY is set (see llm.py)

The planner only ever sees the question and recent chat history, never the user's data.
"""
import re
from datetime import date

from .db import CATEGORIES, MERCHANTS
from .tools import TOOLS

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}

CATEGORY_WORDS = {
    "Food": ["food", "restaurant", "dining", "eating out", "takeaway"],
    "Groceries": ["grocer"],
    "Transport": ["transport", "cab", "commute", "taxi", "ride"],
    "Shopping": ["shopping", "clothes"],
    "Entertainment": ["entertainment", "movie", "subscription"],
    "Bills": ["bill", "recharge", "utilit"],
    "Health": ["health", "pharmacy", "medical", "gym"],
    "Travel": ["travel", "trip", "flight"],
}

ALL_MERCHANTS = sorted({m for ms in MERCHANTS.values() for m in ms}, key=len, reverse=True)

SENSITIVE_WORDS = ["card number", "card digits", "last 4", "last four", "cvv", "password", "my notes",
                   "private note", "the note", "notes"]
OTHER_USER_WORDS = ["other user", "another user", "someone else", "everyone's"]
# "What did Bob spend...", "how much does Priya spend..." (third person, not I/we/you)
OTHER_PRONOUN_RE = re.compile(r"\b(his|her|hers|their|theirs)\b")
OTHER_PERSON_RE = re.compile(r"\b(did|does|has|do)\s+(?!i\b|we\b|you\b|my\b|the\b)([a-z]+)\s+(spend|spent|pay|paid|buy|bought)\b")
DEMO_USERS = ["alice", "bob"]
SUMMARY_WORDS = ["breakdown", "by category", "per category", "each category", "summar", "categories"]
LIST_WORDS = ["list", "show", "transactions", "recent", "latest", "purchases", "orders", "expenses"]
TOP_WORDS = ["top", "most", "biggest", "highest", "rank"]
SPEND_WORDS = ["how much", "spend", "spent", "total", "cost", "paid"]

HELP_REPLY = ("I can answer questions about your expenses: totals by category, your top merchants, "
              "or a list of recent transactions. Try \"How much did I spend on food this month?\"")


def _month_str(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


def resolve_month(text: str, ref: date) -> str | None:
    t = text.lower()
    if "this month" in t:
        return _month_str(ref.year, ref.month)
    if "last month" in t or "previous month" in t:
        y, m = (ref.year, ref.month - 1) if ref.month > 1 else (ref.year - 1, 12)
        return _month_str(y, m)
    for name, num in MONTHS.items():
        if re.search(rf"\b{name}\b", t):
            return _month_str(ref.year, num)
    return None


def resolve_category(text: str) -> str | None:
    t = text.lower()
    for cat in CATEGORIES:
        if re.search(rf"\b{cat.lower()}\b", t):
            return cat
    for cat, words in CATEGORY_WORDS.items():
        if any(w in t for w in words):
            return cat
    return None


def resolve_merchant(text: str) -> str | None:
    t = text.lower()
    return next((m for m in ALL_MERCHANTS if m.lower() in t), None)


def _number(text: str, default: int, cap: int) -> int:
    m = re.search(r"\b(?:top|last|latest|recent|first)\s+(\d{1,2})\b", text.lower())
    return max(1, min(int(m.group(1)), cap)) if m else default


def rules_plan(message: str, last_plan: dict | None, ref: date) -> dict:
    t = message.lower().strip()
    month, category, merchant = resolve_month(t, ref), resolve_category(t), resolve_merchant(t)

    if any(w in t for w in SENSITIVE_WORDS):
        return {"tool": None, "reply": "I can't share card digits or private notes. They are never sent to the AI. "
                                       "I can still total your spending or list transactions."}
    if (any(w in t for w in OTHER_USER_WORDS) or OTHER_PRONOUN_RE.search(t) or OTHER_PERSON_RE.search(t)
            or any(re.search(rf"\b{u}\b", t) for u in DEMO_USERS)):
        return {"tool": None, "reply": "I can only work with your own data."}

    args: dict = {}
    if month:
        args["month"] = month

    if (any(w in t for w in TOP_WORDS) and "merchant" in t) or re.search(r"where (do|did) i spend (the )?most", t):
        args["limit"] = _number(t, 5, 20)
        return {"tool": "top_merchants", "args": args}

    if any(w in t for w in SUMMARY_WORDS):
        if category:
            args["category"] = category
        return {"tool": "summarize_by_category", "args": args}

    if merchant or any(w in t for w in LIST_WORDS):
        if merchant:
            args["merchant"] = merchant
        if category:
            args["category"] = category
        args["limit"] = _number(t, 10, 50)
        return {"tool": "search_expenses", "args": args}

    if any(w in t for w in SPEND_WORDS):
        if category:
            args["category"] = category
        return {"tool": "summarize_by_category", "args": args}

    # Follow-up such as "and last month?" or "what about food?": reuse the previous plan.
    if last_plan and last_plan.get("tool") and (month or category):
        merged = dict(last_plan.get("args", {}))
        if month:
            merged["month"] = month
        if category and "category" in TOOLS[last_plan["tool"]]["params"]:
            merged["category"] = category
        return {"tool": last_plan["tool"], "args": merged}

    return {"tool": None, "reply": HELP_REPLY}


def plan(message: str, history: list[dict], last_plan: dict | None, ref: date) -> tuple[dict, str]:
    """Returns (plan, source). Tries the LLM first when configured, falls back to rules."""
    from . import llm

    if llm.enabled():
        result = llm.plan(message, history, ref)
        if result is not None:
            return result, "llm"
    return rules_plan(message, last_plan, ref), "rules"


# ---------- answer templates (used when no LLM is configured) ----------

def month_label(month: str | None) -> str:
    if not month:
        return ""
    y, m = month.split("-")
    names = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]
    return f"{names[int(m) - 1]} {y}"


def money(x: float) -> str:
    return f"₹{x:,.2f}"


def template_answer(tool: str, args: dict, rows: list[dict]) -> str:
    when = f" in {month_label(args.get('month'))}" if args.get("month") else ""
    if not rows:
        return f"I couldn't find any matching expenses{when}."
    if tool == "summarize_by_category":
        total = sum(r["amount"] for r in rows)
        if len(rows) == 1:
            return f"You spent {money(total)} on {rows[0]['category']}{when}."
        lines = [f"- {r['category']}: {money(r['amount'])}" for r in rows]
        return f"Your spending{when} was {money(total)} in total:\n" + "\n".join(lines)
    if tool == "top_merchants":
        lines = [f"{i}. {r['merchant']}: {money(r['amount'])}" for i, r in enumerate(rows, 1)]
        return f"Your top merchants{when}:\n" + "\n".join(lines)
    total = sum(r["amount"] for r in rows)
    lines = [f"- {r['date']} · {r['merchant']} · {r['category']} · {money(r['amount'])}" for r in rows]
    return f"{len(rows)} matching expenses{when} (total {money(total)}):\n" + "\n".join(lines)
