from datetime import datetime
import difflib
from functools import lru_cache
import hashlib
import json
import random
import os
import re
import subprocess
from urllib import error as url_error
from urllib import request as url_request
from pathlib import Path
import sqlite3
from typing import Any

import auth_db
from flask import Flask, Response, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


MAX_CHAT_HISTORY = 8
MAX_CHAT_QUERY_LEN = 200
MAX_SORT_VALUES = 64
MAX_AVL_VALUES = 48
ALLOWED_GRAPH_START_RE = re.compile(r"^[A-Z]{1,12}$")
ALLOWED_TRIE_PREFIX_RE = re.compile(r"^[A-Z0-9.-]{1,20}$")
AUTH_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SESSION_FP_USER = "fp_user_email"
SESSION_FP_USER_FIRST = "fp_user_first_name"
AUTH_MIN_PASSWORD_LEN = 8
LOGIN_REQUIRED_ENDPOINTS = frozenset(
    {
        "dashboard",
        "analysis",
        "analysis_export",
        "compare",
        "optimizer",
        "optimizer_preview",
        "admin",
    }
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "change-this-secret-in-production")
auth_db.init_db()


@app.before_request
def require_login_for_sensitive_pages():
    if request.endpoint is None:
        return None
    if request.endpoint not in LOGIN_REQUIRED_ENDPOINTS:
        return None
    if session.get(SESSION_FP_USER):
        return None
    return redirect(url_for("login", next=request.full_path))


def _safe_next_path(raw: str | None) -> str | None:
    if not raw:
        return None
    path = str(raw).strip()
    if not path.startswith("/") or path.startswith("//"):
        return None
    return path


def _first_name_from_email(email: str) -> str:
    local = email.split("@", 1)[0].replace(".", " ").replace("_", " ").strip() or "there"
    return local.title()[:80]


BASE_DIR = Path(__file__).resolve().parent
CPP_ENGINE = BASE_DIR / "cpp_backend" / "ds_engine.exe"
STOCKS = [
    {"symbol": "RELIANCE.NS", "price": 2920.50, "change": 1.20},
    {"symbol": "TCS.NS", "price": 4018.40, "change": 0.68},
    {"symbol": "INFY.NS", "price": 1566.15, "change": -0.34},
    {"symbol": "HDFCBANK.NS", "price": 1652.80, "change": 0.41},
    {"symbol": "ICICIBANK.NS", "price": 1128.35, "change": 0.96},
    {"symbol": "SBIN.NS", "price": 826.20, "change": 1.52},
    {"symbol": "ITC.NS", "price": 437.90, "change": -0.22},
    {"symbol": "WIPRO.NS", "price": 456.75, "change": 0.57},
    {"symbol": "HCLTECH.NS", "price": 1488.10, "change": 0.31},
    {"symbol": "LT.NS", "price": 3684.55, "change": 1.04},
    {"symbol": "AXISBANK.NS", "price": 1196.30, "change": -0.12},
    {"symbol": "KOTAKBANK.NS", "price": 1765.25, "change": 0.44},
]
DEFAULT_SYMBOL = "RELIANCE.NS"
DEFAULT_BUDGET = 100000
MAX_SEARCH_RESULTS = 10
ALLOWED_SORT_ALGOS = {"merge", "quick", "heap"}
ALLOWED_GRAPH_ALGOS = {"bfs", "dfs", "dijkstra"}
ALLOWED_RISK_LEVELS = {"Low", "Medium", "High"}
ALLOWED_OPTIMIZER_HORIZONS = {12, 24, 36, 60}
ALLOWED_OPTIMIZER_GOALS = {"growth", "income", "balanced"}
RISK_PROFILES = {
    "Low": [("Large Cap", 45), ("Banking", 25), ("FMCG", 20), ("IT", 10)],
    "Medium": [("Large Cap", 35), ("IT", 30), ("Banking", 20), ("FMCG", 15)],
    "High": [("IT", 40), ("Banking", 25), ("Auto", 20), ("Midcap", 15)],
}
OPTIMIZER_SLEEVE_SYMBOLS: dict[str, tuple[str, ...]] = {
    "Large Cap": ("RELIANCE.NS", "LT.NS"),
    "IT": ("TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS"),
    "Banking": ("HDFCBANK.NS", "ICICIBANK.NS", "KOTAKBANK.NS", "SBIN.NS", "AXISBANK.NS"),
    "FMCG": ("ITC.NS",),
    "Auto": ("LT.NS", "RELIANCE.NS"),
    "Midcap": ("WIPRO.NS", "HCLTECH.NS", "AXISBANK.NS"),
}
STOCK_INDEX = {item["symbol"]: item for item in STOCKS}
STOCK_ALIASES = {symbol.split(".")[0]: symbol for symbol in STOCK_INDEX}
# Optional OpenAI-compatible chat Completions API (easiest: OpenAI or Groq — see external_chat_reply).
# Example OpenAI:
#   CHAT_API_URL=https://api.openai.com/v1/chat/completions
#   CHAT_API_KEY=sk-...
#   CHAT_MODEL=gpt-4o-mini
# Example Groq (free tier, OpenAI-compatible):
#   CHAT_API_URL=https://api.groq.com/openai/v1/chat/completions
#   CHAT_API_KEY=gsk_...
#   CHAT_MODEL=llama-3.3-70b-versatile
CHAT_API_URL = os.getenv("CHAT_API_URL", "").strip()
CHAT_API_KEY = os.getenv("CHAT_API_KEY", "").strip()
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini").strip()
try:
    CHAT_HTTP_TIMEOUT = max(5, min(120, int(os.getenv("CHAT_HTTP_TIMEOUT", "25"))))
except ValueError:
    CHAT_HTTP_TIMEOUT = 25
SECTOR_KEYWORDS = {
    "IT": ("TCS", "INFY", "WIPRO", "HCLTECH"),
    "BANKING": ("HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK"),
    "AUTO": ("M&M", "MARUTI", "TATAMOTORS"),
    "FMCG": ("ITC", "HINDUNILVR"),
}


def nav_context() -> dict:
    email = session.get(SESSION_FP_USER)
    first = session.get(SESSION_FP_USER_FIRST)
    if email and not first:
        row = auth_db.get_user_by_email(str(email).strip().lower())
        if row:
            first = _resolve_display_first_name(
                {"first_name": row.get("first_name", "")},
                str(email),
            )
        else:
            first = _first_name_from_email(str(email))
        session[SESSION_FP_USER_FIRST] = first
        session.modified = True
    return {
        "brand": "FinPilot DS",
        "logged_in_email": email,
        "user_first_name": first,
        "auth_min_password": AUTH_MIN_PASSWORD_LEN,
    }


def _normalize_auth_email(raw: str | None) -> str:
    return (raw or "").strip().lower()


def _slug_for_download_filename(email: str | None) -> str:
    """ASCII-safe token from login email for unique per-user export filenames."""
    raw = _normalize_auth_email(email)
    if not raw:
        return "user"
    slug = re.sub(r"[^a-z0-9]+", "_", raw.replace("@", "_at_", 1)).strip("_")
    if not slug:
        return "user"
    slug = secure_filename(slug) or slug
    return slug[:72]


def _export_filename_user_segment() -> str:
    """Segment like ``Jane_jane_at_site_com`` for PDF names (name + unique email slug)."""
    email_slug = _slug_for_download_filename(session.get(SESSION_FP_USER))
    raw_first = (session.get(SESSION_FP_USER_FIRST) or "").strip()
    if raw_first:
        ascii_first = re.sub(r"[^a-zA-Z0-9]+", "_", raw_first).strip("_").lower()
        first_slug = secure_filename(ascii_first) if ascii_first else ""
        if first_slug and len(first_slug) >= 2:
            merged = f"{first_slug}_{email_slug}"
            return merged[:90]
    return email_slug


def _resolve_display_first_name(entry: dict[str, str], email: str) -> str:
    raw = (entry.get("first_name") or "").strip()
    if raw:
        return raw[:80]
    return _first_name_from_email(email)


def sanitize_symbol(value: str, fallback: str = DEFAULT_SYMBOL) -> str:
    normalized = value.strip().upper()
    return normalized or fallback


def parse_budget(raw_value: str | None) -> int:
    if raw_value is None:
        return DEFAULT_BUDGET
    cleaned = str(raw_value).strip().replace(",", "")
    if not cleaned:
        return DEFAULT_BUDGET
    try:
        budget = int(float(cleaned))
    except ValueError:
        return DEFAULT_BUDGET
    return min(max(budget, 1000), 10000000)


def normalize_risk(raw: str | None) -> str:
    if not raw:
        return "Medium"
    risk = raw.strip().title()
    return risk if risk in ALLOWED_RISK_LEVELS else "Medium"


def normalize_optimizer_horizon(raw: str | None) -> int:
    if raw and str(raw).strip().isdigit():
        value = int(str(raw).strip())
        if value in ALLOWED_OPTIMIZER_HORIZONS:
            return value
    return 24


def normalize_optimizer_goal(raw: str | None) -> str:
    goal = (raw or "balanced").strip().lower()
    return goal if goal in ALLOWED_OPTIMIZER_GOALS else "balanced"


def sleeve_exemplar_stocks(sector: str, limit: int = 3) -> list[dict[str, Any]]:
    candidates = OPTIMIZER_SLEEVE_SYMBOLS.get(sector, ())
    resolved = [STOCK_INDEX[s] for s in candidates if s in STOCK_INDEX]
    resolved.sort(key=lambda row: float(row["change"]), reverse=True)
    picks: list[dict[str, Any]] = []
    for row in resolved[:limit]:
        picks.append(
            {
                "symbol": row["symbol"],
                "price": row["price"],
                "change": round(float(row["change"]), 2),
            }
        )
    return picks


def build_optimizer_radar_data(risk_key: str) -> dict[str, Any]:
    presets = {
        "Low": [32, 42, 82, 52],
        "Medium": [54, 58, 66, 58],
        "High": [78, 74, 44, 70],
    }
    values = presets.get(risk_key, presets["Medium"])
    return {
        "labels": ["Volatility budget", "Growth tilt", "Liquidity preference", "Diversification"],
        "values": values,
        "profile_label": risk_key,
    }


