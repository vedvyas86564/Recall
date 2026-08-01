"""
Generate and index newcomer-phrased questions for every thread.

Safe to re-run: each document's questions are replaced, not appended.

    python -m scripts.build_doc2query --dry-run --limit 3   # inspect the output
    python -m scripts.build_doc2query                       # build the whole corpus
"""

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.db import close_pool, get_pool  # noqa: E402

DEFAULT_ORG = "00000000-0000-0000-0000-000000000001"


async def documents(org_id: str, limit: int = 0):
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, title, raw_text, metadata->>'issue_number' AS num
        FROM documents
        WHERE org_id = $1::uuid
        ORDER BY (metadata->>'issue_number')::int NULLS LAST
        """,
        org_id,
    )
    return rows[:limit] if limit else rows


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--org-id", default=os.environ.get("ORG_ID", DEFAULT_ORG))
    ap.add_argument("--dry-run", action="store_true",
                    help="generate and print, but do not embed or store")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=6)
    args = ap.parse_args()

    from services.bedrock_embed import embed_many_texts
    from services.doc2query import generate_questions, store_questions

    docs = await documents(args.org_id, args.limit)
    print(f"{len(docs)} threads to enrich")

    started = time.time()
    sem = asyncio.Semaphore(args.concurrency)
    done = {"n": 0, "q": 0, "failed": 0}

    async def one(row):
        async with sem:
            try:
                questions = await asyncio.to_thread(
                    generate_questions, row["title"] or "", row["raw_text"] or ""
                )
            except Exception as exc:
                done["failed"] += 1
                print(f"  !  #{row['num']}: {type(exc).__name__}: {exc}")
                return
            if not questions:
                done["failed"] += 1
                print(f"  !  #{row['num']}: no questions returned")
                return

            if args.dry_run:
                print(f"\n#{row['num']} — {row['title'][:66]}")
                for q in questions:
                    print(f"    · {q}")
            else:
                vectors = await asyncio.to_thread(
                    embed_many_texts, questions, purpose="GENERIC_INDEX"
                )
                await store_questions(args.org_id, row["id"], questions, vectors)

            done["n"] += 1
            done["q"] += len(questions)
            if not args.dry_run and done["n"] % 25 == 0:
                print(f"  {done['n']}/{len(docs)} threads, {done['q']} questions "
                      f"({time.time() - started:.0f}s)")

    await asyncio.gather(*(one(r) for r in docs))

    print(f"\n{done['n']} threads enriched, {done['q']} questions, "
          f"{done['failed']} failed, {time.time() - started:.0f}s")

    if not args.dry_run:
        pool = await get_pool()
        total = await pool.fetchval(
            "SELECT count(*) FROM doc_queries WHERE org_id = $1::uuid", args.org_id
        )
        covered = await pool.fetchval(
            "SELECT count(DISTINCT document_id) FROM doc_queries WHERE org_id = $1::uuid",
            args.org_id,
        )
        docs_total = await pool.fetchval(
            "SELECT count(*) FROM documents WHERE org_id = $1::uuid", args.org_id
        )
        print(f"stored {total} questions across {covered}/{docs_total} threads")
        if covered < docs_total:
            # Partial coverage silently advantages the enriched threads in every
            # subsequent measurement, so it is reported loudly rather than left
            # to be discovered in the numbers.
            print(f"!  {docs_total - covered} threads have NO generated questions. "
                  "Any eval run now compares enriched against unenriched threads "
                  "and will overstate the technique. Re-run before measuring.")

    await close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
