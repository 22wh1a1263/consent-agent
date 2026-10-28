"""SQLite storage. Every query in the app is scoped by user_id (the same idea as
Postgres Row-Level Security: a user can only ever read their own rows)."""
import os
import random
import sqlite3
from datetime import date, timedelta

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data.db")

CATEGORIES = ["Food", "Groceries", "Transport", "Shopping", "Entertainment", "Bills", "Health", "Travel"]

MERCHANTS = {
    "Food": ["Swiggy", "Zomato", "Third Wave Coffee", "Paradise Biryani"],
    "Groceries": ["BigBasket", "Blinkit", "DMart"],
    "Transport": ["Uber", "Ola", "Metro Card"],
    "Shopping": ["Amazon", "Myntra", "Flipkart"],
    "Entertainment": ["Netflix", "Spotify", "BookMyShow"],
    "Bills": ["Airtel", "Electricity Board", "Jio Fiber"],
    "Health": ["Apollo Pharmacy", "Cult.fit"],
    "Travel": ["IRCTC", "MakeMyTrip"],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS expenses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  date TEXT NOT NULL,
  merchant TEXT NOT NULL,
  category TEXT NOT NULL,
  amount REAL NOT NULL,
  note TEXT,
  card_last4 TEXT
);
CREATE INDEX IF NOT EXISTS idx_expenses_user_date ON expenses(user_id, date);
CREATE TABLE IF NOT EXISTS grants (
  user_id INTEGER NOT NULL REFERENCES users(id),
  tool TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, tool)
);
CREATE TABLE IF NOT EXISTS pending (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  question TEXT NOT NULL,
  tool TEXT NOT NULL,
  args_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  plan_ms REAL NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'rules',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS receipts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  tool TEXT NOT NULL,
  args_json TEXT NOT NULL,
  decision TEXT NOT NULL,          -- approved_once | approved_standing | denied
  fields_shared_json TEXT NOT NULL,
  fields_withheld_json TEXT NOT NULL,
  row_count INTEGER NOT NULL,
  ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS session_state (
  user_id INTEGER PRIMARY KEY REFERENCES users(id),
  last_plan_json TEXT
);
CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  tool TEXT,
  plan_ms REAL NOT NULL DEFAULT 0,
  tool_ms REAL NOT NULL DEFAULT 0,
  llm_ms REAL NOT NULL DEFAULT 0,
  total_ms REAL NOT NULL DEFAULT 0,
  ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def db_path() -> str:
    return os.environ.get("DB_PATH", DEFAULT_DB)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed(conn)
    conn.close()


def seed(conn: sqlite3.Connection) -> None:
    """Two demo users with deterministic fake expenses (Aug - Oct 2026)."""
    rng = random.Random(42)
    for username in ("alice", "bob"):
        cur = conn.execute("INSERT INTO users (username) VALUES (?)", (username,))
        uid = cur.lastrowid
        card = "4242" if username == "alice" else "1881"
        day = date(2026, 8, 1)
        end = date(2026, 10, 27)
        while day <= end:
            for _ in range(rng.choice([0, 1, 1, 2])):
                cat = rng.choices(CATEGORIES, weights=[5, 3, 4, 3, 2, 1, 1, 1])[0]
                merchant = rng.choice(MERCHANTS[cat])
                amount = round(rng.uniform(40, 1800), 2)
                note = f"{merchant} order, private note {rng.randint(100, 999)}"
                conn.execute(
                    "INSERT INTO expenses (user_id, date, merchant, category, amount, note, card_last4) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (uid, day.isoformat(), merchant, cat, amount, note, card),
                )
            day += timedelta(days=1)
    conn.commit()
