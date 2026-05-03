"""SQLite persistence for FinPilot DS authentication."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "finpilot_users.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users (email)")
    import portfolio_store

    portfolio_store.init_portfolio_tables()


def get_user_by_email(email_normalized: str) -> dict[str, Any] | None:
    """email_normalized must already be lowercased."""
    if not email_normalized:
        return None
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT email, password_hash, first_name, last_name
            FROM users
            WHERE lower(email) = lower(?)
            LIMIT 1
            """,
            (email_normalized,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "email": row["email"],
            "password_hash": row["password_hash"],
            "first_name": row["first_name"],
            "last_name": row["last_name"],
        }


def create_user(
    email_normalized: str,
    password_hash: str,
    first_name: str,
    last_name: str,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (email, password_hash, first_name, last_name)
            VALUES (?, ?, ?, ?)
            """,
            (email_normalized, password_hash, first_name[:80], last_name[:80]),
        )