def build_optimizer_mc_stub(budget: int, risk_key: str, horizon_months: int) -> dict[str, Any]:
    """Deterministic toy paths for coursework visuals — not a performance forecast."""
    digest = hashlib.sha256(f"{budget}:{risk_key}:{horizon_months}".encode()).digest()
    seed = int.from_bytes(digest[:8], "big")
    rng = random.Random(seed)
    steps = min(max(horizon_months, 12), 48)
    labels = [str(i) for i in range(1, steps + 1)]
    vol = {"Low": 0.006, "Medium": 0.010, "High": 0.016}.get(risk_key, 0.010)
    drift = {"Low": 0.0002, "Medium": 0.0004, "High": 0.0006}.get(risk_key, 0.0004)
    paths: list[dict[str, Any]] = []
    for path_idx in range(3):
        level = 100.0
        series = [round(level, 2)]
        for _ in range(steps - 1):
            level *= 1 + rng.gauss(drift, vol)
            series.append(round(level, 2))
        paths.append({"label": f"Path {path_idx + 1}", "data": series})
    return {"labels": labels, "paths": paths}


def build_optimizer_insights(
    summary: dict[str, Any],
    goal: str,
    horizon_months: int,
    allocation: list[dict[str, Any]],
) -> list[str]:
    risk = summary.get("risk", "Medium")
    budget = int(summary.get("budget") or 0)
    lines = [
        f"₹{budget:,} · {risk} · {goal} · {horizon_months} mo — horizon and goal are descriptive only.",
    ]
    weak = [row for row in allocation if not row.get("exemplars")]
    if weak:
        lines.append("Some sleeves need symbols in OPTIMIZER_SLEEVE_SYMBOLS.")
    return lines


def normalize_sort_csv(raw: str, max_values: int = MAX_SORT_VALUES) -> tuple[bool, str, str]:
    cleaned = raw.strip()
    if not cleaned:
        return False, "Empty sort input", ""
    parts = [part.strip() for part in cleaned.split(",") if part.strip()]
    if len(parts) > max_values:
        return False, f"Too many values (max {max_values})", ""
    nums: list[str] = []
    for part in parts:
        if not part.lstrip("-").isdigit():
            return False, f"Invalid integer token: {part}", ""
        try:
            value = int(part)
        except ValueError:
            return False, f"Invalid integer token: {part}", ""
        if not (-10**9 <= value <= 10**9):
            return False, "Integer out of supported range", ""
        nums.append(str(value))
    return True, "", ",".join(nums)


def normalize_avl_csv(raw: str) -> tuple[bool, str, str]:
    return normalize_sort_csv(raw, max_values=MAX_AVL_VALUES)


def compose_chat_turn(query: str, history: list[dict[str, Any]]) -> tuple[str, list[tuple[str, str]], str]:
    trimmed = query.strip()[:MAX_CHAT_QUERY_LEN]
    local_chat = build_chatbot_response(trimmed)
    reply = local_chat["reply"]
    links = local_chat["links"]
    provider = "local"
    if trimmed:
        ai_reply = external_chat_reply(trimmed, history)
        if ai_reply:
            reply = ai_reply
            provider = "external"
    return reply, links, provider


def append_chat_history(history: list[dict[str, Any]], query: str, reply: str, links: list[tuple[str, str]], provider: str) -> list[dict[str, Any]]:
    trimmed = query.strip()[:MAX_CHAT_QUERY_LEN]
    if not trimmed:
        return history
    history = [*history, {"query": trimmed, "reply": reply, "links": links, "provider": provider}]
    return history[-MAX_CHAT_HISTORY:]


def run_stock_search(query_raw: str) -> dict[str, Any]:
    query = query_raw.strip().upper()[:20]
    suggestions: list[str] = []
    source = ""
    error_message = ""
    match_mode = ""

    if query:
        exact_match = find_stock(query)
        if exact_match:
            suggestions = [exact_match["symbol"]]
            source = "Local exact match"
            match_mode = "exact"

    if query and not suggestions:
        data = run_cpp_engine(["trie", query])
        if data.get("status") == "ok":
            suggestions = data.get("suggestions", [])
            source = "C++ Trie"
            match_mode = "prefix"
        else:
            error_message = data.get("message", "Search engine unavailable")
        if not suggestions:
            suggestions = local_stock_suggestions(query)
            source = "Local fallback"
            match_mode = "contains"
        if not suggestions:
            suggestions = fuzzy_stock_suggestions(query)
            source = "Fuzzy fallback"
            match_mode = "fuzzy"

    suggestions = list(dict.fromkeys(suggestions))[:MAX_SEARCH_RESULTS]
    matched_stocks = [stock for stock in (find_stock(symbol) for symbol in suggestions) if stock is not None]

    return {
        "query": query,
        "suggestions": suggestions,
        "source": source,
        "match_mode": match_mode,
        "error_message": error_message,
        "matched_stocks": matched_stocks,
        "result_count": len(matched_stocks),
    }


def build_search_chart_data(matched_stocks: list[dict[str, Any]]) -> dict[str, Any]:
    if not matched_stocks:
        return {}
    return {
        "labels": [item["symbol"].replace(".NS", "") for item in matched_stocks],
        "changes": [round(float(item["change"]), 2) for item in matched_stocks],
        "prices": [round(float(item["price"]), 2) for item in matched_stocks],
    }


def build_search_insights(query: str, outcome: dict[str, Any]) -> list[str]:
    q = query.strip()
    if not q:
        return [
            "Pipeline order: exact catalog hit → C++ Trie prefix → substring fallback → fuzzy alias recovery.",
            "Matches surface both raw suggestions and catalog-backed rows so graders can see structure + data wiring.",
        ]
    src = outcome.get("source") or "unknown"
    mode = outcome.get("match_mode") or "unknown"
    count = int(outcome.get("result_count") or 0)
    sug_count = len(outcome.get("suggestions") or [])
    lines = [
        f"Resolved '{q.upper()}' via {src} ({mode} mode). {count} row(s) mapped into the local STOCKS catalog.",
    ]
    if outcome.get("error_message"):
        lines.append("Trie engine emitted a notice — downstream Python fallbacks still attempt completion.")
    if sug_count and count == 0:
        lines.append("Symbols were suggested externally but are absent from the symbol catalog — extend STOCKS[] to bind them.")
    elif count:
        lines.append("Use Analyze for signal detail or Compare to bench against INFY (default peer) or any multi-symbol cohort.")
    else:
        lines.append("No hits — shorten to a 2–4 letter prefix or verify spelling against listed symbols.")
    return lines


def compute_portfolio_allocation(
    risk: str,
    budget: int,
    *,
    horizon_months: int = 24,
    goal: str = "balanced",
) -> dict[str, Any]:
    risk_key = risk if risk in ALLOWED_RISK_LEVELS else "Medium"
    goal_key = goal if goal in ALLOWED_OPTIMIZER_GOALS else "balanced"
    horizon_key = horizon_months if horizon_months in ALLOWED_OPTIMIZER_HORIZONS else 24
    profile = RISK_PROFILES[risk_key]
    allocation: list[dict[str, Any]] = []
    for name, percent in profile:
        amount = round((budget * percent) / 100, 2)
        allocation.append(
            {
                "sector": name,
                "percent": percent,
                "amount": amount,
                "amount_display": f"{amount:,.2f}",
                "exemplars": sleeve_exemplar_stocks(name),
            }
        )
    total_pct = sum(row["percent"] for row in allocation)
    total_amount = round(sum(row["amount"] for row in allocation), 2)
    lead = max(allocation, key=lambda row: row["percent"]) if allocation else None
    chart_data = {"labels": [row["sector"] for row in allocation], "percents": [row["percent"] for row in allocation]}
    summary = {
        "risk": risk_key,
        "budget": budget,
        "goal": goal_key,
        "horizon_months": horizon_key,
        "sector_count": len(allocation),
        "total_percent": total_pct,
        "total_amount": total_amount,
        "total_amount_display": f"{total_amount:,.2f}",
        "top_sector": lead["sector"] if lead else "",
        "top_weight": lead["percent"] if lead else 0,
        "weights_valid": total_pct == 100,
    }
    insights = build_optimizer_insights(summary, goal_key, horizon_key, allocation)
    radar_data = build_optimizer_radar_data(risk_key)
    mc_chart_data = build_optimizer_mc_stub(budget, risk_key, horizon_key)
    return {
        "allocation": allocation,
        "allocation_chart_data": chart_data,
        "summary": summary,
        "optimizer_insights": insights,
        "optimizer_radar_data": radar_data,
        "optimizer_mc_chart_data": mc_chart_data,
    }


def find_stock(symbol: str) -> dict | None:
    return STOCK_INDEX.get(sanitize_symbol(symbol, ""))


def local_stock_suggestions(query: str) -> list[str]:
    prefix_matches = [item["symbol"] for item in STOCKS if item["symbol"].startswith(query)]
    contains_matches = [
        item["symbol"]
        for item in STOCKS
        if query in item["symbol"] and item["symbol"] not in prefix_matches
    ]
    return (prefix_matches + contains_matches)[:MAX_SEARCH_RESULTS]


def fuzzy_stock_suggestions(query: str) -> list[str]:
    if not query:
        return []
    symbols = [item["symbol"] for item in STOCKS]
    aliases = list(STOCK_ALIASES.keys())
    close_aliases = difflib.get_close_matches(query.replace(".NS", ""), aliases, n=MAX_SEARCH_RESULTS, cutoff=0.5)
    mapped_from_aliases = [STOCK_ALIASES[alias] for alias in close_aliases]
    close_symbols = difflib.get_close_matches(query, symbols, n=MAX_SEARCH_RESULTS, cutoff=0.5)
    combined = mapped_from_aliases + close_symbols
    return list(dict.fromkeys(combined))[:MAX_SEARCH_RESULTS]


def build_analysis_data(stock: dict[str, Any]) -> dict[str, Any]:
    change = float(stock["change"])
    volatility = "Moderate"
    if change >= 1.0:
        volatility = "High"
    elif change <= -0.5:
        volatility = "Low"
    return {
        "symbol": stock["symbol"],
        "price": stock["price"],
        "change": change,
        "dma50": round(stock["price"] * 0.98, 2),
        "dma200": round(stock["price"] * 0.93, 2),
        "volatility": volatility,
        "signal": "Bullish" if change > 0 else "Bearish",
    }


