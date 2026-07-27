import os, json, uuid
from datetime import datetime

# Slack marks these as message subtypes but they carry no retrievable content.
NOISE_SUBTYPES = {
    "channel_join", "channel_leave", "channel_topic", "channel_purpose",
    "channel_name", "channel_archive", "channel_unarchive",
    "bot_add", "bot_remove", "pinned_item", "unpinned_item",
}


def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_channel_index(export_dir: str) -> dict:
    """
    channels.json maps directory names to real Slack channel IDs. Without it we
    have no channel ID, and without a channel ID there is no permalink -- so its
    absence degrades citations rather than breaking ingest.

    A standard Slack export contains public channels only. groups.json (private)
    and dms.json only appear in a full corporate export. See DECISIONS.md D3.
    """
    path = os.path.join(export_dir, "channels.json")
    if not os.path.exists(path):
        return {}

    index = {}
    for c in _load_json(path):
        name = c.get("name")
        if not name:
            continue
        index[name] = {
            "channel_id": c.get("id", ""),
            # Anything in channels.json is public by definition. We read the flag
            # anyway so a full export routed here is caught by the ingest guard
            # rather than silently absorbed.
            "is_private": bool(c.get("is_private", False)),
            "is_archived": bool(c.get("is_archived", False)),
            "purpose": (c.get("purpose") or {}).get("value", ""),
        }
    return index


def _load_user_map(export_dir: str) -> dict:
    users_path = os.path.join(export_dir, "users.json")
    if not os.path.exists(users_path):
        return {}

    user_map = {}
    for u in _load_json(users_path):
        uid = u.get("id")
        if not uid:
            continue
        profile = u.get("profile", {}) or {}
        user_map[uid] = (
            profile.get("display_name")
            or profile.get("real_name")
            or u.get("name")
            or uid
        )
    return user_map


def _detect_private_sources(export_dir: str) -> list[str]:
    """
    Names of any non-public export files present. Ingest refuses to run when this
    is non-empty (DECISIONS.md D3): Phase 1's whole permission story is that the
    corpus cannot contain private content, so this is enforced rather than assumed.
    """
    return [
        f for f in ("groups.json", "dms.json", "mpims.json")
        if os.path.exists(os.path.join(export_dir, f))
    ]


def parse_slack_export(export_dir: str):
    """
    Parses a Slack export folder into normalized "documents", one per thread.

    Each document carries a `messages` list preserving per-message provenance
    (ts, author, text). Chunking packs whole messages from that list, which is
    what keeps a question and its reply in the same chunk -- see chunking.py.

    Output: list of dicts with document_id, text, messages, and metadata.
    """
    channel_index = _load_channel_index(export_dir)
    user_map = _load_user_map(export_dir)

    documents = []

    for entry in sorted(os.listdir(export_dir)):
        chan_dir = os.path.join(export_dir, entry)
        if not os.path.isdir(chan_dir):
            continue
        channel_name = entry
        chan_meta = channel_index.get(channel_name, {})

        messages = []
        for fname in sorted(os.listdir(chan_dir)):
            if fname.endswith(".json"):
                messages.extend(_load_json(os.path.join(chan_dir, fname)))

        # Group into threads. A reply carries thread_ts pointing at its parent;
        # a standalone message is a thread of one.
        threads = {}
        for m in messages:
            text = (m.get("text") or "").strip()
            if not text:
                continue
            if m.get("subtype") in NOISE_SUBTYPES:
                continue
            ts = m.get("ts")
            if not ts:
                continue
            threads.setdefault(m.get("thread_ts") or ts, []).append(m)

        for thread_ts, msgs in threads.items():
            msgs.sort(key=lambda x: float(x.get("ts", "0")))

            parsed_msgs = []
            participants = set()

            for m in msgs:
                uid = m.get("user") or m.get("bot_id") or "unknown"
                author = user_map.get(uid, uid)
                participants.add(author)

                ts = m.get("ts")
                try:
                    ts_str = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
                except (TypeError, ValueError):
                    ts_str = ts

                parsed_msgs.append({
                    "ts": ts,
                    "author": author,
                    "author_id": uid,
                    "ts_display": ts_str,
                    "text": (m.get("text") or "").strip(),
                    # The rendered line is built once here so chunking and the
                    # citation excerpt can never disagree about message text.
                    "line": f"{ts_str} {author}: {(m.get('text') or '').strip()}",
                })

            documents.append({
                "document_id": str(uuid.uuid4()),
                "source": "slack_export",
                "channel": channel_name,
                "channel_id": chan_meta.get("channel_id", ""),
                "visibility": "private" if chan_meta.get("is_private") else "public",
                "thread_ts": thread_ts,
                "participants": sorted(participants),
                "start_ts": msgs[0].get("ts"),
                "end_ts": msgs[-1].get("ts"),
                "title": f"Slack thread in #{channel_name}",
                "messages": parsed_msgs,
                "text": "\n".join(m["line"] for m in parsed_msgs),
                "metadata": {"message_count": len(parsed_msgs)},
            })

    return documents
