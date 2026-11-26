import json
import os
import secrets
from datetime import datetime, timezone

MAX_LINE_BYTES = 16 * 1024
ID_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"


def get_new_id(prefix):
    return f"{prefix}-" + "".join(secrets.choice(ID_ALPHABET) for _ in range(6))


def get_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def append_record(path, record):
    data = (json.dumps(record, ensure_ascii=False) + "\n").encode()
    if len(data) > MAX_LINE_BYTES:
        raise ValueError(f"record over {MAX_LINE_BYTES} bytes for {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def get_records(path, since=None):
    records, _ = get_records_from(path, 0)
    if since is None:
        return records
    ids = [record.get("id") for record in records]
    return records[ids.index(since) + 1:] if since in ids else records


def get_records_from(path, offset):
    if not path.exists():
        return [], offset
    with open(path, "rb") as file:
        file.seek(offset)
        chunk = file.read()
    complete = chunk[: chunk.rfind(b"\n") + 1]
    records = []
    for line in complete.decode(errors="replace").split("\n"):
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records, offset + len(complete)


def get_json(path):
    if not path.exists():
        return None
    return json.loads(path.read_text())


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)