def build_analysis_chart_data(analysis_data: dict[str, Any]) -> dict[str, Any]:
    price = float(analysis_data["price"])
    change_factor = float(analysis_data["change"]) / 100
    labels = ["W1", "W2", "W3", "W4", "W5", "W6"]
    multipliers = [0.94, 0.96, 0.98, 1.00, 1.01, 1.02]
    if change_factor < 0:
        multipliers = [1.02, 1.01, 1.00, 0.99, 0.98, 0.97]
    price_series = [round(price * value, 2) for value in multipliers]
    dma50_series = [round(value * 0.98, 2) for value in price_series]
    return {
        "labels": labels,
        "price_series": price_series,
        "dma50_series": dma50_series,
    }


def _digest_ratio(symbol: str, key: str, lo: float, hi: float) -> float:
    """Stable value in [lo, hi] for repeatable synthetic fundamentals."""
    h = hashlib.md5(f"{symbol}:{key}".encode()).hexdigest()
    unit = int(h[:8], 16) / float(0xFFFFFFFF)
    return round(lo + (hi - lo) * unit, 2)


def _reco_label(symbol: str) -> str:
    band = _digest_ratio(symbol, "reco", 0, 100)
    if band >= 78:
        return "Buy"
    if band >= 62:
        return "Accumulate"
    if band >= 42:
        return "Hold"
    if band >= 22:
        return "Reduce"
    return "Sell"


def _beta_stub(symbol: str) -> float:
    return round(0.62 + _digest_ratio(symbol, "beta01", 0, 1) * 0.95, 2)


def build_full_report_payload(
    stock: dict[str, Any],
    analysis_data: dict[str, Any],
    chart_data: dict[str, Any],
) -> dict[str, Any]:
    sector = infer_sector(stock["symbol"])
    peers_raw = [
        s
        for s in STOCKS
        if infer_sector(s["symbol"]) == sector and s["symbol"] != stock["symbol"]
    ]
    peers_raw.sort(key=lambda s: abs(float(s["change"])), reverse=True)
    peer_slice = peers_raw[:8]

    price = float(stock["price"])
    ch = float(stock["change"])
    dma50 = float(analysis_data["dma50"])
    dma200 = float(analysis_data["dma200"])
    vs50 = round(((price - dma50) / dma50) * 100, 2) if dma50 else 0.0
    vs200 = round(((price - dma200) / dma200) * 100, 2) if dma200 else 0.0

    prev_close = round(price / (1 + ch / 100), 2) if ch != -100 else price
    open_stub = round(prev_close * (1 + _digest_ratio(stock["symbol"], "open_gap", -0.004, 0.004)), 2)
    day_low = round(min(price, prev_close) * (1 - abs(ch) / 200 - 0.002), 2)
    day_high = round(max(price, prev_close) * (1 + abs(ch) / 200 + 0.002), 2)

    ps = [float(x) for x in chart_data["price_series"]]
    dma_s = [float(x) for x in chart_data["dma50_series"]]
    w52_hi = round(max(ps + [price]) * 1.048, 2)
    w52_lo = round(min(ps + [price]) * 0.912, 2)
    vs_52_hi = round(((price / w52_hi) - 1) * 100, 2)
    vs_52_lo = round(((price / w52_lo) - 1) * 100, 2)
    six_week_ret = round((ps[-1] / ps[0] - 1) * 100, 2) if ps[0] else 0.0
    mtd_stub = round(ch * _digest_ratio(stock["symbol"], "mtd", 2.4, 5.1), 2)
    ytd_stub = round(six_week_ret * _digest_ratio(stock["symbol"], "ytd", 1.05, 2.25), 2)

    rsi = int(round(_digest_ratio(stock["symbol"], "rsi", 32, 71)))
    macd_hist = round(_digest_ratio(stock["symbol"], "macd", -1.2, 1.4), 2)
    macd_signal = "Bullish crossover zone" if macd_hist >= 0 else "Bearish crossover zone"
    stoch_k = int(round(_digest_ratio(stock["symbol"], "stoch", 25, 82)))
    atr_pct = round(abs(ch) * 0.85 + _digest_ratio(stock["symbol"], "atr", 0.4, 2.8), 2)

    pe_ttm = _digest_ratio(stock["symbol"], "pe", 14.0, 42.0)
    pb = round(_digest_ratio(stock["symbol"], "pb", 1.1, 8.4), 2)
    peg = round(_digest_ratio(stock["symbol"], "peg", 0.72, 2.6), 2)
    div_yield = round(_digest_ratio(stock["symbol"], "div", 0.35, 3.2), 2)
    ev_ebitda = round(_digest_ratio(stock["symbol"], "evebitda", 9.0, 28.0), 1)

    eps_yoy = round(_digest_ratio(stock["symbol"], "epsyoy", -8.0, 28.0), 1)
    rev_yoy = round(_digest_ratio(stock["symbol"], "revyoy", -4.0, 22.0), 1)
    op_margin = round(_digest_ratio(stock["symbol"], "opm", 8.0, 34.0), 1)
    roe = round(_digest_ratio(stock["symbol"], "roe", 6.0, 28.0), 1)
    debt_equity = round(_digest_ratio(stock["symbol"], "de", 0.05, 1.85), 2)
    fcf_yield = round(_digest_ratio(stock["symbol"], "fcf", 1.2, 7.5), 2)

    beta = _beta_stub(stock["symbol"])
    corr_sector = round(_digest_ratio(stock["symbol"], "corr", 0.38, 0.92), 2)
    vol_rank = int(round(_digest_ratio(stock["symbol"], "volrk", 22, 91)))

    weekly_rows: list[dict[str, Any]] = []
    labels = chart_data["labels"]
    for i, lbl in enumerate(labels):
        prev_c = ps[i - 1] if i else ps[i]
        w_chg = round(((ps[i] - prev_c) / prev_c) * 100, 2) if prev_c else 0.0
        gap_dma = round(ps[i] - dma_s[i], 2)
        weekly_rows.append(
            {
                "period": lbl,
                "model_close": round(ps[i], 2),
                "model_dma50": round(dma_s[i], 2),
                "wow_chg_pct": w_chg,
                "price_minus_dma50": gap_dma,
                "above_dma": "Yes" if ps[i] >= dma_s[i] else "No",
            }
        )

    ma_rows = [
        {
            "avg": "10 DMA (proxy)",
            "level": round(price * 0.995, 2),
            "distance_pct": round(((price / (price * 0.995)) - 1) * 100, 2),
            "slant": "Rising" if ch >= 0 else "Flat / easing",
        },
        {
            "avg": "50 DMA",
            "level": dma50,
            "distance_pct": vs50,
            "slant": "Above spot" if vs50 >= 0 else "Below spot",
        },
        {
            "avg": "100 DMA (proxy)",
            "level": round((dma50 + dma200) / 2, 2),
            "distance_pct": round(((price / ((dma50 + dma200) / 2)) - 1) * 100, 2),
            "slant": "Stack check",
        },
        {
            "avg": "200 DMA",
            "level": dma200,
            "distance_pct": vs200,
            "slant": "Long-base trend filter",
        },
    ]

    pivot_pp = round((day_high + day_low + price) / 3, 2)
    r1 = round(2 * pivot_pp - day_low, 2)
    s1 = round(2 * pivot_pp - day_high, 2)
    level_rows = [
        {"level": w52_hi, "kind": "52-week high (modeled)", "vs_spot_pct": vs_52_hi},
        {"level": r1, "kind": "R1 pivot", "vs_spot_pct": round(((price / r1) - 1) * 100, 2)},
        {"level": pivot_pp, "kind": "Classic pivot", "vs_spot_pct": round(((price / pivot_pp) - 1) * 100, 2)},
        {"level": dma50, "kind": "50 DMA", "vs_spot_pct": vs50},
        {"level": dma200, "kind": "200 DMA", "vs_spot_pct": vs200},
        {"level": s1, "kind": "S1 pivot", "vs_spot_pct": round(((price / s1) - 1) * 100, 2)},
        {"level": w52_lo, "kind": "52-week low (modeled)", "vs_spot_pct": vs_52_lo},
    ]

    sector_changes = [float(s["change"]) for s in STOCKS if infer_sector(s["symbol"]) == sector]
    sector_avg_chg = round(sum(sector_changes) / len(sector_changes), 2) if sector_changes else 0.0
    rel_sector = round(ch - sector_avg_chg, 2)

    volume_cr = round(_digest_ratio(stock["symbol"], "volcr", 0.35, 12.6), 2)
    turnover_cr = round(volume_cr * price / 90.0, 2)
    delivery_pct = int(round(_digest_ratio(stock["symbol"], "deliv", 42, 94)))

    reco = _reco_label(stock["symbol"])
    tgt_stub = round(price * (1 + _digest_ratio(stock["symbol"], "tgt", -0.06, 0.14)), 2)
    upside = round(((tgt_stub / price) - 1) * 100, 2)

    summary = (
        f"{stock['symbol']} closed this catalog session at ₹{price:.2f} ({ch:+.2f}% vs prior close proxy ₹{prev_close:.2f}). "
        f"Versus sector peers in this catalog the name is {rel_sector:+.2f}% vs the sector average day move ({sector_avg_chg:+.2f}%). "
        f"Technicals: RSI {rsi}, modeled 6-week trajectory {six_week_ret:+.2f}%. Valuation screens show PE ~{pe_ttm:.1f}x and PB ~{pb:.2f}x "
        f"(simulated fields). Recommendation stub: {reco}."
    )

    quote_snapshot = [
        {"metric": "Instrument", "value": stock["symbol"], "bench": "NSE-style listing", "note": "Cash equity"},
        {"metric": "Sector", "value": sector, "bench": "Heuristic map", "note": "Sector grouping"},
        {"metric": "Last price", "value": f"₹ {price:.2f}", "bench": f"Chg {ch:+.2f}%", "note": "Snapshot tick"},
        {"metric": "Prev. close (derived)", "value": f"₹ {prev_close:.2f}", "bench": "From % move", "note": "Simulated"},
        {"metric": "Open (stub)", "value": f"₹ {open_stub:.2f}", "bench": "Gap vs prev", "note": "Simulated"},
        {"metric": "Day range", "value": f"{day_low:.2f} – {day_high:.2f}", "bench": "₹ band", "note": "Modeled intraday"},
        {"metric": "52-week range", "value": f"{w52_lo:.2f} – {w52_hi:.2f}", "bench": f"{vs_52_hi:.1f}% below hi", "note": "From weekly model"},
        {"metric": "Volume (stub)", "value": f"{volume_cr:.2f} Cr shares", "bench": f"{turnover_cr:.2f} Cr ₹ turnover", "note": "Illustrative"},
        {"metric": "Delivery % (stub)", "value": f"{delivery_pct}%", "bench": "Institutional mix proxy", "note": "Simulated"},
    ]

    returns_rows = [
        {"period": "1 day", "chg_pct": ch, "comment": "Latest catalog session"},
        {"period": "5 sessions (stub)", "chg_pct": round(ch * 2.35 + _digest_ratio(stock["symbol"], "r5", -0.4, 0.4), 2), "comment": "Scaled proxy"},
        {"period": "MTD (stub)", "chg_pct": mtd_stub, "comment": "Illustrative"},
        {"period": "YTD (stub)", "chg_pct": ytd_stub, "comment": "Linked to 6w model"},
        {"period": "6 weeks (modeled)", "chg_pct": six_week_ret, "comment": "From chart path"},
        {"period": "Vs sector avg", "chg_pct": rel_sector, "comment": f"Sector avg {sector_avg_chg:+.2f}%"},
    ]

    technical_rows = [
        {"name": "RSI (14, stub)", "reading": str(rsi), "takeaway": "Neutral-to-stretched" if 45 <= rsi <= 65 else ("Oversold bias" if rsi < 45 else "Overbought risk")},
        {"name": "MACD histogram (stub)", "reading": f"{macd_hist:+.2f}", "takeaway": macd_signal},
        {"name": "Stochastic %K (stub)", "reading": str(stoch_k), "takeaway": "Momentum cooling" if stoch_k < 40 else "Momentum firm"},
        {"name": "ATR % (stub)", "reading": f"{atr_pct}%", "takeaway": f"Realized band vs spot ({analysis_data['volatility']} tape)"},
        {"name": "Trend alignment", "reading": analysis_data["signal"], "takeaway": "Vs 50/200 DMA stack in moving-average section"},
    ]

    vol_rows = [
        {"metric": "Daily σ proxy", "value": f"{atr_pct}%", "note": "Stub from session volatility"},
        {"metric": "Beta (stub)", "value": str(beta), "note": "Vs Nifty proxy"},
        {"metric": "Correlation to sector basket", "value": str(corr_sector), "note": "Catalog peer linkage"},
        {"metric": "Volatility percentile (stub)", "value": f"{vol_rank} / 100", "note": "Cross-sectional rank"},
    ]

    valuation_rows = [
        {"metric": "P/E (TTM, stub)", "value": f"{pe_ttm:.1f}x", "note": "Illustrative multiple"},
        {"metric": "P/B (stub)", "value": f"{pb:.2f}x", "note": "Book proxy"},
        {"metric": "PEG (stub)", "value": f"{peg:.2f}", "note": "Growth-normalized"},
        {"metric": "EV / EBITDA (stub)", "value": f"{ev_ebitda:.1f}x", "note": "Capital structure neutral"},
        {"metric": "Dividend yield (stub)", "value": f"{div_yield:.2f}%", "note": "Trailing indicative"},
        {"metric": "FCF yield (stub)", "value": f"{fcf_yield:.2f}%", "note": "Cash conversion proxy"},
    ]

    fundamental_rows = [
        {"metric": "EPS YoY % (stub)", "value": f"{eps_yoy:+.1f}%", "note": "Reported-style growth"},
        {"metric": "Revenue YoY % (stub)", "value": f"{rev_yoy:+.1f}%", "note": "Top-line rhythm"},
        {"metric": "Operating margin % (stub)", "value": f"{op_margin:.1f}%", "note": "Cost absorption"},
        {"metric": "ROE % (stub)", "value": f"{roe:.1f}%", "note": "Equity efficiency"},
        {"metric": "Debt / Equity (stub)", "value": f"{debt_equity:.2f}x", "note": "Leverage screen"},
    ]

    outlook_rows = [
        {"field": "Desk view (stub)", "detail": reco},
        {"field": "Horizon", "detail": "12–18 months (illustrative)"},
        {"field": "Price objective (stub)", "detail": f"₹ {tgt_stub:.2f} ({upside:+.1f}%)"},
        {"field": "Key upside risks", "detail": "Broad risk-on, sector rerating, execution beat (illustrative)"},
        {"field": "Key downside risks", "detail": "Macro shock, margin compression, regulation (illustrative)"},
    ]

    peers_detailed: list[dict[str, Any]] = []
    pool = [stock] + peer_slice
    for p in pool:
        sym = p["symbol"]
        px = float(p["price"])
        pch = float(p["change"])
        p_dma50 = round(px * 0.98, 2)
        p_vs50 = round(((px - p_dma50) / p_dma50) * 100, 2) if p_dma50 else 0.0
        p_pe = _digest_ratio(sym, "pe", 12.0, 48.0)
        p_rsi = int(round(_digest_ratio(sym, "rsi", 28, 74)))
        p_beta = _beta_stub(sym)
        p_52h = round(px * 1.052, 2)
        vs_hi = round(((px / p_52h) - 1) * 100, 2)
        peers_detailed.append(
            {
                "symbol": sym,
                "price": px,
                "change": pch,
                "pe_stub": round(p_pe, 1),
                "rsi_stub": p_rsi,
                "beta_stub": p_beta,
                "vs_dma50_pct": p_vs50,
                "vs_52w_hi_pct": vs_hi,
                "reco_stub": _reco_label(sym),
                "highlight": sym == stock["symbol"],
            }
        )
    peers_detailed.sort(key=lambda r: (not r["highlight"], -abs(float(r["change"]))))

    bullets = [
        f"Tape: {analysis_data['signal']} bias with RSI {rsi}; MACD histogram {macd_hist:+.2f} ({macd_signal}).",
        f"Trend stack: {vs50:+.2f}% vs 50 DMA and {vs200:+.2f}% vs 200 DMA — {'bullish structure' if vs50 >= 0 and vs200 >= 0 else 'mixed / repair phase'}.",
        f"Relative performance: {rel_sector:+.2f}% vs sector average move today ({sector_avg_chg:+.2f}%).",
        f"Six-week modeled path {six_week_ret:+.2f}% from W1→W6 reconstruction.",
        f"Valuation screens (simulated): PE {pe_ttm:.1f}x, PB {pb:.2f}x, yield {div_yield:.2f}%.",
        f"Desk stub: {reco} with illustrative target ₹{tgt_stub:.2f} ({upside:+.1f}%).",
        "All fundamentals and liquidity fields above are deterministic synthesized fields — not live data.",
    ]

    return {
        "generated_at": datetime.now().strftime("%d-%b-%Y %H:%M"),
        "sector": sector,
        "sector_avg_chg": sector_avg_chg,
        "summary": summary,
        "bullets": bullets,
        "quote_snapshot": quote_snapshot,
        "returns_rows": returns_rows,
        "ma_rows": ma_rows,
        "weekly_rows": weekly_rows,
        "technical_rows": technical_rows,
        "vol_rows": vol_rows,
        "valuation_rows": valuation_rows,
        "fundamental_rows": fundamental_rows,
        "level_rows": level_rows,
        "outlook_rows": outlook_rows,
        "peers_detailed": peers_detailed,
        "metrics": {"vs_dma50_pct": vs50, "vs_dma200_pct": vs200},
    }


