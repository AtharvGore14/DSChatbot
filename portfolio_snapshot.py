"""Broker-style portfolio JSON — per-user files + guest import + optional demo sample.

Resolution (logged-in): PORTFOLIO_JSON_PATH → instance/portfolios/users/<sha256(email)>/<slug>_<importStem>.json (newest mtime)
  → legacy instance/portfolios/<sha256(email).json> → import/portfolio_sample.json
Resolution (guest):    PORTFOLIO_JSON_PATH → instance/user_portfolio.json → import/portfolio_sample.json

Imports are saved as ``{user_label_slug}_{originalFileStem}.json`` under a private directory keyed by account email
so each login loads that account’s latest uploaded file.

Logged-in users never read instance/user_portfolio.json (so another guest session cannot leak in).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

_APP_ROOT = Path(__file__).resolve().parent
_INSTANCE_DIR = _APP_ROOT / "instance"
_USER_PORTFOLIOS_DIR = _INSTANCE_DIR / "portfolios"
_USER_PORTFOLIO_USERS_DIR = _USER_PORTFOLIOS_DIR / "users"
_GUEST_PORTFOLIO_FILE = _INSTANCE_DIR / "user_portfolio.json"
_SAMPLE_PORTFOLIO_FILE = _APP_ROOT / "import" / "portfolio_sample.json"

_cached: dict[str, Any] | None = None
_cached_key: str | None = None


def invalidate_cache() -> None:
    global _cached, _cached_key
    _cached = None
    _cached_key = None


def _normalized_email(email: str | None) -> str | None:
    if not email:
        return None
    e = str(email).strip().lower()
    return e or None


def _email_sha256_hex(email: str) -> str:
    em = _normalized_email(email)
    if not em:
        raise ValueError("email required")
    return hashlib.sha256(em.encode()).hexdigest()


def _user_portfolio_dir(email: str) -> Path:
    """Per-account directory (opaque id) — imports are named inside with a human-readable prefix."""
    return _USER_PORTFOLIO_USERS_DIR / _email_sha256_hex(email)


def _legacy_flat_portfolio_path(email: str) -> Path:
    """Pre–per-import naming: a single file instance/portfolios/<sha256>.json"""
    return _USER_PORTFOLIOS_DIR / f"{_email_sha256_hex(email)}.json"


def _sanitize_label_slug(raw: str | None, fallback_email: str | None) -> str:
    """Filesystem-safe token from first name or email local-part (e.g. atharv)."""
    s = (raw or "").strip()
    if s:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
        if slug:
            return slug[:48]
    em = _normalized_email(fallback_email)
    if em:
        local = em.split("@", 1)[0]
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", local).strip("_").lower()
        if slug:
            return slug[:48]
    return "user"


def _sanitize_import_stem(original_name: str | None) -> str:
    """Stem only (no .json); safe characters."""
    base = (original_name or "portfolio").strip() or "portfolio"
    base = os.path.basename(base)
    base = re.sub(r"[^\w.\-]+", "_", base, flags=re.UNICODE)
    if base.lower().endswith(".json"):
        base = base[:-5]
    base = re.sub(r"_+", "_", base).strip("._- ") or "portfolio"
    return base[:72]


def latest_json_in_dir(folder: Path) -> Path | None:
    """Most recently modified *.json in folder, or None."""
    if not folder.is_dir():
        return None
    cands = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".json"]
    if not cands:
        return None
    cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0]


def path_for_user_portfolio(email: str | None) -> Path | None:
    """Resolved active JSON for this account (newest named import, else legacy single file)."""
    em = _normalized_email(email)
    if not em:
        return None
    d = _user_portfolio_dir(em)
    latest = latest_json_in_dir(d)
    if latest:
        return latest
    leg = _legacy_flat_portfolio_path(em)
    if leg.is_file():
        return leg
    return None


def get_resolved_portfolio_path(user_email: str | None = None) -> Path | None:
    """Active JSON file on disk for this viewer, or None."""
    return _resolve_json_path(user_email)


def _resolve_json_path(user_email: str | None = None) -> Path | None:
    env = os.environ.get("PORTFOLIO_JSON_PATH", "").strip()
    if env:
        ep = Path(env)
        if ep.is_file():
            return ep
    em = _normalized_email(user_email)
    if em:
        up = path_for_user_portfolio(em)
        if up and up.is_file():
            return up
        if _SAMPLE_PORTFOLIO_FILE.is_file():
            return _SAMPLE_PORTFOLIO_FILE
        return None
    if _GUEST_PORTFOLIO_FILE.is_file():
        return _GUEST_PORTFOLIO_FILE
    if _SAMPLE_PORTFOLIO_FILE.is_file():
        return _SAMPLE_PORTFOLIO_FILE
    return None


def load_portfolio_snapshot(
    *, user_email: str | None = None, force_reload: bool = False
) -> dict[str, Any] | None:
    """Return parsed portfolio JSON for this viewer (session user or guest)."""
    global _cached, _cached_key
    path = _resolve_json_path(user_email)
    if path is None:
        return None
    scope = _normalized_email(user_email) or "guest"
    key = f"{scope}|{path.resolve()}|{path.stat().st_mtime}"
    if not force_reload and _cached is not None and _cached_key == key:
        return _cached
    with open(path, encoding="utf-8") as f:
        _cached = json.load(f)
    _cached_key = key
    return _cached


def save_portfolio_json(
    payload: dict[str, Any],
    *,
    user_email: str | None,
    import_filename: str | None = None,
    user_label_slug: str | None = None,
) -> Path:
    """Persist import: logged-in → instance/portfolios/users/<sha256>/{slug}_{stem}.json; guest → user_portfolio.json."""
    if not payload.get("holdings") and not payload.get("metrics"):
        raise ValueError("Expected metrics and/or holdings in JSON payload.")
    invalidate_cache()
    em = _normalized_email(user_email)
    if em:
        slug = _sanitize_label_slug(user_label_slug, em)
        stem = _sanitize_import_stem(import_filename)
        out_dir = _user_portfolio_dir(em)
        out_dir.mkdir(parents=True, exist_ok=True)
        base = f"{slug}_{stem}.json"
        dest = out_dir / base
        if dest.exists():
            dest = out_dir / f"{slug}_{stem}_{int(time.time())}.json"
        legacy = _legacy_flat_portfolio_path(em)
        if legacy.is_file():
            try:
                legacy.unlink()
            except OSError:
                pass
    else:
        _INSTANCE_DIR.mkdir(exist_ok=True)
        dest = _GUEST_PORTFOLIO_FILE
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return dest


def delete_saved_portfolio(user_email: str | None) -> tuple[bool, str]:
    """Remove this viewer's saved JSON (account folder imports + legacy flat file, or guest file — not env override)."""
    invalidate_cache()
    em = _normalized_email(user_email)
    if em:
        removed_any = False
        udir = _user_portfolio_dir(em)
        if udir.is_dir():
            for p in udir.glob("*.json"):
                try:
                    p.unlink()
                    removed_any = True
                except OSError:
                    pass
        leg = _legacy_flat_portfolio_path(em)
        if leg.is_file():
            try:
                leg.unlink()
                removed_any = True
            except OSError:
                pass
        if removed_any:
            try:
                if udir.is_dir() and not any(udir.iterdir()):
                    udir.rmdir()
            except OSError:
                pass
            return True, "removed_account_file"
        return False, "no_account_file"
    if _GUEST_PORTFOLIO_FILE.is_file():
        _GUEST_PORTFOLIO_FILE.unlink()
        return True, "removed_guest_file"
    return False, "nothing_to_remove"


