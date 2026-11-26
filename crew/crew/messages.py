from datetime import datetime, timedelta, timezone

from crew import agents, delivery, store
from crew.errors import NotFoundError
from crew.paths import get_state_dir

MAX_INLINE_BYTES = 8 * 1024


def send_message(text, targets, *, kind="message", wants_reply=False, ttl_s=600):
    sender = agents.get_sender()
    message_id = store.get_new_id("m")
    messages_dir = get_state_dir() / "messages"
    body = text
    if len(text.encode()) > MAX_INLINE_BYTES:
        text_path = messages_dir / f"{message_id}.txt"
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text(text)
        body = f"(long message, read it with: cat {text_path})"
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_s)
    envelope = {
        "id": message_id,
        "from": sender,
        "from_label": get_sender_label(sender, targets),
        "to": [t["address"] for t in targets],
        "text": body,
        "kind": kind,
        "reply": wants_reply,
        "created_at": store.get_now(),
        "expires_at": expires_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    store.write_json(messages_dir / f"{message_id}.json", envelope)
    deliveries = delivery.deliver(message_id, to_wire(envelope), targets, sender)
    return {"id": message_id, "envelope": envelope, "deliveries": deliveries}


def get_message(message_id):
    envelope = store.get_json(get_state_dir() / "messages" / f"{message_id}.json")
    if envelope is None:
        raise NotFoundError(f"no message {message_id!r}")
    return envelope


def get_sender_label(sender, known_agents=()):
    if sender == "human":
        return "human"
    match = next((a for a in known_agents if a["address"] == sender), None)
    if match is None:
        match = next((a for a in agents.get_agents() if a["address"] == sender), {})
    return " ".join(part for part in (sender, match.get("name") or match.get("where")) if part)


def to_wire(envelope):
    text = escape(envelope["text"])
    sender = escape_attr(envelope["from_label"])
    message_id = envelope["id"]
    if not envelope["reply"]:
        return f'<crew msg="{message_id}" from="{sender}">\n{text}\n(no reply needed)\n</crew>'
    reply = f"crew reply {message_id} '<your answer>'"
    how = f'(Answer by running: crew reply {message_id} "<your answer>". Text you write in chat does not reach the sender.)'
    return f'<crew msg="{message_id}" from="{sender}" reply="{reply}">\n{text}\n{how}\n</crew>'


def escape(text):
    return text.replace("<", "‹").replace(">", "›")


def escape_attr(text):
    return escape(text).replace('"', "'")
