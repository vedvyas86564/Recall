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

from services.citations import source_ref


def citation_title(meta: dict, chunk: dict) -> str:
    """
    Human-readable label for where a chunk came from.

    Source-aware. This previously hardcoded "Slack" regardless of source, so
    every citation on the GitHub corpus was labelled Slack -- wrong provenance
    shown next to a correct answer, which reads as a fabricated citation even
    though the underlying link was right.
    """
    source = meta.get("source") or chunk.get("source") or ""

    if source == "github_issue":
        repo = meta.get("repo") or "GitHub"
        number = meta.get("issue_number")
        title = meta.get("title") or ""
        label = f"{repo}#{number}" if number else repo
        return f"{label} · {title}" if title else label

    if source in ("slack", "slack_export"):
        channel = meta.get("channel") or chunk.get("channel") or ""
        return f"Slack · #{channel}" if channel else "Slack"

    return meta.get("title") or "Source"


def as_citation(chunk: dict) -> dict:
    meta = chunk.get("metadata", {}) or {}
    return {
        "id": chunk.get("chunk_id", ""),
        "title": citation_title(meta, chunk),
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

    def thread_key(chunk):
        """
        Identity of the source a chunk belongs to, so several chunks from one
        thread collapse to a single citation.

        A long thread routinely contributes many chunks to one answer, and
        listing each separately rendered the same issue seven times in a row --
        noise that reads as seven independent sources when there is only one.
        Falls back to the chunk id when a source cannot be identified, which is
        conservative: it over-counts rather than merging unrelated material.
        """
        return source_ref(chunk) or chunk.get("chunk_id")

    cited_order = []
    for d in decisions:
        real = [cid for cid in (d.get("evidence_chunk_ids") or []) if cid in by_id]
        d["evidence_chunk_ids"] = real

        seen_threads = set()
        citations = []
        for cid in real:
            key = thread_key(by_id[cid])
            if key in seen_threads:
                continue
            seen_threads.add(key)
            citations.append(as_citation(by_id[cid]))
        d["citations"] = citations
        cited_order.extend(real)

    seen = set()
    sources = []
    for cid in cited_order:
        key = thread_key(by_id[cid])
        if key not in seen:
            seen.add(key)
            sources.append(as_citation(by_id[cid]))

    return decisions, sources