def migrate_guest_import_to_user(user_email: str, *, user_label_slug: str | None = None) -> bool:
    """After login: if user has no portfolio file but a guest import exists, adopt it."""
    em = _normalized_email(user_email)
    if not em:
        return False
    if path_for_user_portfolio(em) is not None:
        return False
    if not _GUEST_PORTFOLIO_FILE.is_file():
        return False
    _USER_PORTFOLIO_USERS_DIR.mkdir(parents=True, exist_ok=True)
    slug = _sanitize_label_slug(user_label_slug, em)
    out_dir = _user_portfolio_dir(em)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{slug}_guest_import.json"
    if dest.exists():
        dest = out_dir / f"{slug}_guest_import_{int(time.time())}.json"
    shutil.copy2(_GUEST_PORTFOLIO_FILE, dest)
    _GUEST_PORTFOLIO_FILE.unlink()
    invalidate_cache()
    return True


def _source_label(path: Path, user_email: str | None) -> str:
    env = os.environ.get("PORTFOLIO_JSON_PATH", "").strip()
    if env and path.resolve() == Path(env).resolve():
        return "env"
    em = _normalized_email(user_email)
    if em:
        up = path_for_user_portfolio(em)
        if up and path.resolve() == up.resolve():
            return "your_account"
        if path.resolve() == _SAMPLE_PORTFOLIO_FILE.resolve():
            return "demo_sample"
        return "file"
    if path.resolve() == _GUEST_PORTFOLIO_FILE.resolve():
        return "guest_session"
    if path.resolve() == _SAMPLE_PORTFOLIO_FILE.resolve():
        return "demo_sample"
    return "file"


