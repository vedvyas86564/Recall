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

# Hard ceiling on a single message before it is split internally.
#
# "Messages are atomic" is the right rule for chunk *boundaries* -- it is what
# keeps a question with its reply. But taken literally it is unbounded, and a
# real uv issue body of 87,687 characters (a pasted build log) was emitted as
# one chunk and rejected by Bedrock, which caps input at 50,000.
#
# Splitting inside one long message is a different act from splitting between a
# question and its answer. Trap 3 is about the latter. A message this size is a
# document in its own right, and it needs internal structure for retrieval
# quality regardless of the API limit: one 1024-dimension vector cannot
# meaningfully represent 87k characters, so an unsplit giant is close to
# unretrievable anyway.
#
# Set well below the API ceiling because the limit is on the request payload and
# multi-byte characters cost more than one character each.
OVERSIZE_MESSAGE_CHARS = 6000


def _slack_chunk_metadata(doc, anchor, current):
    channel_id = doc.get("channel_id", "")
    thread_ts = doc.get("thread_ts")
    return {
        "source": "slack",
        "channel": doc.get("channel"),
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        # None when the workspace domain is unconfigured. Downstream must treat
        # a missing url as "cite without a link", never as a reason to
        # synthesize one (spec rule 5).
        "url": slack_permalink(channel_id, anchor["ts"], thread_ts),
    }


def _github_chunk_metadata(doc, anchor, current):
    return {
        "source": "github_issue",
        "repo": doc.get("repo"),
        "issue_number": doc.get("issue_number"),
        "is_pull_request": doc.get("is_pull_request", False),
        "state": doc.get("state"),
        "labels": doc.get("labels", []),
        # Anchored to the first comment in this chunk, so a citation opens the
        # exact comment the text came from rather than the top of a 40-reply
        # thread. Comments carry their own permalink from the fetcher.
        "url": anchor.get("url") or doc.get("url"),
    }


_METADATA_BUILDERS = {
    "slack_export": _slack_chunk_metadata,
    "github_issue": _github_chunk_metadata,
}


def _split_long_message(msg, limit=OVERSIZE_MESSAGE_CHARS):
    """
    Split one oversized message into parts at paragraph, then line, boundaries.

    Each part keeps the original ts, author, and url, so a citation still points
    at the right comment. Only the text differs. Parts after the first drop the
    "timestamp author:" prefix, which belongs to the message rather than to each
    fragment of it.
    """
    if len(msg["line"]) <= limit:
        return [msg]

    text = msg["text"]
    parts = []
    current = ""

    # Paragraphs first; fall back to lines for prose with no blank lines, and to
    # a hard cut only for something like a single enormous minified blob.
    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
            current = ""
        while len(para) > limit:
            cut = para.rfind("\n", 0, limit)
            if cut <= 0:
                cut = limit
            parts.append(para[:cut])
            para = para[cut:].lstrip("\n")
        current = para
    if current:
        parts.append(current)

    out = []
    for i, part in enumerate(parts):
        prefix = f"{msg['ts_display']} {msg['author']}: " if i == 0 else ""
        out.append({
            **msg,
            "text": part,
            "line": f"{prefix}{part}",
            "part": i,
            "part_count": len(parts),
        })
    return out


def chunk_thread(doc, max_chars=MAX_CHARS, overlap_messages=OVERLAP_MESSAGES):
    """
    Pack whole messages into chunks up to max_chars.

    Source-agnostic: a GitHub issue and a Slack thread are the same shape -- an
    opening post and replies, where the answer is often several messages down --
    so both take this path and only the metadata differs.

    Each chunk records the ts range it covers and a link anchored to its first
    message, so a citation points at the part of the thread the text actually
    came from rather than at the thread generally.
    """
    raw_messages = doc.get("messages") or []
    if not raw_messages:
        return []

    # Bound each message before packing, so no single chunk can exceed the
    # embedding API's input limit no matter how long one comment is.
    messages = [part for m in raw_messages for part in _split_long_message(m)]

    build_metadata = _METADATA_BUILDERS.get(doc.get("source"), _slack_chunk_metadata)

    chunks = []
    current = []
    current_len = 0

    def flush():
        nonlocal current, current_len
        if not current:
            return

        text = "\n".join(m["line"] for m in current)
        anchor = current[0]

        metadata = {
            "visibility": doc.get("visibility", "public"),
            "start_ts": anchor["ts"],
            "end_ts": current[-1]["ts"],
            "authors": sorted({m["author"] for m in current}),
            "message_count": len(current),
            "title": doc.get("title"),
            **build_metadata(doc, anchor, current),
        }

        chunks.append({
            "chunk_id": str(uuid.uuid4()),
            "document_id": doc["document_id"],
            "chunk_index": len(chunks),
            "text": text,
            "metadata": metadata,
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


# Retained so existing imports and tests keep working.
chunk_slack_thread = chunk_thread


def chunk_document(doc, max_chars=MAX_CHARS, overlap=None):
    """
    Dispatch on document shape.

    Kept as the entry point so existing callers (ingest.py) keep working. The
    `overlap` parameter is accepted and ignored -- overlap is counted in messages
    now, not characters. Documents carrying a `messages` list take the
    thread-aware path; anything else falls back to the character window.
    """
    if doc.get("messages"):
        return chunk_thread(doc, max_chars=max_chars)
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
