import sys
import time

from crew import agents, delivery, messages, store
from crew.paths import get_state_dir


def get_replies_path(message_id):
    return get_state_dir() / "replies" / f"{message_id}.jsonl"


def add_reply(message_id, text):
    envelope = messages.get_message(message_id)
    all_agents = agents.get_agents()
    sender = next((a for a in all_agents if a["self"]), None)
    sender_address = sender["address"] if sender else "human"
    if envelope["expires_at"] < store.get_now():
        print(f"warning: {message_id} expired at {envelope['expires_at']}; reply recorded anyway", file=sys.stderr)
    reply_id = store.get_new_id("r")
    if len(text.encode()) > messages.MAX_INLINE_BYTES:
        text_path = get_state_dir() / "replies" / f"{message_id}.{reply_id}.txt"
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text(text)
        text = f"(long reply, read it with: cat {text_path})"
    record = {
        "id": reply_id,
        "msg": message_id,
        "from": sender_address,
        "agent": sender["agent"] if sender else None,
        "where": sender["where"] if sender else None,
        "text": text,
        "at": store.get_now(),
    }
    store.append_record(get_replies_path(message_id), record)
    original_sender = next((a for a in all_agents if a["address"] == envelope["from"]), None)
    if original_sender and original_sender["address"] != sender_address:
        label = messages.get_sender_label(sender_address, all_agents)
        wire = f'<crew reply-to="{message_id}" from="{messages.escape_attr(label)}">\n{messages.escape(text)}\n</crew>'
        delivery.deliver(record["id"], wire, [original_sender], sender_address)
    return record


def get_replies(message_id):
    return store.get_records(get_replies_path(message_id))


def wait_for_replies(message_id, expected, timeout_s=600, on_reply=None, poll_s=0.3):
    path = get_replies_path(message_id)
    deadline = time.monotonic() + timeout_s
    replies, offset = [], 0
    missing = set(expected)
    while True:
        new_records, offset = store.get_records_from(path, offset)
        for record in new_records:
            replies.append(record)
            missing.discard(record["from"])
            if on_reply:
                on_reply(record)
        if not missing or time.monotonic() >= deadline:
            return replies, sorted(missing)
        time.sleep(poll_s)
