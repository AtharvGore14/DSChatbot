"""In-process portfolio knowledge graph for GraphRAG-style context (literature §3–4).

No Neo4j: adjacency is derived from the session plan + static STOCKS catalog so retrieval can
surface relationships (same sector, sleeve membership) alongside flat chunks.
"""

from __future__ import annotations

from typing import Any


def build_graph_context_block(plan: dict[str, Any], entities: dict[str, Any]) -> str:
    """Structured subgraph summary: entities → sleeve / sector → peer symbols (1 hop)."""
    import app as app_module

    lines: list[str] = [
        "GRAPH SUBGRAPH (relationship-aware context; not external market data):",
    ]

    alloc = plan.get("allocation") or []
    sector_to_exemplars: dict[str, list[str]] = {}
    for row in alloc:
        sec = str(row.get("sector") or "")
        exs = row.get("exemplars") or []
        syms = [str(x.get("symbol", "")).strip() for x in exs if x.get("symbol")]
        if sec:
            sector_to_exemplars[sec] = syms

    for sec, syms in sector_to_exemplars.items():
        if syms:
            short = ", ".join(s.replace(".NS", "") for s in syms[:8])
            lines.append(f"  • sleeve[{sec}] exemplars → {short}")

    syms_q = entities.get("symbols") or []
    for sym in syms_q[:8]:
        if sym not in app_module.STOCK_INDEX:
            continue
        row = app_module.STOCK_INDEX[sym]
        sec = app_module.sector_for_stock(row)
        peers = [
            x["symbol"]
            for x in app_module.STOCKS
            if app_module.sector_for_stock(x) == sec and x["symbol"] != sym
        ]
        peer_short = ", ".join(p.replace(".NS", "") for p in peers[:6])
        lines.append(
            f"  • {sym.replace('.NS', '')} —sector[{sec}]— peers_in_catalog: {peer_short or 'n/a'}"
        )

    if len(lines) <= 1:
        lines.append("  • (no entity-linked edges for this query — see sleeve rows above if any.)")

    return "\n".join(lines)
