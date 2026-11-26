import json
import re
import sys
import time

from crew import agents, delivery, hc, messages, store
from crew.errors import UsageError
from crew.paths import get_state_dir

MESSAGE_ID = re.compile(r"m-[a-z0-9]{4,16}")
REMOTE_POLL_S = 2.0


def get_replies_path(message_id):
    return get_state_dir() / "replies" / f"{message_id}.jsonl"


def add_reply(message_id, text):
    if not MESSAGE_ID.fullmatch(message_id):
        raise UsageError(f"bad message id {message_id!r}")
    envelope = store.get_json(get_state_dir() / "messages" / f"{message_id}.json")
    all_agents = agents.get_agents()
    sender = next((a for a in all_agents if a["self"]), None)
    sender_address = sender["address"] if sender else "human"
    if envelope is None:
        print(f"note: {message_id} was sent from another machine; its sender collects this reply from here", file=sys.stderr)
    elif envelope["expires_at"] < store.get_now():
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
    original_sender = envelope and next((a for a in all_agents if a["address"] == envelope["from"]), None)
    if original_sender and original_sender["address"] != sender_address:
        label = messages.get_sender_label(sender_address, all_agents)
        wire = f'<crew reply-to="{message_id}" from="{messages.escape_attr(label)}">\n{messages.escape(text)}\n</crew>'
        delivery.deliver(record["id"], wire, [original_sender], sender_address)
    return record


def get_replies(message_id):
    sent_to = [d["to"] for d in delivery.get_deliveries(message_id) if d["status"] == "sent"]
    machines = sorted({agents.get_machine(address) for address in sent_to} - {None})
    remote = [record for machine in machines for record in get_remote_replies(machine, message_id)]
    return [*store.get_records(get_replies_path(message_id)), *remote]


def get_remote_replies(machine, message_id):
    # Agents on another machine reply into that machine's crew state; read it from there over hc.
    text = hc.read_file_on(machine, f".local/state/crew/replies/{message_id}.jsonl") or ""
    records = []
    for line in text.split("\n"):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        records.append({**record, "id": f"{machine}/{record['id']}", "from": f"{machine}/{record['from']}"})
    return records


def wait_for_replies(message_id, expected, timeout_s=600, on_reply=None, poll_s=0.3):
    deadline = time.monotonic() + timeout_s
    poll_s = REMOTE_POLL_S if any(agents.get_machine(address) for address in expected) else poll_s
    seen, replies, missing = set(), [], set(expected)
    while True:
        for record in get_replies(message_id):
            if record["id"] in seen:
                continue
            seen.add(record["id"])
            replies.append(record)
            missing.discard(record["from"])
            if on_reply:
                on_reply(record)
        if not missing or time.monotonic() >= deadline:
            return replies, sorted(missing)
        time.sleep(poll_s)