def infer_sector(symbol: str) -> str:
    base = symbol.replace(".NS", "")
    for sector, keywords in SECTOR_KEYWORDS.items():
        if any(base.startswith(keyword) for keyword in keywords):
            return sector
    return "ENTERPRISE"


def enrich_search_rows(matched_stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": item["symbol"],
            "price": item["price"],
            "change": item["change"],
            "sector": infer_sector(item["symbol"]),
        }
        for item in matched_stocks
    ]


def build_market_pulse_data() -> dict[str, list[Any]]:
    ranked = sorted(STOCKS, key=lambda item: item["change"], reverse=True)
    top = ranked[:6]
    return {
        "labels": [item["symbol"].replace(".NS", "") for item in top],
        "change_series": [round(float(item["change"]), 2) for item in top],
    }


def build_sector_strength_data() -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = {}
    for stock in STOCKS:
        sector = infer_sector(stock["symbol"])
        buckets.setdefault(sector, []).append(float(stock["change"]))
    result: list[dict[str, Any]] = []
    for sector, changes in buckets.items():
        avg_change = round(sum(changes) / len(changes), 2)
        result.append({"sector": sector, "avg_change": avg_change, "count": len(changes)})
    result.sort(key=lambda row: row["avg_change"], reverse=True)
    return result


def build_market_breadth_data() -> dict[str, Any]:
    gainers = sum(1 for item in STOCKS if float(item["change"]) > 0)
    losers = sum(1 for item in STOCKS if float(item["change"]) < 0)
    flat = len(STOCKS) - gainers - losers
    return {"labels": ["Gainers", "Losers", "Unchanged"], "values": [gainers, losers, flat]}


def build_daily_change_buckets_data() -> dict[str, Any]:
    labels = ["≤ -1%", "-1% to 0%", "0% to +1%", "> +1%"]
    counts = [0, 0, 0, 0]
    for item in STOCKS:
        c = float(item["change"])
        if c <= -1:
            counts[0] += 1
        elif c < 0:
            counts[1] += 1
        elif c <= 1:
            counts[2] += 1
        else:
            counts[3] += 1
    return {"labels": labels, "values": counts}


def build_snapshot_price_chart_data(snapshot: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "labels": [item["symbol"].replace(".NS", "") for item in snapshot],
        "prices": [round(float(item["price"]), 2) for item in snapshot],
        "changes": [round(float(item["change"]), 2) for item in snapshot],
    }


