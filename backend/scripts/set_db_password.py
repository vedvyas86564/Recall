#!/usr/bin/env python3
"""
Put the database password into backend/.env without typing it anywhere visible.

    cd backend && ./venv/bin/python scripts/set_db_password.py

Prompts with hidden input, percent-encodes the password, and substitutes it into
the DATABASE_URL already in .env. The password is never echoed, never printed,
and never passed as a shell argument -- so it stays out of the terminal
scrollback and out of shell history.

Percent-encoding is the point of doing this in a script rather than by hand. An
unencoded '@' terminates the URL's userinfo section, so the connection fails
with "password authentication failed" and sends you hunting for the wrong bug.
"""

import getpass
import re
import sys
from pathlib import Path
from urllib.parse import quote

ENV = Path(__file__).resolve().parent.parent / ".env"
PLACEHOLDER = "[YOUR-PASSWORD]"


def main() -> int:
    if not ENV.exists():
        print(f"No .env at {ENV}. Copy .env.example to .env first.")
        return 1

    content = ENV.read_text()
    match = re.search(r"^DATABASE_URL=(.*)$", content, re.MULTILINE)
    if not match:
        print("No DATABASE_URL line in .env. Add one from the Supabase Connect panel.")
        return 1

    url = match.group(1).strip()
    if PLACEHOLDER not in url:
        if url and "://" in url:
            print("DATABASE_URL already has a password set.")
            print("To replace it, paste a fresh string from Supabase (with the")
            print(f"{PLACEHOLDER} placeholder intact) into .env and re-run this.")
            return 1
        print(f"DATABASE_URL has no {PLACEHOLDER} to fill in.")
        return 1

    print("Paste the database password. It will not be shown as you type.")
    print("(Supabase only reveals it at creation -- reset it in the dashboard if lost.)\n")

    password = getpass.getpass("password: ")
    if not password:
        print("\nNothing entered; .env unchanged.")
        return 1

    confirm = getpass.getpass("re-enter:  ")
    if password != confirm:
        print("\nThe two entries differ; .env unchanged.")
        return 1

    # safe="" so every reserved character is encoded, including @ : / ? # & =
    encoded = quote(password, safe="")
    was_encoded = encoded != password

    ENV.write_text(content.replace(PLACEHOLDER, encoded))

    print("\nWritten to .env.")
    if was_encoded:
        print("Password contained characters that needed percent-encoding; handled.")
    print("\nNext: ./venv/bin/python scripts/check_db.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
