"""
Answer assembly: turning retrieved chunks plus model output into a cited answer.

The rule this module exists to enforce: a citation shown to the user must
resolve to a real retrieved chunk. Two things can violate that, and both are
handled here.

1. Attaching the whole retrieval set as "sources" regardless of what the model
   used. That displays unused chunks as supporting evidence -- spec trap 4,
   ARCHITECTURE.md R1.
2. The model inventing a chunk id. Nova Lite is instructed to cite only supplied
   ids, but instruction-following is not a guarantee, so invented ids are
   dropped rather than trusted.
"""


def as_citation(chunk: dict) -> dict:
    meta = chunk.get("metadata", {}) or {}
    channel = meta.get("channel") or chunk.get("channel") or ""
    return {
        "id": chunk.get("chunk_id", ""),
        "title": f"Slack · #{channel}" if channel else "Slack",
        "excerpt": (chunk.get("text") or "")[:240],
        # None when the chunk cannot be deep-linked. Renderers must show the
        # citation without a link rather than synthesizing one (spec rule 5).
        "url": meta.get("url"),
    }


def attach_citations(decisions: list[dict], retrieved: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Bind each decision to the chunks it actually cited.

    Returns (decisions, sources) where decisions gain a `citations` list and
    `evidence_chunk_ids` is filtered to ids that really exist, and sources is the
    deduplicated union across all decisions -- in first-cited order, so the most
    load-bearing evidence appears first.
    """
    by_id = {c.get("chunk_id"): c for c in retrieved if c.get("chunk_id")}

    cited_order = []
    for d in decisions:
        real = [cid for cid in (d.get("evidence_chunk_ids") or []) if cid in by_id]
        d["evidence_chunk_ids"] = real
        d["citations"] = [as_citation(by_id[cid]) for cid in real]
        cited_order.extend(real)

    seen = set()
    sources = []
    for cid in cited_order:
        if cid not in seen:
            seen.add(cid)
            sources.append(as_citation(by_id[cid]))

    return decisions, sources