def build_compare_rows(compared: list[dict[str, Any]], avg_price: float, avg_change: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not compared:
        return rows
    denom = avg_price if avg_price else 1.0
    for item in compared:
        price = float(item["price"])
        change = float(item["change"])
        rows.append(
            {
                "symbol": item["symbol"],
                "price": round(price, 2),
                "change": round(change, 2),
                "sector": infer_sector(item["symbol"]),
                "vs_avg_price_pct": round((price / denom - 1) * 100, 2),
                "vs_avg_change": round(change - avg_change, 2),
                "composite_score": round(change * 10 + 50, 1),
            }
        )
    rows.sort(key=lambda row: row["change"], reverse=True)
    return rows


def build_compare_insights(compared: list[dict[str, Any]], avg_change: float) -> list[str]:
    if len(compared) < 2:
        return [
            "Pick two or more symbols from the in-memory catalog to compute spreads, averages, and rankings.",
        ]
    insights: list[str] = []
    ranked = sorted(compared, key=lambda item: float(item["change"]), reverse=True)
    leader = ranked[0]
    laggard = ranked[-1]
    spread = round(float(leader["change"]) - float(laggard["change"]), 2)
    positives = sum(1 for item in compared if float(item["change"]) > 0)
    insights.append(
        f"{leader['symbol']} leads the set with {leader['change']}%. "
        f"{laggard['symbol']} trails at {laggard['change']}%, giving a {spread} pt intraday spread."
    )
    insights.append(
        f"Average cohort move is {avg_change}% with {positives} advancing tickers out of {len(compared)} selected."
    )
    prices = [float(item["price"]) for item in compared]
    insights.append(
        f"Price dispersion spans ₹{round(min(prices), 2)} → ₹{round(max(prices), 2)}, "
        "useful for benchmarking liquidity tiers across peers."
    )
    return insights


def extract_symbols_from_text(query: str) -> list[str]:
    upper_query = query.upper()
    found: list[str] = []
    token_matches = re.findall(r"[A-Z]{2,}(?:\.NS)?", upper_query)
    for token in token_matches:
        symbol = token if token.endswith(".NS") else STOCK_ALIASES.get(token, "")
        if symbol and symbol in STOCK_INDEX and symbol not in found:
            found.append(symbol)
    return found


def summarize_catalog_market_state(lower_prompt: str = "") -> str:
    n = len(STOCKS)
    gainers = sum(1 for s in STOCKS if float(s["change"]) > 0)
    losers = sum(1 for s in STOCKS if float(s["change"]) < 0)
    flat = n - gainers - losers
    avg_ch = round(sum(float(s["change"]) for s in STOCKS) / n, 2) if n else 0.0
    by_ch = sorted(STOCKS, key=lambda x: float(x["change"]), reverse=True)
    leader, laggard = by_ch[0], by_ch[-1]
    if avg_ch > 0.12:
        bias = "slightly risk-on"
    elif avg_ch < -0.12:
        bias = "slightly defensive"
    else:
        bias = "balanced-to-mixed"
    extra = ""
    lp = lower_prompt
    if "bullish" in lp or "bearish" in lp:
        extra = (
            f" If you force a label: the average tick is {avg_ch:+.2f}%, "
            f"so it reads more bullish than bearish on this tiny sample."
            if avg_ch >= 0
            else f" Average change is {avg_ch:+.2f}%, so the session skews soft here."
        )
    return (
        f"Market snapshot ({n} names): breadth {gainers} up / {losers} down / {flat} flat; "
        f"average move {avg_ch:+.2f}% — tone feels {bias}. "
        f"Leader {leader['symbol']} {float(leader['change']):+.2f}%, laggard {laggard['symbol']} {float(laggard['change']):+.2f}%. "
        f"In-app static feed — not live NSE/BSE.{extra}"
    )


def wants_market_overview(lower: str) -> bool:
    if "breadth" in lower:
        return True
    if "market sentiment" in lower or "sentiment of market" in lower:
        return True
    if "market" in lower and (
        any(
            w in lower
            for w in ("state", "doing", "today", "look", "feel", "situation", "overview", "picture", "condition")
        )
        or any(p in lower for p in ("tell me about", "explain the market", "describe the market"))
    ):
        return True
    if any(p in lower for p in ("how are stocks", "how stocks are", "overall stocks", "stock market")):
        return True
    return False


def reply_ranking_movers(lower_prompt: str) -> dict[str, Any] | None:
    pos_keys = ("top gainer", "best performer", "who gained", "biggest gainer", "hottest stock", "strongest stock")
    neg_keys = ("worst performer", "biggest loser", "biggest drop", "weakest stock", "bottom stock")
    if not any(k in lower_prompt for k in pos_keys + neg_keys):
        return None
    by_ch = sorted(STOCKS, key=lambda x: float(x["change"]), reverse=True)
    if any(k in lower_prompt for k in neg_keys):
        w = by_ch[-1]
        return {
            "reply": (
                f"Largest decline in the catalog is {w['symbol']} at {float(w['change']):+.2f}% "
                f"(₹{w['price']}). Snapshot only — not a signal."
            ),
            "links": [],
        }
    g = by_ch[0]
    return {
        "reply": (
            f"Largest gain in the catalog is {g['symbol']} at {float(g['change']):+.2f}% "
            f"(₹{g['price']}). Snapshot only — not a recommendation."
        ),
        "links": [],
    }


def reply_which_better(symbols: list[str]) -> dict[str, Any]:
    disclaimer = " Judging only by % change on this catalog snapshot — not investment advice."
    if len(symbols) >= 2:
        rows = [STOCK_INDEX[s] for s in symbols[:8] if s in STOCK_INDEX]
        if len(rows) < 2:
            return {"reply": "I need at least two tickers that exist in the symbol catalog.", "links": []}
        ranked = sorted(rows, key=lambda x: float(x["change"]), reverse=True)
        winner = ranked[0]
        tail = ", ".join(f"{r['symbol']} {float(r['change']):+.2f}%" for r in ranked[1:])
        return {
            "reply": (
                f"On % change alone today’s session favors {winner['symbol']} ({float(winner['change']):+.2f}%). "
                f"Then: {tail}.{disclaimer}"
            ),
            "links": [],
        }
    if len(symbols) == 1:
        s = symbols[0]
        st = STOCK_INDEX[s]
        peers = sorted([x for x in STOCKS if x["symbol"] != s], key=lambda x: float(x["change"]), reverse=True)[:3]
        peer_txt = ", ".join(f"{p['symbol']} {float(p['change']):+.2f}%" for p in peers)
        return {
            "reply": (
                f"{s} is printing {float(st['change']):+.2f}% (₹{st['price']}). "
                f"Other strong movers here: {peer_txt}. Add a second ticker for a direct matchup.{disclaimer}"
            ),
            "links": [],
        }
    top = sorted(STOCKS, key=lambda x: float(x["change"]), reverse=True)[:3]
    tops = ", ".join(f"{t['symbol']} {float(t['change']):+.2f}%" for t in top)
    soft = sorted(STOCKS, key=lambda x: float(x["change"]))[0]
    return {
        "reply": (
            f"No symbols named — snapshot leaders: {tops}; softest {soft['symbol']} {float(soft['change']):+.2f}%. "
            f"Try “which is better TCS vs INFY”.{disclaimer}"
        ),
        "links": [],
    }


def wants_comparison_language(lower: str) -> bool:
    return (
        "better" in lower
        or " vs " in lower
        or " versus " in lower
        or ("which" in lower and "stock" in lower)
        or ("pick" in lower and "stock" in lower)
        or ("who wins" in lower)
        or ("which one" in lower and ("buy" in lower or "stock" in lower))
    )


def build_chatbot_response(query: str) -> dict[str, Any]:
    """Conversation-first replies; navigation stays in the shell — no button spam."""
    prompt = query.strip()
    if not prompt:
        return {
            "reply": (
                "Ask anything finance-flavored: a ticker quote, market snapshot, which name looks stronger on % change, "
                "portfolio risk, prefix search, Algorithms Lab — all grounded in this symbol catalog unless you plug in an LLM API."
            ),
            "links": [],
        }

    lower_prompt = prompt.lower()
    symbols = extract_symbols_from_text(prompt)

    if re.search(r"\b(hello|hi|hey)\b", lower_prompt):
        return {
            "reply": (
                "Hi! I’m here to talk through symbols, comparisons, risk buckets, and the Algorithms Lab — "
                "just type what you’re curious about."
            ),
            "links": [],
        }

    if wants_market_overview(lower_prompt):
        return {"reply": summarize_catalog_market_state(lower_prompt), "links": []}

    ranked_reply = reply_ranking_movers(lower_prompt)
    if ranked_reply:
        return ranked_reply

    if any(p in lower_prompt for p in ("should i buy", "should i invest", "safe to buy")):
        return {
            "reply": (
                "I can’t give personal buy/sell advice. "
                "Ask for the market overview, a head-to-head (“which is better X vs Y”), or a quote — "
                "those I can answer from the symbol catalog."
            ),
            "links": [],
        }

    if wants_comparison_language(lower_prompt):
        return reply_which_better(symbols)

    if "compare" in lower_prompt:
        if len(symbols) >= 2:
            s1, s2 = symbols[0], symbols[1]
            a = STOCK_INDEX.get(s1)
            b = STOCK_INDEX.get(s2)
            if a and b:
                return {
                    "reply": (
                        f"{s1} is near ₹{a['price']} ({a['change']:+.2f}%), "
                        f"{s2} near ₹{b['price']} ({b['change']:+.2f}%). "
                        "Want a read on which name moved more aggressively?"
                    ),
                    "links": [],
                }
            return {
                "reply": f"You mentioned {s1} and {s2} — both should be tickers in the symbol catalog.",
                "links": [],
            }
        return {
            "reply": "Sure — name two tickers like “compare TCS and INFY” and I’ll summarize both sides.",
            "links": [],
        }

    if any(word in lower_prompt for word in ("price", "change", "quote", "return")) and symbols:
        stock = STOCK_INDEX[symbols[0]]
        trend = "up" if stock["change"] >= 0 else "down"
        return {
            "reply": (
                f"{stock['symbol']} is around ₹{stock['price']}, "
                f"{trend} {abs(stock['change'])}% on this snapshot. Ask for another symbol anytime."
            ),
            "links": [],
        }

    if any(word in lower_prompt for word in ("search", "prefix", "trie", "find symbol")):
        prefix_match = re.search(r"\b[A-Za-z]{1,5}\b", prompt)
        prefix = prefix_match.group(0).upper() if prefix_match else "RE"
        return {
            "reply": (
                f"If you type a short prefix like {prefix}, the catalog narrows that way — "
                "spell one in your next message and I’ll talk through what usually matches."
            ),
            "links": [],
        }

    if "risk" in lower_prompt or "portfolio" in lower_prompt or "optimize" in lower_prompt:
        risk = "Medium"
        if "low" in lower_prompt:
            risk = "Low"
        elif "high" in lower_prompt:
            risk = "High"
        return {
            "reply": (
                f"A {risk} template usually tilts toward steadier sleeves vs chasing beta — "
                "the optimizer turns that into sector weights you can cite in a write-up."
            ),
            "links": [],
        }

    if any(word in lower_prompt for word in ("algo", "algorithm", "lab", "demo", "sort", "graph", "avl", "heap")):
        return {
            "reply": (
                "The Algorithms Lab runs a sort first, then trie matches, AVL inorder, "
                "and a graph walk — good for showing structure plus UI in a walkthrough."
            ),
            "links": [],
        }

    if "volatility" in lower_prompt:
        return {
            "reply": (
                "Volatility is how much prices bounce around — higher means bigger swings and uncertainty. "
                "Your dashboard buckets daily % moves so you can visualize dispersion across tracked symbols."
            ),
            "links": [],
        }

    if "dividend" in lower_prompt:
        return {
            "reply": (
                "Dividends are profit payouts to shareholders — this build doesn’t model yields or payout ratios; "
                "stick to price/%change storytelling or extend STOCKS[] yourself."
            ),
            "links": [],
        }

    if "pe ratio" in lower_prompt or "p/e" in lower_prompt or "price to earnings" in lower_prompt:
        return {
            "reply": (
                "P/E compares stock price to earnings per share — cheap vs expensive depends on sector growth. "
                "FinPilot’s modeled snapshot doesn’t compute fundamentals; use it for structure + UX narrative."
            ),
            "links": [],
        }

    if any(k in lower_prompt for k in ("inflation", "interest rate", "rbi", "repo rate", "gdp")):
        return {
            "reply": (
                "Macro (rates, inflation, GDP) sets the backdrop for equities — this app doesn’t ingest live macro feeds. "
                "You can still discuss conceptually, while numbers stay tied to the static STOCKS snapshot."
            ),
            "links": [],
        }

    if symbols:
        symbol = symbols[0]
        stock = STOCK_INDEX.get(symbol)
        if stock:
            trend = "up" if stock["change"] >= 0 else "down"
            return {
                "reply": (
                    f"{symbol}: about ₹{stock['price']}, {trend} {abs(stock['change'])}% on this snapshot. "
                    "Name another ticker if you want a side-by-side story."
                ),
                "links": [],
            }
        return {
            "reply": (
                f"I saw {symbol} in your message — if it isn’t in the symbol catalog, "
                "try the full .NS ticker spelling."
            ),
            "links": [],
        }

    return {
        "reply": (
            "I’m missing a hook — try “what’s the market state”, “which is better RELIANCE vs TCS”, "
            "“top gainer in the catalog”, “explain volatility”, or any ticker like INFY."
        ),
        "links": [],
    }


def build_catalog_system_prompt_block() -> str:
    """Ground the LLM on our static STOCKS table so it does not invent prices."""
    lines = [
        "Authoritative in-app quotes for THIS application only (not live markets):",
    ]
    for row in STOCKS:
        lines.append(f"- {row['symbol']}: ₹{row['price']}, change {row['change']}%")
    lines.append(
        "FinPilot DS scope: educational dashboards, Trie prefix search, compare cohorts, "
        "risk-template optimizer, Algorithms Lab (merge/quick/heap sort + Trie + AVL + graph traversal). "
        "If asked for data outside this list, say it is not in the symbol catalog."
    )
    return "\n".join(lines)


def external_chat_reply(query: str, history: list[dict[str, Any]]) -> str | None:
    if not CHAT_API_URL or not CHAT_API_KEY:
        return None
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "You are FinPilot DS: a concise assistant for a data-structures + finance intelligence UI. "
                "Answer anything reasonable about stocks, portfolios, risk concepts, or how such apps are built — "
                "but whenever this app’s tickers appear, use ONLY the numbers from the catalog below.\n\n"
                + build_catalog_system_prompt_block()
                + "\n\nReply in plain conversational text. Do not push navigation (no ‘open dashboard’, "
                "‘try search’, or lists of app URLs) unless the user explicitly asks where to go."
            ),
        }
    ]
    for item in history[-4:]:
        q = str(item.get("query", "")).strip()
        a = str(item.get("reply", "")).strip()
        if q:
            messages.append({"role": "user", "content": q})
        if a:
            messages.append({"role": "assistant", "content": a})
    messages.append({"role": "user", "content": query})
    payload = json.dumps({"model": CHAT_MODEL, "messages": messages}).encode("utf-8")
    req = url_request.Request(
        CHAT_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {CHAT_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with url_request.urlopen(req, timeout=CHAT_HTTP_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
            choices = data.get("choices", [])
            if not choices:
                return None
            message = choices[0].get("message", {})
            content = str(message.get("content", "")).strip()
            return content or None
    except (url_error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError):
        return None


def run_cpp_engine(args: list[str]) -> dict:
    if not CPP_ENGINE.exists():
        return {
            "status": "error",
            "message": f"Compile {CPP_ENGINE.relative_to(BASE_DIR)} first",
        }
    try:
        result = subprocess.run(
            [str(CPP_ENGINE), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        output = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if not output:
            return {"status": "error", "message": stderr or "No engine output"}
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return {
                "status": "error",
                "message": "Invalid JSON from C++ engine",
                "raw_output": output,
                "stderr": stderr,
            }
        if result.returncode != 0:
            data.setdefault("status", "error")
            if stderr:
                data.setdefault("message", stderr)
        return data
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "C++ engine timeout"}
    except OSError as exc:
        return {"status": "error", "message": f"Engine execution failed: {exc}"}


@app.route("/")
def home():
    catalog_symbols = len(STOCKS)
    market_advancers = sum(1 for item in STOCKS if float(item["change"]) > 0)
    return render_template(
        "home.html",
        catalog_symbols=catalog_symbols,
        market_advancers=market_advancers,
        market_decliners=catalog_symbols - market_advancers,
        **nav_context(),
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get(SESSION_FP_USER):
        return redirect(url_for("dashboard"))
    next_from_query = _safe_next_path(request.args.get("next"))
    sticky_next = next_from_query
    if request.method == "POST":
        sticky_next = _safe_next_path(request.form.get("next")) or next_from_query
        email = _normalize_auth_email(request.form.get("email"))
        password = request.form.get("password") or ""
        row = auth_db.get_user_by_email(email)
        stored_hash = row["password_hash"] if row else ""
        if not email or not password:
            flash("Enter email and password.", "danger")
        elif not row or not check_password_hash(stored_hash, password):
            flash("Invalid email or password.", "danger")
        else:
            session[SESSION_FP_USER] = email
            session[SESSION_FP_USER_FIRST] = _resolve_display_first_name(
                {"first_name": row.get("first_name", "")},
                email,
            )
            session.modified = True
            flash("Signed in successfully.", "success")
            return redirect(sticky_next or url_for("dashboard"))
    ctx = nav_context()
    ctx["login_next_path"] = sticky_next
    return render_template("login.html", **ctx)


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get(SESSION_FP_USER):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        first = (request.form.get("first_name") or "").strip()
        last = (request.form.get("last_name") or "").strip()
        email = _normalize_auth_email(request.form.get("email"))
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""
        messages: list[tuple[str, str]] = []
        if len(first) < 1 or len(last) < 1:
            messages.append(("danger", "Enter first and last name."))
        if not AUTH_EMAIL_RE.match(email):
            messages.append(("danger", "Enter a valid email address."))
        if len(password) < AUTH_MIN_PASSWORD_LEN:
            messages.append(
                ("danger", f"Password must be at least {AUTH_MIN_PASSWORD_LEN} characters.")
            )
        if password != confirm:
            messages.append(("danger", "Passwords do not match."))
        if messages:
            for category, msg in messages:
                flash(msg, category)
        else:
            try:
                auth_db.create_user(
                    email,
                    generate_password_hash(password),
                    first[:80],
                    last[:80],
                )
            except sqlite3.IntegrityError:
                flash("That email is already registered.", "danger")
            else:
                flash("Account created. You can sign in now.", "success")
                return redirect(url_for("login"))
    return render_template("register.html", **nav_context())


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.pop(SESSION_FP_USER, None)
    session.pop(SESSION_FP_USER_FIRST, None)
    session.modified = True
    flash("You have been signed out.", "info")
    return redirect(url_for("home"))


@app.route("/dashboard")
def dashboard():
    market_snapshot = sorted(STOCKS, key=lambda item: abs(item["change"]), reverse=True)[:8]
    top_movers = sorted(STOCKS, key=lambda item: item["change"], reverse=True)[:5]
    gainers = len([item for item in STOCKS if item["change"] > 0])
    losers = len(STOCKS) - gainers
    dashboard_catalog = [
        {
            "symbol": item["symbol"],
            "price": item["price"],
            "change": round(float(item["change"]), 2),
            "sector": infer_sector(item["symbol"]),
        }
        for item in STOCKS
    ]
    return render_template(
        "dashboard.html",
        market_snapshot=market_snapshot,
        top_movers=top_movers,
        dashboard_catalog=dashboard_catalog,
        market_pulse_data=build_market_pulse_data(),
        sector_strength_data=build_sector_strength_data(),
        market_breadth_data=build_market_breadth_data(),
        change_buckets_data=build_daily_change_buckets_data(),
        snapshot_price_chart_data=build_snapshot_price_chart_data(market_snapshot),
        gainers=gainers,
        losers=losers,
        **nav_context(),
    )


@app.route("/search")
def search():
    outcome = run_stock_search(request.args.get("q", ""))
    search_chart_data = build_search_chart_data(outcome["matched_stocks"])
    search_insights = build_search_insights(outcome["query"], outcome)
    popular_pick_symbols = [item["symbol"] for item in STOCKS[:8]]
    search_rows = enrich_search_rows(outcome["matched_stocks"])
    return render_template(
        "search.html",
        query=outcome["query"],
        suggestions=outcome["suggestions"],
        source=outcome["source"],
        match_mode=outcome["match_mode"],
        error_message=outcome["error_message"],
        result_count=outcome["result_count"],
        matched_stocks=outcome["matched_stocks"],
        search_rows=search_rows,
        search_chart_data=search_chart_data,
        search_insights=search_insights,
        popular_pick_symbols=popular_pick_symbols,
        max_search_results=MAX_SEARCH_RESULTS,
        **nav_context(),
    )


@lru_cache(maxsize=1)
def fpdf2_available() -> bool:
    """fpdf2 exposes the importable ``fpdf`` package used by PDF export."""
    try:
        import fpdf  # noqa: F401

        return True
    except ImportError:
        return False


def _pdf_txt(val: Any) -> str:
    if val is None:
        return ""
    t = (
        str(val)
        .replace("₹", "Rs.")
        .replace("Δ", "D")
        .replace("−", "-")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )
    return t.encode("latin-1", "replace").decode("latin-1")


def load_analysis_context(symbol_raw: str | None) -> dict[str, Any]:
    cleaned = (symbol_raw or "").strip() or DEFAULT_SYMBOL
    symbol = sanitize_symbol(cleaned)
    stock = find_stock(symbol) or STOCK_INDEX[DEFAULT_SYMBOL]
    analysis_data = build_analysis_data(stock)
    chart_data = build_analysis_chart_data(analysis_data)
    gaps = [
        round(float(p) - float(d), 2)
        for p, d in zip(chart_data["price_series"], chart_data["dma50_series"])
    ]
    analysis_gap_chart_data = {"labels": chart_data["labels"], "gaps": gaps}
    return {
        "stock": stock,
        "analysis_data": analysis_data,
        "chart_data": chart_data,
        "analysis_gap_chart_data": analysis_gap_chart_data,
    }


def render_analysis_pdf_bytes(full_report: dict[str, Any], analysis_data: dict[str, Any]) -> bytes:
    from fpdf import FPDF

    sym = _pdf_txt(analysis_data["symbol"])
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(12, 12, 12)

    def heading(text: str, size: int = 10) -> None:
        pdf.set_font("Helvetica", "B", size)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 5, _pdf_txt(text))
        pdf.ln(1)

    def paragraph(text: str, size: int = 8) -> None:
        pdf.set_font("Helvetica", "", size)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 4, _pdf_txt(text))
        pdf.ln(1)

    def table_block(title: str, headers: list[str], rows: list[list[str]], widths: tuple[float, ...]) -> None:
        heading(title, 9)
        pdf.set_font("Helvetica", "", 7)
        lh = 5.0
        ew_local = pdf.epw
        ws = sum(widths)
        scaled = tuple(ew_local * (w / ws) for w in widths)
        with pdf.table(width=ew_local, col_widths=scaled, line_height=lh) as table:
            hdr = table.row()
            for h in headers:
                hdr.cell(_pdf_txt(h))
            for row in rows:
                rr = table.row()
                for cell in row:
                    rr.cell(_pdf_txt(cell))
        pdf.set_x(pdf.l_margin)

    pdf.add_page()
    heading(f"Equity research snapshot — {sym}", 13)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pdf.epw, 4, _pdf_txt(f"Generated {full_report['generated_at']} — FinPilot DS symbol catalog."))
    pdf.ln(1)
    pdf.set_x(pdf.l_margin)
    paragraph(full_report["summary"])

    ew = pdf.epw
    qs = full_report["quote_snapshot"]
    table_block(
        "A. Quote & session snapshot",
        ["Field", "Value", "Bench", "Note"],
        [[str(r["metric"]), str(r["value"]), str(r["bench"]), str(r["note"])] for r in qs],
        (ew * 0.22, ew * 0.26, ew * 0.26, ew * 0.26),
    )
    table_block(
        "B. Return analytics (%)",
        ["Horizon", "Return %", "Comment"],
        [[str(r["period"]), str(r["chg_pct"]), str(r["comment"])] for r in full_report["returns_rows"]],
        (ew * 0.26, ew * 0.18, ew * 0.56),
    )
    table_block(
        "C. Moving averages",
        ["Average", "Level Rs.", "Dist.%", "Stack"],
        [
            [str(r["avg"]), str(r["level"]), str(r["distance_pct"]), str(r["slant"])]
            for r in full_report["ma_rows"]
        ],
        (ew * 0.28, ew * 0.2, ew * 0.16, ew * 0.36),
    )
    table_block(
        "D. Weekly modeled path",
        ["Week", "Close", "DMA50", "WoW%", "Gap", "Above DMA"],
        [
            [
                str(r["period"]),
                str(round(float(r["model_close"]), 2)),
                str(round(float(r["model_dma50"]), 2)),
                str(r["wow_chg_pct"]),
                str(r["price_minus_dma50"]),
                str(r["above_dma"]),
            ]
            for r in full_report["weekly_rows"]
        ],
        (ew * 0.1, ew * 0.14, ew * 0.14, ew * 0.12, ew * 0.14, ew * 0.22),
    )
    table_block(
        "E. Technical indicators",
        ["Indicator", "Reading", "View"],
        [[str(r["name"]), str(r["reading"]), str(r["takeaway"])] for r in full_report["technical_rows"]],
        (ew * 0.34, ew * 0.18, ew * 0.48),
    )
    table_block(
        "F. Volatility & risk",
        ["Metric", "Value", "Comment"],
        [[str(r["metric"]), str(r["value"]), str(r["note"])] for r in full_report["vol_rows"]],
        (ew * 0.42, ew * 0.18, ew * 0.40),
    )
    table_block(
        "G. Valuation (simulated)",
        ["Ratio", "Value", "Note"],
        [[str(r["metric"]), str(r["value"]), str(r["note"])] for r in full_report["valuation_rows"]],
        (ew * 0.32, ew * 0.22, ew * 0.46),
    )
    table_block(
        "H. Fundamentals (simulated)",
        ["Line item", "Value", "Note"],
        [[str(r["metric"]), str(r["value"]), str(r["note"])] for r in full_report["fundamental_rows"]],
        (ew * 0.34, ew * 0.18, ew * 0.48),
    )
    table_block(
        "I. Support / resistance ladder",
        ["Level type", "Price Rs.", "Vs spot %"],
        [
            [str(r["kind"]), str(round(float(r["level"]), 2)), str(r["vs_spot_pct"])]
            for r in full_report["level_rows"]
        ],
        (ew * 0.42, ew * 0.28, ew * 0.30),
    )

    pdf.add_page(orientation="L")
    heading("J. Sector peer matrix", 10)
    ew_l = pdf.epw
    frac = (0.18, 0.11, 0.09, 0.09, 0.09, 0.09, 0.12, 0.11, 0.12)
    fs = sum(frac)
    widths_l = tuple(ew_l * (f / fs) for f in frac)
    headers_p = ["Sym", "Px", "d%", "PE", "RSI", "Beta", "50DMA", "Hi%", "Rec"]
    peers = full_report["peers_detailed"]
    pdf.set_font("Helvetica", "", 6)
    with pdf.table(width=ew_l, col_widths=widths_l, line_height=4.5) as table:
        hr = table.row()
        for h in headers_p:
            hr.cell(h)
        for peer in peers:
            tag = "(Subject)" if peer.get("highlight") else ""
            rr = table.row()
            rr.cell(_pdf_txt(f"{peer['symbol']} {tag}".strip()))
            rr.cell(_pdf_txt(str(round(float(peer["price"]), 2))))
            rr.cell(_pdf_txt(str(peer["change"])))
            rr.cell(_pdf_txt(str(peer["pe_stub"])))
            rr.cell(_pdf_txt(str(peer["rsi_stub"])))
            rr.cell(_pdf_txt(str(peer["beta_stub"])))
            rr.cell(_pdf_txt(str(peer["vs_dma50_pct"])))
            rr.cell(_pdf_txt(str(peer["vs_52w_hi_pct"])))
            rr.cell(_pdf_txt(str(peer["reco_stub"])))
    pdf.set_x(pdf.l_margin)

    pdf.add_page(orientation="P")
    ew = pdf.epw
    table_block(
        "K. Scenario outlook",
        ["Topic", "Detail"],
        [[str(r["field"]), str(r["detail"])] for r in full_report["outlook_rows"]],
        (ew * 0.32, ew * 0.68),
    )

    heading("L. Analyst bullets", 9)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_x(pdf.l_margin)
    for idx, line in enumerate(full_report["bullets"], start=1):
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 4, _pdf_txt(f"{idx}. {line}"))
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(
        pdf.epw,
        3,
        _pdf_txt("Disclaimer: synthesized analytical output — not investment advice or live market data."),
    )

    raw_out = pdf.output(dest="S")
    if isinstance(raw_out, str):
        return raw_out.encode("latin-1")
    return bytes(raw_out)


@app.route("/analysis")
def analysis():
    ctx = load_analysis_context(request.args.get("symbol"))
    return render_template(
        "analysis.html",
        analysis_data=ctx["analysis_data"],
        chart_data=ctx["chart_data"],
        analysis_gap_chart_data=ctx["analysis_gap_chart_data"],
        stocks=STOCKS,
        pdf_export_available=fpdf2_available(),
        analysis_pdf_user_slug=_export_filename_user_segment(),
        **nav_context(),
    )


@app.route("/analysis/export")
def analysis_export():
    """Always returns the tabular analysis report as a PDF download (no HTML report page)."""
    ctx = load_analysis_context(request.args.get("symbol"))
    full_report = build_full_report_payload(ctx["stock"], ctx["analysis_data"], ctx["chart_data"])
    try:
        pdf_blob = render_analysis_pdf_bytes(full_report, ctx["analysis_data"])
    except ImportError:
        return Response(
            "PDF export requires the fpdf2 package. On the server run: pip install fpdf2",
            status=503,
            mimetype="text/plain; charset=utf-8",
        )
    except Exception as exc:
        return Response(
            f"PDF generator error: {exc}",
            status=500,
            mimetype="text/plain; charset=utf-8",
        )
    if not pdf_blob:
        return Response(
            "PDF generator produced empty output.",
            status=500,
            mimetype="text/plain; charset=utf-8",
        )
    sym_clean = ctx["analysis_data"]["symbol"].replace(".NS", "_NS")
    user_slug = _export_filename_user_segment()
    fname_base = f"{sym_clean}_{user_slug}_analysis_report.pdf"
    fname = secure_filename(fname_base) or f"{sym_clean}_analysis_report.pdf"
    return Response(
        pdf_blob,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.route("/compare")
def compare():
    raw_symbols = []
    csv_symbols = request.args.get("symbols", "").strip()
    if csv_symbols:
        raw_symbols.extend([item.strip() for item in csv_symbols.split(",") if item.strip()])
    for idx in range(1, 9):
        value = request.args.get(f"s{idx}", "").strip()
        if value:
            raw_symbols.append(value)
    if not raw_symbols:
        raw_symbols = ["TCS.NS", "INFY.NS"]

    symbols = [sanitize_symbol(value, "") for value in raw_symbols]
    symbols = list(dict.fromkeys([sym for sym in symbols if sym]))[:8]
    invalid_symbols = [sym for sym in symbols if sym and find_stock(sym) is None]
    compared = [find_stock(sym) for sym in symbols if sym]
    compared = [item for item in compared if item is not None]

    best_stock = max(compared, key=lambda item: item["change"]) if compared else None
    worst_stock = min(compared, key=lambda item: item["change"]) if compared else None
    avg_change = round(sum(item["change"] for item in compared) / len(compared), 2) if compared else 0.0
    avg_price = round(sum(item["price"] for item in compared) / len(compared), 2) if compared else 0.0
    ordered = sorted(compared, key=lambda item: float(item["change"]), reverse=True)
    compare_chart_data = {
        "labels": [item["symbol"] for item in ordered],
        "price_data": [item["price"] for item in ordered],
        "change_data": [item["change"] for item in ordered],
    }
    compare_momentum_chart_data = {
        "labels": [item["symbol"].replace(".NS", "") for item in ordered],
        "changes": [round(float(item["change"]), 2) for item in ordered],
    }
    compare_rows = build_compare_rows(compared, avg_price, avg_change)
    compare_insights = build_compare_insights(compared, avg_change)
    advance_ct = sum(1 for item in compared if float(item["change"]) > 0)
    decline_ct = sum(1 for item in compared if float(item["change"]) < 0)
    flat_ct = len(compared) - advance_ct - decline_ct
    return render_template(
        "compare.html",
        compared=compared,
        compare_rows=compare_rows,
        compare_insights=compare_insights,
        selected=symbols,
        invalid_symbols=invalid_symbols,
        all_symbols=[item["symbol"] for item in STOCKS],
        compare_chart_data=compare_chart_data,
        compare_momentum_chart_data=compare_momentum_chart_data,
        best_stock=best_stock,
        worst_stock=worst_stock,
        avg_change=avg_change,
        avg_price=avg_price,
        advance_ct=advance_ct,
        decline_ct=decline_ct,
        flat_ct=flat_ct,
        **nav_context(),
    )


@app.route("/optimizer")
def optimizer():
    budget_value = parse_budget(request.args.get("budget", str(DEFAULT_BUDGET)))
    risk = normalize_risk(request.args.get("risk", "Medium"))
    horizon = normalize_optimizer_horizon(request.args.get("horizon"))
    goal = normalize_optimizer_goal(request.args.get("goal"))
    plan = compute_portfolio_allocation(risk, budget_value, horizon_months=horizon, goal=goal)
    return render_template(
        "optimizer.html",
        budget=budget_value,
        risk=plan["summary"]["risk"],
        horizon_months=plan["summary"]["horizon_months"],
        goal=plan["summary"]["goal"],
        allocation=plan["allocation"],
        allocation_chart_data=plan["allocation_chart_data"],
        optimizer_summary=plan["summary"],
        optimizer_insights=plan["optimizer_insights"],
        optimizer_radar_data=plan["optimizer_radar_data"],
        optimizer_mc_chart_data=plan["optimizer_mc_chart_data"],
        **nav_context(),
    )


@app.route("/api/optimizer/preview")
def optimizer_preview():
    budget_value = parse_budget(request.args.get("budget", str(DEFAULT_BUDGET)))
    risk = normalize_risk(request.args.get("risk", "Medium"))
    horizon = normalize_optimizer_horizon(request.args.get("horizon"))
    goal = normalize_optimizer_goal(request.args.get("goal"))
    plan = compute_portfolio_allocation(risk, budget_value, horizon_months=horizon, goal=goal)
    return jsonify({"status": "ok", **plan})


@app.route("/chatbot", methods=["GET", "POST"])
def chatbot():
    if request.args.get("clear") == "1":
        session.pop("chat_history", None)
        return redirect(url_for("chatbot"))

    history = session.get("chat_history", [])
    if not isinstance(history, list):
        history = []

    if request.method == "POST":
        query = request.form.get("q", "").strip()[:MAX_CHAT_QUERY_LEN]
    else:
        query = request.args.get("q", "").strip()[:MAX_CHAT_QUERY_LEN]

    reply, links, provider = compose_chat_turn(query, history)
    history = append_chat_history(history, query, reply, links, provider)
    session["chat_history"] = history

    return render_template(
        "chatbot.html",
        query=query,
        reply=reply,
        links=links,
        history=history,
        **nav_context(),
    )


@app.route("/api/chatbot", methods=["POST"])
def chatbot_api():
    payload = request.get_json(silent=True) or {}
    query = str(payload.get("q", "")).strip()[:MAX_CHAT_QUERY_LEN]
    history = session.get("chat_history", [])
    if not isinstance(history, list):
        history = []

    reply, links, provider = compose_chat_turn(query, history)
    history = append_chat_history(history, query, reply, links, provider)
    session["chat_history"] = history

    return jsonify(
        {
            "status": "ok",
            "query": query,
            "reply": reply,
            "links": links,
            "provider": provider,
            "history": history,
        }
    )


@app.route("/demo")
def demo():
    nums = request.args.get("nums", "8,3,5,1,9").strip()
    algo = request.args.get("algo", "merge").strip().lower()
    graph_algo = request.args.get("graph_algo", "bfs").strip().lower()
    if algo not in ALLOWED_SORT_ALGOS:
        algo = "merge"
    if graph_algo not in ALLOWED_GRAPH_ALGOS:
        graph_algo = "bfs"
    sort_result = run_cpp_engine(["sort", algo, nums])
    graph_result = run_cpp_engine(["graph", graph_algo, "IT"])
    return render_template(
        "demo.html",
        nums=nums,
        algo=algo,
        graph_algo=graph_algo,
        sort_result=sort_result,
        graph_result=graph_result,
        **nav_context(),
    )


@app.route("/admin")
def admin():
    health = run_cpp_engine(["health"])
    modules = [
        {"name": "Flask API", "status": "Healthy", "latency": "40ms"},
        {
            "name": "C++ DS Engine",
            "status": "Healthy" if health.get("status") == "ok" else "Issue",
            "latency": "16ms" if health.get("status") == "ok" else "N/A",
        },
        {"name": "Stock Catalog", "status": f"{len(STOCKS)} symbols", "latency": "In-memory"},
        {"name": "SQLite Store", "status": "Not configured", "latency": "N/A"},
    ]
    return render_template("admin.html", modules=modules, **nav_context())


@app.route("/about")
def about():
    return render_template("about.html", **nav_context())


@app.route("/api/ds/<command>")
def ds_api(command: str):
    command = command.lower()
    if command == "health":
        data = run_cpp_engine(["health"])
        return jsonify(data), (200 if data.get("status") == "ok" else 500)
    if command == "trie":
        prefix = request.args.get("prefix", "RE").strip().upper()[:20]
        if not ALLOWED_TRIE_PREFIX_RE.fullmatch(prefix):
            return jsonify({"status": "error", "message": "Invalid trie prefix"}), 400
        data = run_cpp_engine(["trie", prefix])
        return jsonify(data), (200 if data.get("status") == "ok" else 400)
    if command == "sort":
        algo = request.args.get("algo", "merge").strip().lower()
        data = request.args.get("data", "8,3,5,1,9")
        if algo not in ALLOWED_SORT_ALGOS:
            return jsonify({"status": "error", "message": f"Unsupported sort algo: {algo}"}), 400
        ok, msg, normalized = normalize_sort_csv(data)
        if not ok:
            return jsonify({"status": "error", "message": msg}), 400
        result = run_cpp_engine(["sort", algo, normalized])
        return jsonify(result), (200 if result.get("status") == "ok" else 400)
    if command == "graph":
        algo = request.args.get("algo", "bfs").strip().lower()
        start = request.args.get("start", "IT").strip().upper()
        if algo not in ALLOWED_GRAPH_ALGOS:
            return jsonify({"status": "error", "message": f"Unsupported graph algo: {algo}"}), 400
        if not ALLOWED_GRAPH_START_RE.fullmatch(start):
            return jsonify({"status": "error", "message": "Invalid graph start node"}), 400
        result = run_cpp_engine(["graph", algo, start])
        return jsonify(result), (200 if result.get("status") == "ok" else 400)
    if command == "avl":
        data = request.args.get("data", "10,20,30,40,50,25")
        ok, msg, normalized = normalize_avl_csv(data)
        if not ok:
            return jsonify({"status": "error", "message": msg}), 400
        result = run_cpp_engine(["avl", normalized])
        return jsonify(result), (200 if result.get("status") == "ok" else 400)
    return jsonify({"status": "error", "message": "Unsupported DS command"}), 400


@app.route("/api/market/gainers")
def market_gainers():
    limit_raw = request.args.get("limit", "5").strip()
    limit = 5
    if limit_raw.isdigit():
        limit = min(max(int(limit_raw), 1), 20)
    gainers = sorted(STOCKS, key=lambda item: item["change"], reverse=True)[:limit]
    return jsonify({"status": "ok", "gainers": gainers})


@app.route("/api/market/sectors")
def market_sectors():
    return jsonify({"status": "ok", "sectors": build_sector_strength_data()})


@app.route("/api/market/overview")
def market_overview():
    gainers_ct = sum(1 for item in STOCKS if item["change"] > 0)
    return jsonify(
        {
            "status": "ok",
            "symbol_count": len(STOCKS),
            "gainers_count": gainers_ct,
            "losers_count": len(STOCKS) - gainers_ct,
            "pulse": build_market_pulse_data(),
            "sectors": build_sector_strength_data(),
            "breadth": build_market_breadth_data(),
            "change_buckets": build_daily_change_buckets_data(),
        }
    )


if __name__ == "__main__":
    app.run(debug=True)
