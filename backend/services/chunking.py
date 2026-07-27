"""
Chunking.

The previous implementation sliced document text on a fixed 1200-character
window. Thread grouping upstream was correct, but the window cut through it
blind to message boundaries, so a long thread could be split mid-message --
separating a question from its answer, which is spec trap 3 and the single
worst failure mode for an onboarding corpus.

It looked fine only because every thread in the sample corpus fit inside one
window. See ARCHITECTURE.md R5.

The rule here: a message is atomic. Chunk boundaries fall between messages,
never inside one. A single message larger than the budget gets its own
oversized chunk rather than being cut.
"""

import uuid

from services.citations import slack_permalink

MAX_CHARS = 1600
# Overlap is measured in whole messages, not characters. One trailing message
# repeated into the next chunk preserves the question a reply is answering.
OVERLAP_MESSAGES = 1


def chunk_slack_thread(doc, max_chars=MAX_CHARS, overlap_messages=OVERLAP_MESSAGES):
    """
    Pack whole Slack messages into chunks up to max_chars.

    Each chunk records the ts range it covers and a permalink anchored to its
    first message, so a citation points at the specific part of the thread the
    text came from rather than at the thread generally.
    """
    messages = doc.get("messages") or []
    if not messages:
        return []

    channel_id = doc.get("channel_id", "")
    thread_ts = doc.get("thread_ts")

    chunks = []
    current = []
    current_len = 0

    def flush():
        nonlocal current, current_len
        if not current:
            return

        text = "\n".join(m["line"] for m in current)
        anchor = current[0]

        chunks.append({
            "chunk_id": str(uuid.uuid4()),
            "document_id": doc["document_id"],
            "chunk_index": len(chunks),
            "text": text,
            "metadata": {
                "source": "slack",
                "channel": doc.get("channel"),
                "channel_id": channel_id,
                "visibility": doc.get("visibility", "public"),
                "thread_ts": thread_ts,
                "start_ts": anchor["ts"],
                "end_ts": current[-1]["ts"],
                "authors": sorted({m["author"] for m in current}),
                "message_count": len(current),
                # None when the workspace domain is unconfigured. Downstream must
                # treat a missing url as "cite without a link", never as a reason
                # to synthesize one (spec rule 5).
                "url": slack_permalink(channel_id, anchor["ts"], thread_ts),
            },
        })
        current = []
        current_len = 0

    for msg in messages:
        line_len = len(msg["line"]) + 1  # +1 for the joining newline

        # Close the current chunk before this message would overflow it. A single
        # message longer than the budget still lands whole in its own chunk.
        if current and current_len + line_len > max_chars:
            carry = current[-overlap_messages:] if overlap_messages else []
            flush()
            current = list(carry)
            current_len = sum(len(m["line"]) + 1 for m in current)

        current.append(msg)
        current_len += line_len

    flush()
    return chunks


def chunk_document(doc, max_chars=MAX_CHARS, overlap=None):
    """
    Dispatch on document shape.

    Kept as the entry point so existing callers (ingest.py) keep working. The
    `overlap` parameter is accepted and ignored -- overlap is counted in messages
    now, not characters. Documents carrying a `messages` list take the
    thread-aware path; anything else falls back to the character window.
    """
    if doc.get("messages"):
        return chunk_slack_thread(doc, max_chars=max_chars)
    return _chunk_by_chars(doc, max_chars=max_chars)


def _chunk_by_chars(doc, max_chars=MAX_CHARS, overlap=150):
    """
    Fixed-window fallback for documents with no message structure.

    Retained only for sources that genuinely have no natural boundary. Slack must
    not reach this path; if it does, thread integrity is silently lost.
    """
    text = doc["text"]
    chunks = []
    start = 0

    while start < len(text):
        end = min(len(text), start + max_chars)
        chunk_text = text[start:end].strip()

        if chunk_text:
            chunks.append({
                "chunk_id": str(uuid.uuid4()),
                "document_id": doc["document_id"],
                "chunk_index": len(chunks),
                "text": chunk_text,
                "metadata": {
                    "source": doc.get("source", "unknown"),
                    "channel": doc.get("channel"),
                    "visibility": doc.get("visibility", "public"),
                    "thread_ts": doc.get("thread_ts"),
                    "url": None,
                },
            })

        if end == len(text):
            break
        start = end - overlap

    return chunks
