"""RAG / hybrid / GraphRAG-style retrieval for FinPilot (maps to literature review).

Literature mapping (coursework instantiation — no FAISS/Neo4j/Redis required):
• §2 RAG — external memory via ranked chunks injected into the LLM prompt.
• §3 GraphRAG — `portfolio_graph.build_graph_context_block`: entity-linked subgraph text from plan+catalog.
• §6 Hybrid retrieval — TF–IDF cosine (dense proxy) + lexical/Jaccard sparse scores, fused with weights.
• §6 Semantic cache — short TTL cache of assembled context string keyed by user + normalized query + intent.
• Enterprise diagrams — pipeline stages exposed as functions (query analysis → hybrid retrieval → context assembly).

Stages: structured filters → corpus → hybrid rank → graph augmentation → merge → (optional) truncate.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

import portfolio_graph
import portfolio_store

# --- Semantic cache (enterprise “semantic cache check” pattern, in-process) ---
_RETRIEVAL_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_TTL_SEC = 90.0
_CACHE_MAX_ENTRIES = 64
_CONTEXT_CHAR_CAP = 9000

_HYBRID_DENSE_WEIGHT = 0.58
_HYBRID_SPARSE_WEIGHT = 0.42


@dataclass
class StructuredRetrievalFilters:
    """Query-builder output: scoped filters (coursework substitute for full OLTP IDs)."""

    user_email: str | None
    intent: str
    asset_class: str | None = None
    date_hint: str | None = None


def extract_query_entities(normalized_query: str, raw_query: str) -> dict[str, Any]:
    """Light entity extraction — symbols plus naive ISO dates."""
    import app as app_module

    symbols = app_module.extract_symbols_from_text(raw_query)
    dates = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", raw_query)
    sectors_guess: list[str] = []
    low = normalized_query.lower()
    for word in ("banking", "it ", " fmcg", "auto", "pharma", "energy"):
        if word.strip() in low:
            sectors_guess.append(word.strip().upper())
    return {
        "symbols": symbols,
        "dates_iso": dates[:3],
        "sector_hints": sectors_guess,
    }


def build_structured_filters(
    user_email: str | None, intent: str, plan: dict[str, Any], entities: dict[str, Any]
) -> StructuredRetrievalFilters:
    asset = None
    if entities.get("sector_hints"):
        asset = entities["sector_hints"][0]
    elif intent == "allocation":
        asset = "allocation"
    return StructuredRetrievalFilters(
        user_email=(user_email.strip().lower() if user_email else None),
        intent=intent,
        asset_class=asset,
        date_hint=entities["dates_iso"][0] if entities.get("dates_iso") else None,
    )


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]{2,}", text.lower())


def expand_query_for_retrieval(normalized_query: str, intent: str) -> str:
    """Light query rewriting / expansion for sparse+dense recall (literature: query rewriting)."""
    parts = [normalized_query]
    if intent in ("pnl",):
        parts.append("profit loss performance day mark pnl")
    if intent in ("holdings",):
        parts.append("positions exemplars sleeves holdings")
    if intent in ("allocation",):
        parts.append("sector weights percent split breakdown")
    if intent in ("value",):
        parts.append("net worth total notional nav")
    if intent in ("risk",):
        parts.append("risk radar volatility profile")
    if intent in ("compare",):
        parts.append("versus peers sector change percent")
    if intent in ("live_day_explain",):
        parts.append("portfolio red green day change contributors drag session")
    if intent in ("live_contributors",):
        parts.append("holdings profit loss stronger weaker drag lift positions")
    if intent in ("live_return_filter",):
        parts.append("return percent yield profit loss percent annual threshold holdings")
    return " ".join(parts)


def _tfidf_dense_scores(query: str, records: list[tuple[str, str]]) -> np.ndarray:
    """Dense retrieval scores: TF–IDF cosine similarity per document (vector-space proxy)."""
    n_docs = len(records)
    if n_docs == 0:
        return np.array([])
    q_tokens = _tokenize(query)
    doc_tokens = [_tokenize(txt) for _, txt in records]
    all_terms: dict[str, int] = {}
    for toks in doc_tokens + [q_tokens]:
        for t in toks:
            if t not in all_terms:
                all_terms[t] = len(all_terms)
    dim = len(all_terms)
    if dim == 0:
        return np.zeros(n_docs)

    df = np.zeros(dim)
    mat = np.zeros((n_docs, dim))
    for i, toks in enumerate(doc_tokens):
        seen = set()
        for t in toks:
            idx = all_terms[t]
            mat[i, idx] += 1.0
            seen.add(idx)
        for idx in seen:
            df[idx] += 1.0

    idf = np.log((n_docs + 1.0) / (df + 1.0)) + 1.0
    mat = mat * idf
    row_norm = np.linalg.norm(mat, axis=1, keepdims=True)
    row_norm[row_norm == 0] = 1.0
    mat = mat / row_norm

    qv = np.zeros(dim)
    for t in q_tokens:
        if t in all_terms:
            qv[all_terms[t]] += 1.0
    qv = qv * idf
    qn = np.linalg.norm(qv)
    if qn == 0:
        return np.zeros(n_docs)
    return (mat @ qv) / qn


def _sparse_lexical_scores(query: str, records: list[tuple[str, str]]) -> np.ndarray:
    """Sparse retrieval: Jaccard on token sets + token overlap hits (keyword channel)."""
    n_docs = len(records)
    if n_docs == 0:
        return np.array([])
    qset = set(_tokenize(query))
    scores = np.zeros(n_docs)
    for i, (_, txt) in enumerate(records):
        tset = set(_tokenize(txt))
        union = qset | tset
        jacc = len(qset & tset) / len(union) if union else 0.0
        bonus = 0.0
        for tok in qset:
            if len(tok) >= 3 and tok.upper() in txt.upper():
                bonus += 0.12
        scores[i] = jacc + min(bonus, 0.48)
    mx = float(scores.max()) if scores.size else 0.0
    if mx > 0:
        scores = scores / mx
    return scores


def _hybrid_fusion_scores(
    dense: np.ndarray, sparse: np.ndarray
) -> np.ndarray:
    """Combine dense + sparse channels (literature: hybrid retrieval)."""
    if dense.size == 0:
        return sparse
    d = dense.copy()
    if d.max() > 0:
        d = d / d.max()
    s = sparse.copy()
    if s.size and s.max() > 0:
        s = s / s.max()
    return _HYBRID_DENSE_WEIGHT * d + _HYBRID_SPARSE_WEIGHT * s


def _tfidf_cosine_rank(
    query: str, records: list[tuple[str, str]], top_k: int = 6
) -> list[tuple[str, str, float]]:
    """Backward-compatible: rank by dense scores only."""
    if not records:
        return []
    scores = _tfidf_dense_scores(query, records)
    idx_order = np.argsort(-scores)
    out: list[tuple[str, str, float]] = []
    for j in idx_order[:top_k]:
        cid = records[int(j)][0]
        txt = records[int(j)][1]
        out.append((cid, txt, float(scores[int(j)])))
    return out


def _cache_key(user_email: str | None, normalized_query: str, intent: str) -> str:
    raw = f"{user_email or ''}|{normalized_query}|{intent}".encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()[:40]


def _cache_get(key: str) -> str | None:
    now = time.time()
    hit = _RETRIEVAL_CACHE.get(key)
    if not hit:
        return None
    exp, text = hit
    if now > exp:
        del _RETRIEVAL_CACHE[key]
        return None
    return text


def _cache_set(key: str, text: str) -> None:
    if len(_RETRIEVAL_CACHE) >= _CACHE_MAX_ENTRIES:
        drop = sorted(_RETRIEVAL_CACHE.items(), key=lambda kv: kv[1][0])[: max(1, _CACHE_MAX_ENTRIES // 4)]
        for k, _ in drop:
            _RETRIEVAL_CACHE.pop(k, None)
    _RETRIEVAL_CACHE[key] = (time.time() + _CACHE_TTL_SEC, text)


def _intent_chunk_bonus(intent: str, chunk_id: str, chunk_text: str) -> float:
    low = chunk_text.lower()
    if intent == "holdings" and ("holding" in low or "exemplar" in low or "sleeve" in low):
        return 0.35
    if intent == "pnl" and ("p&l" in low or "pnl" in low or "mark" in low):
        return 0.35
    if intent == "value" and ("total" in low or "notional" in low or "nav" in low):
        return 0.35
    if intent == "allocation" and ("sleeve" in low or "%" in chunk_text):
        return 0.35
    if intent == "risk" and "risk" in low:
        return 0.35
    if intent.startswith("full") and "portfolio" in low:
        return 0.25
    return 0.0


def assemble_merged_context(
    ranked: list[tuple[str, str, float]], filters: StructuredRetrievalFilters
) -> str:
    """Context assembler: ranked chunks + user metadata line."""
    lines = [
        "RAG context (portfolio-scoped; cite chunk ids mentally — not live web data):",
        f"filters: user_scope={'yes' if filters.user_email else 'anonymous'} intent={filters.intent} "
        f"asset_hint={filters.asset_class or 'any'} date_hint={filters.date_hint or 'latest'}",
        "",
    ]
    for cid, text, score in ranked:
        lines.append(f"[{cid}] (sim≈{score:.3f}) {text}")
    return "\n".join(lines)


def build_full_chunk_corpus(plan: dict[str, Any], user_email: str | None) -> list[tuple[str, str]]:
    """Merge plan-derived chunks + SQLite holdings / txn / EOD chunks."""
    import app as app_module

    records = list(app_module.build_portfolio_chunk_records(plan))
    if user_email:
        records.extend(portfolio_store.fetch_holdings_chunks(user_email))
        records.extend(portfolio_store.fetch_transaction_chunks(user_email))
        records.extend(portfolio_store.fetch_eod_chunks(user_email))
    return records


def agent_hybrid_retrieval_scores(
    expanded_query: str, records: list[tuple[str, str]], intent: str, top_k: int = 8
) -> list[tuple[str, str, float]]:
    """Retrieval agent: hybrid dense + sparse fusion + intent-aware rerank."""
    if not records:
        return []
    dense = _tfidf_dense_scores(expanded_query, records)
    sparse = _sparse_lexical_scores(expanded_query, records)
    fused = _hybrid_fusion_scores(dense, sparse)
    adjusted = fused.copy()
    for i, (cid, txt) in enumerate(records):
        adjusted[i] += _intent_chunk_bonus(intent, cid, txt)
    idx_order = np.argsort(-adjusted)
    out: list[tuple[str, str, float]] = []
    for j in idx_order[:top_k]:
        ji = int(j)
        out.append((records[ji][0], records[ji][1], float(adjusted[ji])))
    return out


def retrieve_and_assemble_context(
    raw_query: str,
    normalized_query: str,
    plan: dict[str, Any],
    user_email: str | None,
    intent: str,
) -> str:
    """Full pipeline: cache check → query analysis → corpus → hybrid retrieval → GraphRAG block → assemble."""
    ck = _cache_key(user_email, normalized_query, intent)
    cached = _cache_get(ck)
    if cached is not None:
        return cached

    entities = extract_query_entities(normalized_query, raw_query)
    filters = build_structured_filters(user_email, intent, plan, entities)
    expanded = expand_query_for_retrieval(normalized_query, intent)
    records = build_full_chunk_corpus(plan, user_email)
    ranked = agent_hybrid_retrieval_scores(expanded, records, intent, top_k=8)
    ranked = ranked[:6]
    graph_block = portfolio_graph.build_graph_context_block(plan, entities)
    rag_body = assemble_merged_context(ranked, filters)
    merged = graph_block + "\n\n" + rag_body
    if len(merged) > _CONTEXT_CHAR_CAP:
        merged = merged[: _CONTEXT_CHAR_CAP] + "\n[…context truncated to token budget…]"
    _cache_set(ck, merged)
    return merged


def pipeline_retrieval_for_llm(
    raw_query: str,
    normalized_query: str,
    plan: dict[str, Any],
    user_email: str | None,
    intent: str,
) -> str:
    """Explicit alias for architecture diagrams (Retrieval → Context builder input)."""
    return retrieve_and_assemble_context(
        raw_query, normalized_query, plan, user_email, intent
    )


def guardrail_filter_llm_reply(reply: str, plan: dict[str, Any]) -> str:
    """Post-LLM guardrail: flag tickers outside catalog + plan exemplars."""
    import app as app_module

    allowed = app_module.portfolio_tickers_from_plan(plan)
    allowed_prefix = {s.replace(".NS", "") for s in allowed}
    allowed_prefix |= {s.split(".")[0] for s in app_module.STOCK_INDEX.keys()}
    extra_aliases = getattr(app_module, "STOCK_ALIASES_EXTRA", {})
    if isinstance(extra_aliases, dict):
        allowed_prefix |= set(extra_aliases.keys())
    noise = frozenset(
        {
            "NS",
            "THE",
            "AND",
            "FOR",
            "YOU",
            "OUR",
            "DAY",
            "NOT",
            "YES",
            "ALL",
            "CAN",
            "ONE",
            "TWO",
            "ANY",
            "USD",
            "INR",
            "IPO",
            "ETF",
            "API",
            "RAG",
            "PNL",
            "NAV",
        }
    )
    hits: list[str] = []
    for m in re.finditer(r"\b([A-Z]{2,}(?:\.NS)?)\b", reply):
        tok = m.group(1)
        base = tok.replace(".NS", "")
        if tok in app_module.STOCK_INDEX:
            continue
        if base in app_module.STOCK_ALIASES or (
            isinstance(extra_aliases, dict) and base in extra_aliases
        ):
            continue
        if base in noise or len(base) < 3:
            continue
        if tok in allowed or base in allowed_prefix:
            continue
        hits.append(tok)
    if not hits:
        return reply
    uniq = ", ".join(sorted(set(hits))[:8])
    return (
        reply.rstrip()
        + "\n\n---\n_Guardrail notice (architecture): flagged symbols not in this app’s catalog/plan — "
        f"{uniq}. Treat as third-party names unless added to your portfolio store._"
    )
