"""
Citation link construction.

Spec rule 5: no fabricated citations. Every function here returns None rather
than a guess when it lacks the parts needed to build a real, resolvable URL.
An answer with no link is acceptable; an answer with a wrong one is not.
"""

import os
import re

# Slack permalinks need the workspace domain, which a standard export does not
# reliably contain. It is configuration, not derivable data. When it is unset we
# emit no Slack links at all rather than guessing at a subdomain.
SLACK_WORKSPACE_DOMAIN = os.environ.get("SLACK_WORKSPACE_DOMAIN", "").strip()

_TS_RE = re.compile(r"^\d{10}\.\d{6}$")
_CHANNEL_ID_RE = re.compile(r"^[CGD][A-Z0-9]{6,}$")


def slack_permalink(channel_id: str, ts: str, thread_ts: str | None = None) -> str | None:
    """
    https://<workspace>.slack.com/archives/<C…>/p<ts with the dot removed>

    Returns None unless the workspace domain is configured AND the channel id and
    timestamp both look like real Slack values. A malformed id would produce a
    plausible-looking URL that 404s, which is exactly the failure rule 5 forbids.
    """
    if not SLACK_WORKSPACE_DOMAIN:
        return None
    if not channel_id or not _CHANNEL_ID_RE.match(channel_id):
        return None
    if not ts or not _TS_RE.match(ts):
        return None

    link = f"https://{SLACK_WORKSPACE_DOMAIN}.slack.com/archives/{channel_id}/p{ts.replace('.', '')}"

    # A reply needs the parent thread ts to deep-link into the thread rather than
    # the channel. Only append it when it differs from the message's own ts.
    if thread_ts and thread_ts != ts and _TS_RE.match(thread_ts):
        link += f"?thread_ts={thread_ts}&cid={channel_id}"
    return link


def github_blob_url(
    repo: str,
    ref: str,
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str | None:
    """
    https://github.com/<owner/repo>/blob/<ref>/<path>#L<start>-L<end>

    `ref` should be a commit SHA, not a branch name — a branch link rots the
    moment the file changes, and a citation that silently points at different
    content than the one indexed is a wrong citation.
    """
    if not repo or "/" not in repo or not ref or not path:
        return None

    url = f"https://github.com/{repo}/blob/{ref}/{path.lstrip('/')}"
    if start_line:
        url += f"#L{start_line}"
        if end_line and end_line != start_line:
            url += f"-L{end_line}"
    return url
