# Consent-Gated Personal Agent

An AI assistant that answers questions about your own data (a demo expense tracker) but **cannot read anything until you approve that specific request**. Built as a full-stack project around agents, tool use, data privacy and measurable quality.

```
Next.js + TypeScript  ->  FastAPI  ->  SQLite (per-user scoped rows)
 chat / consent UI        planner -> consent gate -> tools -> receipts + metrics
```

## How it works

1. **Plan, don't touch data.** `/chat` turns a question into a tool call (`search_expenses`, `summarize_by_category`, `top_merchants`). The planner never sees any rows.
2. **Consent gate.** Unless you granted a standing approval, the API returns `consent_required` with the tool, filters, the fields it wants, and the fields that stay hidden. No data has been read yet.
3. **Least privilege.** After you approve, each tool returns only its declared fields. `note` and `card_last4` are never returned by any tool, so they can never reach the LLM.
4. **Receipts.** Every approval, standing approval and denial is logged: tool, filters, fields shared, fields withheld, row count.
5. **Isolation.** Every SQL query is scoped by the caller's `user_id`, and a pending request can only be approved by the user who made it.
6. **Memory.** Recent chat turns (last 6) and the last plan are kept, so "and last month?" works. Standing approvals persist until revoked.
7. **Latency instrumentation.** Each answer records plan / tool / LLM time. `/stats` shows average, p95 and % within a latency budget (default 1500 ms).
8. **Evals.** `backend/evals` scores tool choice, argument accuracy and consent safety.

## Run it

Backend (Python 3.10+):
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend (Node 18+):
```bash
cd frontend
npm install
npm run dev          # http://localhost:3000
```

Sign in as `alice` or `bob` (demo accounts, no password). The first start seeds fake expenses into `backend/data.db`.

### Optional: use a real LLM
By default the app runs fully offline with a rule-based planner. To use an LLM for planning and answer writing (any OpenAI-compatible API, Groq by default):
```bash
export LLM_API_KEY=...            # enables the LLM path
export LLM_MODEL=llama-3.3-70b-versatile
export LLM_BASE_URL=https://api.groq.com/openai/v1
```
The LLM only chooses a tool and writes the final sentence from the approved, minimal rows. Its tool arguments are validated before anything runs, and the planner falls back to rules on any failure.

## Tests and evals
```bash
cd backend
python -m pytest -q                # 21 tests: isolation, consent gating, redaction, validation, SQL injection
python evals/run_evals.py          # 20-question eval: tool accuracy, arg accuracy, consent safety
```

## Environment variables
| Name | Default | Purpose |
|---|---|---|
| `JWT_SECRET` | dev value | **Change in production** |
| `DB_PATH` | `backend/data.db` | SQLite file |
| `LLM_API_KEY` | unset | Turns on the LLM path |
| `LATENCY_BUDGET_MS` | 1500 | Budget used by `/stats` |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Frontend -> API |

## Limits (by design, for a demo)
- Login is username-only; use real auth for anything beyond a demo.
- SQLite with `user_id` scoping stands in for Postgres Row-Level Security. Moving to Supabase/Postgres means adding RLS policies on `expenses`.
- The eval set is small (20 cases) and tests the offline planner by default; run it with `LLM_API_KEY` set to evaluate the LLM planner.
- Not implemented: on-device inference, vector search/RAG, a mobile client.
