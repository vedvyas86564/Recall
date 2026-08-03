"""
Generate the questions a thread answers, and index those.

The idea (doc2query)
--------------------
Dense retrieval matches how a question is *phrased*. Measured on matched pairs,
the same question asked in the corpus's vocabulary versus a newcomer's gets 71.7%
against 9.1% rank-1 accuracy (DECISIONS.md D22), and a lexical retriever cannot
close it because the newcomer's words are frequently absent from the thread
entirely (D23).

So instead of trying to translate the query into the corpus's language at request
time, translate the corpus into the *asker's* language once, at ingest: generate
the questions each thread answers, phrased the way someone with the problem would
phrase them, and embed those alongside the thread. A question that matches the
asker's wording now exists on the index side.

Why per-thread rather than per-chunk
------------------------------------
Recall@1 and Recall@10 are measured over threads -- a reading list and a citation
both resolve to a thread -- so enriching threads targets exactly what is measured.
It is also ~10x cheaper: 392 model calls against 4,149, and roughly 1,600 extra
embeddings against 12,000.

Coverage must be total
----------------------
Every thread gets enriched or none does. Generating questions only for threads
the golden set happens to name would hand those threads a retrieval advantage no
other thread has, and the resulting numbers would measure the sampling rather
than the technique.
"""

import asyncio
import json
import os

from services.db import get_pool

MODEL_ID = os.environ.get("NOVA_LITE_MODEL_ID", "")
QUESTIONS_PER_DOC = int(os.environ.get("DOC2QUERY_N", "5"))

# How much of the thread the model sees. The opening post plus early replies is
# where the problem is stated; later messages drift into implementation detail
# that produces questions nobody would ask cold.
DOC_CHARS = int(os.environ.get("DOC2QUERY_CHARS", "4000"))

_INSTRUCTION = """
You are given a software engineering discussion thread.

Write {n} questions that this thread answers, as they would be asked by someone
who has NOT read it: a new engineer who has hit the problem and is searching for
help.

Rules, in order of importance:

1. Use PLAIN LANGUAGE. Do not reuse the thread's technical terms, command names,
   flags, or jargon. If the thread says "backtracking", a newcomer says "it keeps
   trying loads of versions". If the thread says "max-age header", a newcomer says
   "my package doesn't show up yet". This is the entire point of the task -- a
   question that echoes the thread's own wording is useless.
2. Describe the SYMPTOM or the GOAL, not the mechanism. The asker knows what went
   wrong or what they want, not what causes it or what it is called.
3. Each question must be genuinely answerable from this thread. Do not invent.
4. Vary them. Different angles on the thread, not five rewordings of one.

Return STRICT JSON only, no markdown:
{{"questions": ["...", "..."]}}
""".strip()


def build_request_body(title: str, text: str, n: int = QUESTIONS_PER_DOC) -> dict:
    """Split out so the prompt can be asserted on without a Bedrock client."""
    return {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"text": _INSTRUCTION.format(n=n)},
                    {"text": json.dumps({"title": title, "thread": text[:DOC_CHARS]})},
                ],
            }
        ],
        # Same reasoning as services/nova_extract: this is not a creative task,
        # and a corpus that regenerates differently on every run cannot be
        # measured against itself.
        "inferenceConfig": {"temperature": 0.0, "topP": 1.0},
    }


def generate_questions(title: str, text: str, n: int = QUESTIONS_PER_DOC) -> list[str]:
    from services.nova_extract import invoke_json

    parsed = invoke_json(build_request_body(title, text, n))
    out = parsed.get("questions") or []
    return [q.strip() for q in out if isinstance(q, str) and q.strip()][:n]


async def store_questions(org_id: str, document_id: str, questions: list[str],
                          vectors: list[list[float]]) -> None:
    """Replace this document's generated questions. Idempotent per document."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM doc_queries WHERE org_id = $1::uuid AND document_id = $2",
                org_id, document_id,
            )
            for q, v in zip(questions, vectors):
                await conn.execute(
                    """
                    INSERT INTO doc_queries (org_id, document_id, question, embedding)
                    VALUES ($1::uuid, $2, $3, $4::vector)
                    """,
                    org_id, document_id, q,
                    "[" + ",".join(str(x) for x in v) + "]",
                )
