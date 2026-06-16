import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id    INTEGER PRIMARY KEY,
                username   TEXT,
                first_name TEXT,
                last_name  TEXT,
                phone      TEXT,
                first_seen TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


def upsert_user(user_id: int, username=None, first_name=None,
                last_name=None, phone=None) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, username, first_name, last_name, phone)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username   = COALESCE(excluded.username,   username),
                first_name = COALESCE(excluded.first_name, first_name),
                last_name  = COALESCE(excluded.last_name,  last_name),
                phone      = COALESCE(excluded.phone,      phone),
                last_seen  = datetime('now')
            """,
            (user_id, username, first_name, last_name, phone),
        )
        conn.commit()


def get_users_page(page: int, per_page: int = 10) -> tuple[list[dict], int]:
    offset = (page - 1) * per_page
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM users ORDER BY first_seen DESC LIMIT ? OFFSET ?",
            (per_page, offset),
        ).fetchall()
    return [dict(r) for r in rows], total
