import asyncio
import json

from services.bedrock_embed import embed_many_texts
from services.chunking import chunk_document
from services.db import get_pool
from services.slack_export import _detect_private_sources, parse_slack_export


class PrivateContentError(RuntimeError):
    """Raised when an export contains non-public channels."""


def slack_document_external_id(doc: dict) -> str:
    """
    Stable identity for a Slack thread, so re-ingesting updates rather than
    duplicating (ARCHITECTURE.md R8).

    Prefers the channel ID, which is immutable. Falls back to the directory name
    when channels.json is absent -- weaker, because renaming a channel then
    orphans its old rows, but still stable across ordinary re-runs.
    """
    channel_key = doc.get("channel_id") or doc.get("channel") or "unknown"
    return f"{channel_key}:{doc.get('thread_ts')}"


async def ingest_slack_export(export_dir: str, org_id: str) -> dict:
    """
    Parse a Slack export, chunk it, embed it, and upsert into Postgres.

    Idempotent: running twice over an unchanged export leaves the corpus
    identical. Previously every run minted fresh UUIDs and INSERTed, so a second
    run silently doubled the corpus and filled top-k with duplicates.
    """
    # DECISIONS.md D3: Phase 1's entire permission story is that the corpus
    # cannot contain private content. Enforced, not assumed -- refuse rather
    # than quietly absorbing a full corporate export.
    private = _detect_private_sources(export_dir)
    if private:
        raise PrivateContentError(
            f"Export contains non-public sources: {', '.join(private)}. "
            "Phase 1 indexes public channels only (DECISIONS.md D3). "
            "Remove these files or supply a standard public-channel export."
        )

    pool = await get_pool()
    docs = parse_slack_export(export_dir)

    # Chunk everything first so embedding can run as one wide concurrent batch
    # rather than a serial call per chunk inside a per-document loop.
    all_chunks = []
    doc_chunks = {}
    for doc in docs:
        if doc.get("visibility") != "public":
            raise PrivateContentError(
                f"Refusing to ingest non-public channel #{doc.get('channel')}."
            )
        chunks = chunk_document(doc)
        doc_chunks[doc["document_id"]] = chunks
        all_chunks.extend(chunks)

    if not all_chunks:
        return {"documents": 0, "chunks": 0, "embeddings": 0, "skipped_unchanged": 0}

    vectors = await asyncio.to_thread(
        embed_many_texts,
        [c["text"] for c in all_chunks],
        purpose="GENERIC_INDEX",
    )
    vec_by_chunk = {c["chunk_id"]: v for c, v in zip(all_chunks, vectors)}

    documents = chunks_written = embeddings_written = 0

    for doc in docs:
        doc_external = slack_document_external_id(doc)

        async with pool.acquire() as conn:
            async with conn.transaction():
                doc_row = await conn.fetchrow(
                    """
                    INSERT INTO documents
                        (org_id, source, external_id, title, raw_text, visibility, metadata, updated_at)
                    VALUES ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb, now())
                    ON CONFLICT (org_id, source, external_id) DO UPDATE SET
                        title      = EXCLUDED.title,
                        raw_text   = EXCLUDED.raw_text,
                        visibility = EXCLUDED.visibility,
                        metadata   = EXCLUDED.metadata,
                        updated_at = now()
                    RETURNING id
                    """,
                    org_id,
                    doc.get("source", "slack_export"),
                    doc_external,
                    doc.get("title", ""),
                    doc.get("text", ""),
                    doc.get("visibility", "public"),
                    json.dumps({
                        "channel": doc.get("channel"),
                        "channel_id": doc.get("channel_id"),
                        "thread_ts": doc.get("thread_ts"),
                        "participants": doc.get("participants"),
                        "start_ts": doc.get("start_ts"),
                        "end_ts": doc.get("end_ts"),
                        "message_count": doc.get("metadata", {}).get("message_count"),
                    }),
                )
                doc_id = doc_row["id"]
                documents += 1

                chunks = doc_chunks[doc["document_id"]]
                keep_external_ids = [f"{doc_external}:{c['chunk_index']}" for c in chunks]

                # An edited thread can produce fewer chunks than before. Without
                # this, the surplus rows from the previous run survive as
                # orphans and stay retrievable forever (R8, and the "what happens
                # to an edited message" gap in ARCHITECTURE.md section 2).
                await conn.execute(
                    """
                    DELETE FROM chunks
                    WHERE org_id = $1::uuid
                      AND document_id = $2
                      AND NOT (external_id = ANY($3::text[]))
                    """,
                    org_id,
                    doc_id,
                    keep_external_ids,
                )

                for chunk in chunks:
                    chunk_external = f"{doc_external}:{chunk['chunk_index']}"
                    chunk_row = await conn.fetchrow(
                        """
                        INSERT INTO chunks
                            (org_id, document_id, external_id, chunk_index, text, visibility, metadata)
                        VALUES ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb)
                        ON CONFLICT (org_id, external_id) DO UPDATE SET
                            document_id = EXCLUDED.document_id,
                            chunk_index = EXCLUDED.chunk_index,
                            text        = EXCLUDED.text,
                            visibility  = EXCLUDED.visibility,
                            metadata    = EXCLUDED.metadata
                        RETURNING id, (xmax = 0) AS inserted
                        """,
                        org_id,
                        doc_id,
                        chunk_external,
                        chunk["chunk_index"],
                        chunk["text"],
                        chunk["metadata"].get("visibility", "public"),
                        json.dumps(chunk.get("metadata", {})),
                    )
                    chunks_written += 1

                    vec = vec_by_chunk[chunk["chunk_id"]]
                    vec_literal = "[" + ",".join(str(v) for v in vec) + "]"
                    await conn.execute(
                        """
                        INSERT INTO embeddings (chunk_id, org_id, embedding)
                        VALUES ($1, $2::uuid, $3::vector)
                        ON CONFLICT (chunk_id) DO UPDATE SET
                            embedding = EXCLUDED.embedding,
                            created_at = now()
                        """,
                        chunk_row["id"],
                        org_id,
                        vec_literal,
                    )
                    embeddings_written += 1

    return {
        "documents": documents,
        "chunks": chunks_written,
        "embeddings": embeddings_written,
    }
