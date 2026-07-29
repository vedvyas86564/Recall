"""
GitHub issue and PR discussion threads as a corpus.

Normalized into the same document shape parse_slack_export produces -- a
`messages` list of {ts, author, text, line} -- so the thread-aware chunker
applies unchanged. An issue is structurally a Slack thread: an opening post and
replies, where the answer is frequently three comments down.

See DECISIONS.md D8 for why this is the Phase 1 corpus.
"""

import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone

import httpx

from services.citations import github_issue_url

API = "https://api.github.com"

# The search API returns at most 1000 results (10 pages of 100) regardless of
# how many match. Beyond that the query has to be narrowed rather than paged.
SEARCH_MAX_PAGES = 10

# Backstop on comment pagination: 10 pages is 1000 comments, past any real
# thread. Prevents a pathological thread from consuming the rate limit alone.
COMMENT_MAX_PAGES = 10

# Bot chatter carries no retrievable answer and dilutes retrieval. Matched on
# the API's own author_association/type rather than by name where possible.
BOT_SUFFIXES = ("[bot]",)
KNOWN_BOTS = {"codecov", "dependabot", "github-actions", "renovate", "pre-commit-ci"}


def _token() -> str:
    """
    Prefer an explicit token; fall back to the gh CLI's.

    Unauthenticated requests are capped at 60/hour, which will not fetch a
    corpus. Authenticated is 5000/hour.
    """
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        return tok
    try:
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=15
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _is_bot(user: dict) -> bool:
    login = (user or {}).get("login", "")
    if (user or {}).get("type") == "Bot":
        return True
    return login.lower() in KNOWN_BOTS or login.endswith(BOT_SUFFIXES)


def _clean(text: str) -> str:
    """
    Strip quoted replies and collapse whitespace.

    Quoted text is the previous message repeated, so leaving it in means the
    same content is embedded several times across a thread and crowds out
    distinct material in top-k.
    """
    if not text:
        return ""
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _ts(iso: str) -> str:
    """ISO 8601 to a Slack-style epoch string, so both sources sort alike."""
    try:
        return f"{datetime.fromisoformat(iso.replace('Z', '+00:00')).timestamp():.6f}"
    except (TypeError, ValueError):
        return "0.000000"


