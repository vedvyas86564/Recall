#!/usr/bin/env python3
"""
Apply backend/schema.sql to the configured database.

    cd backend && ./venv/bin/python scripts/apply_schema.py

An alternative to pasting into the Supabase SQL Editor. schema.sql is written to
be idempotent -- every statement is IF NOT EXISTS -- so re-running is safe and
is the normal way to pick up schema changes.

Credentials are masked in all output, including errors.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import asyncpg  # noqa: E402

SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"


def mask(url: str) -> str:
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", url or "")


async def main() -> int:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is not set in backend/.env")
        return 1
    if not SCHEMA.exists():
        print(f"No schema at {SCHEMA}")
        return 1

    print(f"applying {SCHEMA.name} to {mask(url)}")

    try:
        conn = await asyncpg.connect(url, timeout=30)
    except Exception as e:
        print(f"\nconnection FAILED  {type(e).__name__}: {e}")
        return 1

    try:
        # No parameters, so asyncpg uses the simple query protocol and runs the
        # whole file as one multi-statement batch.
        await conn.execute(SCHEMA.read_text())
        print("schema applied")

        tables = await conn.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
        print("\ntables now present:")
        for t in tables:
            count = await conn.fetchval(f"SELECT count(*) FROM {t['table_name']}")
            print(f"  {t['table_name']:<14} {count:>8} rows")
        return 0

    except asyncpg.InsufficientPrivilegeError as e:
        print(f"\nFAILED  {e}")
        print(
            "\n  Enabling the vector extension may need the dashboard:\n"
            "  Database -> Extensions -> search 'vector' -> enable, then re-run."
        )
        return 1
    except Exception as e:
        print(f"\nFAILED  {type(e).__name__}: {e}")
        return 1
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