def get_portfolio_status(user_email: str | None = None) -> dict[str, Any]:
    """Lightweight status for UI (no full holdings payload)."""
    path = _resolve_json_path(user_email)
    if path is None:
        return {"loaded": False, "positions": 0, "source": None, "filename": None, "personal": False}
    data = load_portfolio_snapshot(user_email=user_email)
    n = len((data or {}).get("holdings") or [])
    up = path_for_user_portfolio(user_email) if _normalized_email(user_email) else None
    personal = bool(up is not None and path.resolve() == up.resolve())
    return {
        "loaded": True,
        "positions": n,
        "source": _source_label(path, user_email),
        "filename": path.name,
        "personal": personal,
    }


def snapshot_metrics(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("metrics") or {}


def format_snapshot_digest_for_llm(data: dict[str, Any]) -> str:
    m = snapshot_metrics(data)
    cv = float(m.get("current_value") or 0)
    dcp = float(m.get("day_change_percent") or 0)
    pl_pct = float(m.get("profit_loss_percent") or 0)
    n = len(data.get("holdings") or [])
    return (
        "BROKER SNAPSHOT JSON (holdings-level — use for drag/lift/return questions):\n"
        f"- Current value (export): ₹{cv:,.2f}; day change: {dcp:+.4f}%\n"
        f"- Total return on book (export field): {pl_pct:+.2f}%\n"
        f"- Positions: {n}"
    )


def _fmt_inr(x: float) -> str:
    ax = abs(x)
    s = f"₹{ax:,.2f}"
    return f"-{s}" if x < 0 else s


def holding_day_impact_inr(h: dict[str, Any]) -> float:
    cv = float(h.get("current_value") or 0)
    dcp = float(h.get("day_change_percent") or 0)
    return cv * dcp / 100.0


def holding_total_pnl_inr(h: dict[str, Any]) -> float:
    if h.get("profit_loss") is not None:
        return float(h["profit_loss"])
    return float(h.get("pnl") or 0)


def parse_percent_threshold(norm: str, raw: str) -> float | None:
    """Extract a % threshold from e.g. '10% annual', 'over 12.5%'."""
    blob = f"{norm} {raw.lower()}"
    m = re.search(r"(?:at least|more than|over|above|>=|≥)\s*(\d+(?:\.\d+)?)\s*%", blob)
    if m:
        return float(m.group(1))
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*%\s*(?:annual|yearly|return|cagr|pa\b|anual)", blob)
    if m:
        return float(m.group(1))
    m = re.search(r"(?:return|returning)s?\s*(?:of|at|around|about)?\s*(\d+(?:\.\d+)?)\s*%?", blob)
    if m:
        return float(m.group(1))
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*%", blob)
    if m:
        return float(m.group(1))
    return None


def reply_live_day_explain(norm: str, data: dict[str, Any]) -> str:
    """Why is the book red/green today — portfolio-level + contributors."""
    m = snapshot_metrics(data)
    dcp = float(m.get("day_change_percent") or 0)
    dc = float(m.get("day_change") or 0)
    cv = float(m.get("current_value") or 0)
    pl_pct = float(m.get("profit_loss_percent") or 0)
    if dcp < -1e-9:
        tone = "down today"
    elif dcp > 1e-9:
        tone = "up today"
    else:
        tone = "flat today"

    lines: list[str] = [
        f"From your loaded portfolio export: the whole book is {tone} — session move {dcp:+.3f}% "
        f"(about {_fmt_inr(dc)} on ~{_fmt_inr(cv)} current value). "
        f"Labeled total return on this export: {pl_pct:+.2f}% vs cost.",
        "",
    ]

    holdings = [h for h in (data.get("holdings") or []) if float(h.get("current_value") or 0) > 0]
    impacts = [(holding_day_impact_inr(h), h) for h in holdings]
    impacts.sort(key=lambda x: x[0])

    by_sector: dict[str, float] = defaultdict(float)
    for imp, h in impacts:
        sec = str(h.get("sector") or "Unknown")
        by_sector[sec] += imp
    worst_secs = sorted(by_sector.items(), key=lambda x: x[1])[:4]

    if dcp < 0:
        lines.append("Largest negative contributors to today’s mark (approx. position value × day % move):")
        neg = [(imp, h) for imp, h in impacts if imp < 0]
        neg.sort(key=lambda x: x[0])
        if neg:
            for imp, h in neg[:10]:
                sym = h.get("tradingsymbol") or "?"
                dhp = float(h.get("day_change_percent") or 0)
                lines.append(f"   • {sym}: ≈ {_fmt_inr(imp)} ({dhp:+.2f}% today)")
        else:
            lines.append("   • No single position shows a negative day move in this export — check cash/T1 or rounding.")
        lines.append("")
        lines.append("Sectors dragging today the hardest (sum of approx. position day impacts):")
        for sec, s_imp in worst_secs:
            if s_imp < 0:
                lines.append(f"   • {sec}: ≈ {_fmt_inr(s_imp)}")
    elif dcp > 0:
        lines.append("Largest positive contributors to today’s mark:")
        pos = [(imp, h) for imp, h in impacts if imp > 0]
        pos.sort(key=lambda x: -x[0])
        for imp, h in pos[:10]:
            sym = h.get("tradingsymbol") or "?"
            dhp = float(h.get("day_change_percent") or 0)
            lines.append(f"   • {sym}: ≈ {_fmt_inr(imp)} ({dhp:+.2f}% today)")
    else:
        lines.append("Day move is effectively flat vs prior close in this export.")

    lines.append("")
    lines.append("Figures follow your JSON snapshot — not a live exchange feed.")
    return "\n".join(lines)


def reply_live_contributors(norm: str, data: dict[str, Any]) -> str:
    """Stronger / weaker — total P&L (₹) and today’s session impact."""
    holdings = [h for h in (data.get("holdings") or []) if float(h.get("current_value") or 0) > 0]
    weaker_q = any(
        w in norm
        for w in ("weaker", "weak", "drag", "hurt", "worst", "losing", "bottom", "negative")
    )
    stronger_q = any(
        w in norm for w in ("stronger", "strong", "lift", "help", "best", "winning", "top", "positive")
    )
    if not weaker_q and not stronger_q:
        stronger_q = True
        weaker_q = True

    lines: list[str] = []

    if stronger_q or weaker_q:
        by_pnl = sorted(holdings, key=lambda h: holding_total_pnl_inr(h))
        lines.append("Total P&L vs average cost (export fields — main drivers of overall strength):")
        if weaker_q:
            lines.append("Weighing you down the most (lowest ₹ P&L):")
            for h in by_pnl[:8]:
                sym = h.get("tradingsymbol") or "?"
                pnl = holding_total_pnl_inr(h)
                pctp = float(h.get("profit_loss_percent") or 0)
                lines.append(f"   • {sym}: {_fmt_inr(pnl)} ({pctp:+.2f}% on cost)")
        if stronger_q:
            lines.append("Lifting the book the most (highest ₹ P&L):")
            for h in reversed(by_pnl[-8:]):
                sym = h.get("tradingsymbol") or "?"
                pnl = holding_total_pnl_inr(h)
                pctp = float(h.get("profit_loss_percent") or 0)
                lines.append(f"   • {sym}: {_fmt_inr(pnl)} ({pctp:+.2f}% on cost)")
        lines.append("")

    lines.append("Today’s session (approx. ₹ impact from position value × day % move):")
    impacts = [(holding_day_impact_inr(h), h) for h in holdings]
    neg_today = [(i, h) for i, h in impacts if i < 0]
    neg_today.sort(key=lambda x: x[0])
    pos_today = [(i, h) for i, h in impacts if i > 0]
    pos_today.sort(key=lambda x: -x[0])
    lines.append("Dragging today:")
    if neg_today:
        for imp, h in neg_today[:8]:
            sym = h.get("tradingsymbol") or "?"
            dhp = float(h.get("day_change_percent") or 0)
            lines.append(f"   • {sym}: ≈ {_fmt_inr(imp)} ({dhp:+.2f}% today)")
    else:
        lines.append("   • Nothing marked negative for the session in this export.")
    lines.append("Lifting today:")
    if pos_today:
        for imp, h in pos_today[:8]:
            sym = h.get("tradingsymbol") or "?"
            dhp = float(h.get("day_change_percent") or 0)
            lines.append(f"   • {sym}: ≈ {_fmt_inr(imp)} ({dhp:+.2f}% today)")
    else:
        lines.append("   • Nothing marked positive for the session in this export.")

    lines.append("")
    lines.append("Snapshot-only — not investment advice.")
    return "\n".join(lines)


def reply_live_return_filter(norm: str, raw: str, data: dict[str, Any]) -> str:
    """Filter holdings by profit_loss_percent vs a threshold (total return on cost in export)."""
    thresh = parse_percent_threshold(norm, raw)
    if thresh is None:
        thresh = 10.0
    want_below = any(w in norm for w in ("under", "below", "less than", "lower than", "<"))
    annual_ask = any(w in norm for w in ("annual", "yearly", "cagr", "per year", "p.a"))

    holdings = list(data.get("holdings") or [])
    if want_below:
        hits = [h for h in holdings if float(h.get("profit_loss_percent") or 0) < thresh]
        hits.sort(key=lambda h: float(h.get("profit_loss_percent") or 0))
        title = f"Holdings with total return below {thresh:g}% (vs average cost in export)"
    else:
        hits = [h for h in holdings if float(h.get("profit_loss_percent") or 0) >= thresh]
        hits.sort(key=lambda h: -float(h.get("profit_loss_percent") or 0))
        title = f"Holdings with total return at or above {thresh:g}% (vs average cost in export)"

    lines = [title + ":", ""]
    if annual_ask:
        lines.append(
            "Note: this file records total return since average cost (`profit_loss_percent`), "
            "not a computed CAGR. Treat “annual” questions as “total return threshold” unless your export adds CAGR."
        )
        lines.append("")

    if not hits:
        lines.append(f"No positions match that filter in this export ({len(holdings)} rows loaded).")
        return "\n".join(lines)

    for h in hits[:35]:
        sym = h.get("tradingsymbol") or "?"
        pctp = float(h.get("profit_loss_percent") or 0)
        pnl = holding_total_pnl_inr(h)
        cv = float(h.get("current_value") or 0)
        lines.append(f"   • {sym}: {pctp:+.2f}% on cost · {_fmt_inr(pnl)} · ~{_fmt_inr(cv)} value")

    if len(hits) > 35:
        lines.append(f"\n… and {len(hits) - 35} more — narrow the threshold or ask by sector.")

    lines.append("")
    lines.append("Snapshot-only.")
    return "\n".join(lines)


def reply_snapshot_missing() -> str:
    return (
        "I can answer from your portfolio JSON export, but no file is available for this session.\n\n"
        "Sign in and use Import JSON (data is stored per account), or import as a guest, "
        "or set env PORTFOLIO_JSON_PATH to a file on disk."
    )
