"""Portfolio-scoped data layer (coursework): holdings, transactions, EOD snapshots — user-isolated by email.

Aligns with the portfolio chatbot architecture doc: no external market feeds; rows back RAG chunks + audit trail.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from auth_db import get_connection


def init_portfolio_tables() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio_holdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                symbol TEXT NOT NULL,
                quantity REAL NOT NULL,
                avg_cost REAL NOT NULL,
                sleeve TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(user_email, symbol)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_holdings_user ON portfolio_holdings (user_email)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_txn_user ON portfolio_transactions (user_email)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio_eod_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                nav_total_display TEXT,
                nav_total_raw REAL,
                pnl_day_estimate REAL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(user_email, snapshot_date)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_eod_user ON portfolio_eod_snapshots (user_email)"
        )


def sync_holdings_and_snapshot_from_plan(
    user_email: str, plan: dict[str, Any], pnl_day_estimate: float | None = None
) -> None:
    """Derive synthetic lots + one EOD snapshot from the optimizer plan (deterministic coursework positions)."""
    if not user_email:
        return
    email = user_email.strip().lower()
    summary = plan.get("summary") or {}
    budget = float(summary.get("budget") or 0)
    total_disp = str(summary.get("total_amount_display", summary.get("total_amount", "")))
    pnl_day = pnl_day_estimate

    with get_connection() as conn:
        conn.execute("DELETE FROM portfolio_holdings WHERE lower(user_email) = lower(?)", (email,))
        for row in plan.get("allocation") or []:
            sector = str(row.get("sector") or "")
            pct = float(row.get("percent") or 0) / 100.0
            sleeve_amt = budget * pct
            exemplars = row.get("exemplars") or []
            if not exemplars:
                continue
            per = sleeve_amt / len(exemplars)
            for ex in exemplars:
                sym = str(ex.get("symbol", "")).strip().upper()
                price = float(ex.get("price") or 0)
                if not sym or price <= 0:
                    continue
                qty = round(per / price, 6)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO portfolio_holdings
                    (user_email, symbol, quantity, avg_cost, sleeve, updated_at)
                    VALUES (lower(?), ?, ?, ?, ?, datetime('now'))
                    """,
                    (email, sym, qty, price, sector),
                )

        today = date.today().isoformat()
        conn.execute(
            """
            INSERT OR REPLACE INTO portfolio_eod_snapshots
            (user_email, snapshot_date, nav_total_display, nav_total_raw, pnl_day_estimate, created_at)
            VALUES (lower(?), ?, ?, ?, ?, datetime('now'))
            """,
            (
                email,
                today,
                total_disp,
                float(summary.get("total_amount") or 0),
                pnl_day,
            ),
        )


def fetch_holdings_chunks(user_email: str) -> list[tuple[str, str]]:
    """Rows merged into RAG as structured holdings evidence."""
    if not user_email:
        return []
    email = user_email.strip().lower()
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT symbol, quantity, avg_cost, sleeve
            FROM portfolio_holdings
            WHERE lower(user_email) = lower(?)
            ORDER BY symbol
            """,
            (email,),
        )
        rows = cur.fetchall()
    out: list[tuple[str, str]] = []
    for r in rows:
        sym = str(r["symbol"])
        short = sym.replace(".NS", "")
        out.append(
            (
                f"holding:{short}",
                f"Holdings record (DB): {sym} — qty {float(r['quantity']):.4f}, avg cost ₹{float(r['avg_cost']):.2f}, sleeve {r['sleeve'] or 'n/a'}.",
            )
        )
    return out


def clear_user_holdings_and_snapshots(user_email: str) -> None:
    """Remove DB copies of positions and recent EOD row for this user (e.g. after clear import)."""
    if not user_email:
        return
    email = user_email.strip().lower()
    with get_connection() as conn:
        conn.execute("DELETE FROM portfolio_holdings WHERE lower(user_email) = lower(?)", (email,))
        conn.execute("DELETE FROM portfolio_eod_snapshots WHERE lower(user_email) = lower(?)", (email,))


def sync_holdings_from_broker_json(user_email: str, data: dict[str, Any]) -> int:
    """Replace portfolio_holdings (and one EOD snapshot) from an imported portfolio JSON — app-wide DB."""
    if not user_email:
        return 0
    email = user_email.strip().lower()
    rows_in = data.get("holdings") or []
    n = 0
    with get_connection() as conn:
        conn.execute("DELETE FROM portfolio_holdings WHERE lower(user_email) = lower(?)", (email,))
        for h in rows_in:
            sym = str(h.get("tradingsymbol") or "").strip().upper()
            if not sym:
                continue
            if "." not in sym:
                sym = f"{sym}.NS"
            qty = float(h.get("total_quantity") or h.get("quantity") or 0)
            avg = float(h.get("average_price") or 0)
            sleeve = str(h.get("sector") or "")
            if qty <= 0 or avg < 0:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO portfolio_holdings
                (user_email, symbol, quantity, avg_cost, sleeve, updated_at)
                VALUES (lower(?), ?, ?, ?, ?, datetime('now'))
                """,
                (email, sym, qty, avg, sleeve),
            )
            n += 1
        m = data.get("metrics") or {}
        today = date.today().isoformat()
        nav = float(m.get("current_value") or 0)
        nav_disp = f"{nav:,.2f}" if nav else str(m.get("current_value", ""))
        pnl_day = float(m.get("day_change") or 0)
        conn.execute(
            """
            INSERT OR REPLACE INTO portfolio_eod_snapshots
            (user_email, snapshot_date, nav_total_display, nav_total_raw, pnl_day_estimate, created_at)
            VALUES (lower(?), ?, ?, ?, ?, datetime('now'))
            """,
            (email, today, nav_disp, nav, pnl_day),
        )
    return n


def fetch_transaction_chunks(user_email: str, limit: int = 12) -> list[tuple[str, str]]:
    if not user_email:
        return []
    email = user_email.strip().lower()
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT symbol, side, quantity, price, note, created_at
            FROM portfolio_transactions
            WHERE lower(user_email) = lower(?)
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (email, limit),
        )
        rows = cur.fetchall()
    out: list[tuple[str, str]] = []
    for r in rows:
        out.append(
            (
                "txn",
                f"Transaction (DB): {r['side']} {r['symbol']} qty {float(r['quantity']):.4f} @ ₹{float(r['price']):.2f} — {r['created_at']}.",
            )
        )
    return out


def fetch_eod_chunks(user_email: str, limit: int = 5) -> list[tuple[str, str]]:
    if not user_email:
        return []
    email = user_email.strip().lower()
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT snapshot_date, nav_total_display, pnl_day_estimate
            FROM portfolio_eod_snapshots
            WHERE lower(user_email) = lower(?)
            ORDER BY snapshot_date DESC
            LIMIT ?
            """,
            (email, limit),
        )
        rows = cur.fetchall()
    out: list[tuple[str, str]] = []
    for r in rows:
        pnl = r["pnl_day_estimate"]
        pnl_s = f", modeled day delta ≈ ₹{float(pnl):+,}" if pnl is not None else ""
        out.append(
            (
                f"eod:{r['snapshot_date']}",
                f"EOD snapshot (DB): date {r['snapshot_date']}, NAV {r['nav_total_display']}{pnl_s}.",
            )
        )
    return out
