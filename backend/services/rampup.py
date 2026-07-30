"""
Ramp-up paths — spec section 3.

Given a topic, return an ORDERED reading list: the threads that explain it,
sequenced foundational-to-specific.

The ordering is the product. A relevance-ranked pile is not a ramp-up path, so
relevance is used only to decide *what* is included; a separate set of signals
decides the *order*. That separation is the whole idea.

Why signal-based rather than graph-based
----------------------------------------
The spec suggests dependency signals -- PR references, import graphs. Measured
against the indexed corpus, that graph is too sparse to order anything: 19
cross-reference edges across 100 threads, and 84 threads with in-degree zero,
which makes them indistinguishable from each other.

The sparsity is an artefact of sampling the top 100 threads by comment count --
most issues they reference fall outside the sample, so the edges point nowhere.
References are still used where they exist, because when present they are the
strongest evidence available; they just cannot carry the ordering alone.

Signals, and what each one is evidence of
-----------------------------------------
- referenced_by: other threads cite this one, so it established something they
  build on. Strongest signal, available for ~16% of threads.
- chronology: earlier discussions establish context that later ones assume.
  Weaker but available for every thread, so it carries most orderings.
- volume: a 170-message thread is load-bearing in a way an 8-message one is not.
  Weakest of the three, and used mainly to break ties.

Every position is attributable to one of these, which is why the reason string
can name the signal that produced it rather than gesturing at relevance.
"""

import re

# Deliberately not tuned. These are stated so the ordering can be argued with,
# and they should be revisited against a golden ramp-up set the way the
# relevance threshold was (DECISIONS.md D12).
W_REFERENCED = 0.45
W_CHRONOLOGY = 0.35
W_VOLUME = 0.20

# GitHub issue references: #1234, GH-1234, or a full issue/pull URL.
_REF_PATTERNS = (
    re.compile(r"(?:^|[\s(\[])#(\d{2,6})\b"),
    re.compile(r"\bGH-(\d{2,6})\b", re.IGNORECASE),
    re.compile(r"github\.com/[\w.-]+/[\w.-]+/(?:issues|pull)/(\d{2,6})"),
)


def extract_references(text: str, exclude: str | None = None) -> set[str]:
    """
    Issue numbers referenced by a thread's text.

    `exclude` drops the thread's own number, which otherwise self-references
    constantly -- GitHub renders the issue number inside its own body and
    participants quote it back.

    Requires a boundary before '#' so that a Markdown heading (`### Summary`) or
    a colour literal (`#fff`) is not read as a reference. Two-digit minimum for
    the same reason.
    """
    if not text:
        return set()

    found: set[str] = set()
    for pattern in _REF_PATTERNS:
        found.update(pattern.findall(text))

    if exclude:
        found.discard(str(exclude))
    return found


def _normalize(values: dict[str, float]) -> dict[str, float]:
    """
    Scale to [0, 1] within the candidate set.

    Normalising against the candidates rather than the whole corpus is
    deliberate: "foundational" means foundational *to what was asked*, so a
    thread's rank should not shift because of material nobody retrieved.

    A set where every value is identical maps to 0.0 rather than 1.0 -- a signal
    that does not discriminate should contribute nothing instead of contributing
    equally to everyone, which would just add a constant.
    """
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: 0.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def score_threads(threads: list[dict]) -> list[dict]:
    """
    Attach a foundational score and its explanation to each candidate thread.

    Each thread needs: id, start_ts, message_count, referenced_by.
    Returns the same dicts with `foundational_score`, `signals`, and `reason`
    added, ordered most-foundational first.
    """
    if not threads:
        return []

    by_id = {t["id"]: t for t in threads}

    refs = _normalize({t["id"]: float(t.get("referenced_by", 0)) for t in threads})
    # Negated so that earlier (smaller timestamp) normalizes toward 1.0.
    ages = _normalize({t["id"]: -float(t.get("start_ts") or 0) for t in threads})
    vols = _normalize({t["id"]: float(t.get("message_count", 0)) for t in threads})

    for tid, thread in by_id.items():
        contributions = {
            "referenced_by": W_REFERENCED * refs[tid],
            "chronology": W_CHRONOLOGY * ages[tid],
            "volume": W_VOLUME * vols[tid],
        }
        thread["foundational_score"] = round(sum(contributions.values()), 4)
        thread["signals"] = {k: round(v, 4) for k, v in contributions.items()}
        thread["reason"] = _reason_for(thread, contributions)

    # Relevance breaks ties, so a tie among ordering signals falls back to the
    # thread that matched the question best rather than to dict order.
    return sorted(
        by_id.values(),
        key=lambda t: (-t["foundational_score"], -(t.get("relevance") or 0.0)),
    )


def _reason_for(thread: dict, contributions: dict[str, float]) -> str:
    """
    One line naming the signal that placed this thread where it is.

    Derived from the score rather than written by a model, so the explanation
    cannot drift from the ordering it claims to explain.
    """
    dominant = max(contributions, key=contributions.get)

    if contributions[dominant] == 0.0:
        return "Included for relevance; no ordering signal distinguishes it."

    if dominant == "referenced_by":
        n = thread.get("referenced_by", 0)
        return f"Foundational — {n} later thread{'s' if n != 1 else ''} reference it."

    if dominant == "chronology":
        return "Among the earliest discussions here, so later threads assume it."

    count = thread.get("message_count", 0)
    return f"Longest debate in this set at {count} messages — most of the reasoning lives here."


def build_reading_list(chunks: list[dict], reference_counts: dict[str, int]) -> list[dict]:
    """
    Collapse retrieved chunks into an ordered reading list of threads.

    Retrieval returns chunks, several of which routinely belong to one thread. A
    reading list is a list of *threads*, so chunks collapse by thread and the
    best-scoring chunk carries that thread's relevance.
    """
    threads: dict[str, dict] = {}

    for chunk in chunks:
        meta = chunk.get("metadata", {}) or {}
        number = str(meta.get("issue_number") or "")
        if not number:
            continue

        existing = threads.get(number)
        relevance = chunk.get("score") or 0.0

        if existing is None:
            # Thread-level totals, not the retrieved chunk's. A chunk carries
            # its own start_ts and message_count, and using those made the
            # ordering read chunk size instead of thread size -- a 157-message
            # thread reported 3. retrieval.py exposes the thread values under
            # thread_* precisely so this cannot happen silently again.
            threads[number] = {
                "id": number,
                "title": meta.get("title") or f"#{number}",
                "url": meta.get("url"),
                "repo": meta.get("repo"),
                "start_ts": float(meta.get("thread_start_ts") or meta.get("start_ts") or 0),
                "message_count": int(
                    meta.get("thread_message_count") or meta.get("message_count") or 0
                ),
                "referenced_by": reference_counts.get(number, 0),
                "relevance": relevance,
                "excerpt": (chunk.get("text") or "")[:240],
            }
        elif relevance > existing["relevance"]:
            existing["relevance"] = relevance
            existing["excerpt"] = (chunk.get("text") or "")[:240]

    return score_threads(list(threads.values()))