def _display(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return iso or ""


class GitHubClient:
    def __init__(self, token: str = None, timeout: float = 30.0):
        self.token = token if token is not None else _token()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self._client = httpx.Client(headers=headers, timeout=timeout)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def get(self, path: str, **params) -> list | dict:
        """
        GET with retry on secondary rate limits.

        GitHub answers abuse detection with 403 plus Retry-After rather than
        429, so a naive client sees a permission error and gives up on a corpus
        that was merely being fetched too fast.
        """
        url = path if path.startswith("http") else f"{API}{path}"

        for attempt in range(5):
            r = self._client.get(url, params=params)

            if r.status_code in (403, 429):
                retry_after = r.headers.get("Retry-After")
                remaining = r.headers.get("X-RateLimit-Remaining")
                if retry_after:
                    time.sleep(min(int(retry_after), 60))
                    continue
                if remaining == "0":
                    reset = int(r.headers.get("X-RateLimit-Reset", "0"))
                    wait = max(0, reset - int(time.time())) + 1
                    raise RuntimeError(
                        f"GitHub rate limit exhausted; resets in {wait}s. "
                        "Set GITHUB_TOKEN or run `gh auth login`."
                    )
                time.sleep(2 ** attempt)
                continue

            r.raise_for_status()
            return r.json()

        raise RuntimeError(f"GitHub kept rate-limiting {url} after 5 attempts")


def fetch_issue_threads(
    repo: str,
    min_comments: int = 3,
    max_threads: int = 500,
    state: str = "closed",
    client: GitHubClient = None,
    progress=None,
) -> list[dict]:
    """
    Fetch issue/PR threads with real discussion on them.

    min_comments defaults to 3 because a thread with fewer is usually a report
    and an acknowledgement -- it adds volume without adding answers, and the
    point of this corpus is questions that got answered.

    state defaults to closed: a closed thread usually reached a conclusion,
    which is what makes it worth retrieving.
    """
    owns_client = client is None
    client = client or GitHubClient()

    try:
        threads = []
        page = 1
        scanned = skipped_bot = skipped_short = 0

        # Filter server-side via the search API rather than paging the issues
        # list and discarding most of it. Listing scanned 466 issues to find 12
        # qualifying ones -- a 2.6% yield that would need ~19,000 scanned for a
        # 500-thread corpus, far past any sane page cap.
        #
        # Note the issues list endpoint accepts sort=comments but does not
        # honour it (an observed page: 32, 3, 170, 156, 11, 19, ...), so
        # ordering could not be used to stop early either. Search does honour it.
        query = f"repo:{repo} type:issue comments:>={min_comments}"
        if state in ("open", "closed"):
            query += f" state:{state}"

        while len(threads) < max_threads and page <= SEARCH_MAX_PAGES:
            result = client.get(
                "/search/issues",
                q=query,
                sort="comments",
                order="desc",
                per_page=100,
                page=page,
            )
            batch = result.get("items", []) if isinstance(result, dict) else []
            if not batch:
                break

            for issue in batch:
                if len(threads) >= max_threads:
                    break
                scanned += 1

                if _is_bot(issue.get("user") or {}):
                    skipped_bot += 1
                    continue

                doc = _build_thread(client, repo, issue)
                if doc is None:
                    skipped_short += 1
                    continue

                threads.append(doc)
                if progress:
                    progress(len(threads), max_threads)

            page += 1

        # Report what was dropped. A corpus that is quietly smaller than asked
        # for reads as "indexed everything" when reviewing eval numbers later.
        print(
            f"fetched {len(threads)} threads from {repo} "
            f"(matched {scanned} with >={min_comments} comments; skipped "
            f"{skipped_bot} bot-authored, {skipped_short} with no discussion)"
        )
        if page > SEARCH_MAX_PAGES and len(threads) < max_threads:
            print(
                f"!  hit the search API's {SEARCH_MAX_PAGES * 100}-result ceiling; "
                "narrow the query (raise min_comments) to reach deeper threads"
            )

        return _finish(threads, owns_client, client)

    except Exception:
        if owns_client:
            client.close()
        raise


def _finish(threads, owns_client, client):
    if owns_client:
        client.close()
    return threads


def _all_comments(client: GitHubClient, repo: str, number: int) -> list[dict]:
    """
    Every comment on a thread, following pagination.

    per_page maxes at 100, so a single request silently truncates any longer
    discussion -- and the longest threads are the most valuable ones here. An
    earlier version did exactly that and every thread came back at exactly 101
    messages, which is the shape of a cap rather than of real data.
    """
    comments = []
    page = 1
    while page <= COMMENT_MAX_PAGES:
        batch = client.get(
            f"/repos/{repo}/issues/{number}/comments", per_page=100, page=page
        )
        if not batch:
            break
        comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return comments


def _build_thread(client: GitHubClient, repo: str, issue: dict) -> dict | None:
    number = issue["number"]
    is_pr = "pull_request" in issue

    messages = []
    participants = set()

    body = _clean(issue.get("body") or "")
    if body:
        author = (issue.get("user") or {}).get("login", "unknown")
        participants.add(author)
        created = issue.get("created_at", "")
        messages.append({
            "ts": _ts(created),
            "author": author,
            "author_id": author,
            "ts_display": _display(created),
            "text": body,
            "comment_id": None,
            "url": github_issue_url(repo, number),
            "line": f"{_display(created)} {author}: {body}",
        })

    for c in _all_comments(client, repo, number):
        if _is_bot(c.get("user") or {}):
            continue
        text = _clean(c.get("body") or "")
        if not text:
            continue

        author = (c.get("user") or {}).get("login", "unknown")
        participants.add(author)
        created = c.get("created_at", "")
        messages.append({
            "ts": _ts(created),
            "author": author,
            "author_id": author,
            "ts_display": _display(created),
            "text": text,
            "comment_id": c.get("id"),
            "url": github_issue_url(repo, number, c.get("id")),
            "line": f"{_display(created)} {author}: {text}",
        })

    # A thread with a single message is a statement, not a discussion. It cannot
    # demonstrate the question-and-answer retrieval this corpus exists to test.
    if len(messages) < 2:
        return None

    messages.sort(key=lambda m: float(m["ts"]))

    return {
        "document_id": str(uuid.uuid4()),
        "source": "github_issue",
        "repo": repo,
        "issue_number": number,
        "is_pull_request": is_pr,
        # Public repository, so every thread is public by construction. The
        # field exists because ingest enforces D3's public-only guarantee on it.
        "visibility": "public",
        "title": issue.get("title", "") or f"{repo}#{number}",
        "participants": sorted(participants),
        "start_ts": messages[0]["ts"],
        "end_ts": messages[-1]["ts"],
        "state": issue.get("state", ""),
        "labels": [l.get("name", "") for l in (issue.get("labels") or [])],
        "url": github_issue_url(repo, number),
        "messages": messages,
        "text": "\n".join(m["line"] for m in messages),
        "metadata": {"message_count": len(messages)},
    }
