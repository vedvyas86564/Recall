#!/usr/bin/env python3
"""
Verify the database is reachable and correctly provisioned.

Run after setting DATABASE_URL and applying schema.sql:

    cd backend && ./venv/bin/python scripts/check_db.py

Never prints the connection string or any credential. Everything is reported
against a masked form, so the output is safe to paste into a chat or an issue.
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

REQUIRED_TABLES = ["documents", "chunks", "embeddings", "abstentions", "jobs"]


def mask(url: str) -> str:
    """postgresql://user:secret@host:5432/db -> postgresql://user:***@host:5432/db"""
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", url or "")


def hint_for(err: Exception, url: str) -> str:
    text = f"{type(err).__name__}: {err}".lower()

    if "duplicateprepared" in text or "prepared statement" in text:
        return (
            "This is the transaction pooler (port 6543). asyncpg needs prepared\n"
            "  statements, which pgbouncer rejects in transaction mode.\n"
            "  Switch to the Session pooler (port 5432) in the Supabase Connect panel."
        )
    if "password authentication failed" in text:
        return (
            "Wrong password, or special characters that need percent-encoding.\n"
            "  A '@' in the password must be written %40, '#' as %23, and so on --\n"
            "  otherwise it terminates the userinfo section and the URL parses wrong."
        )
    if "does not exist" in text and "database" in text:
        return "Database name is wrong; Supabase expects /postgres at the end."
    if "network is unreachable" in text or "connection refused" in text:
        if ":5432" in url and "pooler" not in url:
            return (
                "Direct connections are IPv6-only on Supabase. If this network is\n"
                "  IPv4-only, use the Session pooler string instead."
            )
        return "Host unreachable. Check the host and that the project is not paused."
    if "timeout" in text:
        return "Connection timed out -- likely a firewall between here and Supabase."
    return "Copy the string fresh from the Supabase Connect panel."


async def main() -> int:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is not set in backend/.env")
        return 1

    print(f"connecting to {mask(url)}")

    if ":6543" in url:
        print("!  port 6543 is the transaction pooler; asyncpg needs 5432 (session or direct)")

    try:
        conn = await asyncpg.connect(url, timeout=20)
    except Exception as e:
        print(f"\nFAILED  {type(e).__name__}: {e}")
        print(f"\n  {hint_for(e, url)}")
        return 1

    try:
        version = await conn.fetchval("SHOW server_version")
        print(f"connected   Postgres {version}")

        has_vector = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )
        print(f"pgvector    {'enabled' if has_vector else 'MISSING -- run schema.sql'}")

        print("\ntables:")
        missing = []
        for table in REQUIRED_TABLES:
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = $1)",
                table,
            )
            if exists:
                count = await conn.fetchval(f"SELECT count(*) FROM {table}")
                print(f"  {table:<14} {count:>8} rows")
            else:
                missing.append(table)
                print(f"  {table:<14}   MISSING")

        if missing:
            print(f"\n  Run backend/schema.sql in the Supabase SQL Editor "
                  f"({len(missing)} table(s) absent).")
            return 1

        # lists is left untuned until the corpus is loaded, so report what the
        # row count implies rather than assuming the schema default is right.
        rows = await conn.fetchval("SELECT count(*) FROM embeddings")
        has_index = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_indexes "
            "WHERE tablename = 'embeddings' AND indexdef ILIKE '%ivfflat%')"
        )
        print(f"\nvector index: {'present' if has_index else 'none (sequential scan)'}")
        if rows == 0:
            print("  no embeddings yet -- sequential scan is correct until the corpus lands")
        elif not has_index and rows > 5000:
            print(f"  {rows} rows: worth creating the index now, lists ~= {max(1, rows // 1000)}")
        elif not has_index:
            print(f"  {rows} rows: still small enough that exact search beats an index")

        if not has_vector:
            return 1

        print("\nready")
        return 0

    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
