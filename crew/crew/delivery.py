from concurrent.futures import ThreadPoolExecutor

from crew import hc, store
from crew.paths import get_state_dir

SKIPPED_STATUSES = {"blocked", "error"}


def deliver(envelope_id, wire, targets, sender):
    with ThreadPoolExecutor(max_workers=8) as pool:
        deliveries = list(pool.map(lambda target: deliver_one(wire, target, sender), targets))
    path = get_state_dir() / "deliveries" / f"{envelope_id}.jsonl"
    for record in deliveries:
        store.append_record(path, record)
    return deliveries


def deliver_one(wire, target, sender):
    address = target["address"]
    skip_reason = get_skip_reason(target, sender)
    if skip_reason:
        return {"to": address, "status": "skipped", "reason": skip_reason, "at": store.get_now()}
    error = hc.send_text(address, wire)
    status = "failed" if error else "sent"
    return {"to": address, "status": status, "reason": error, "at": store.get_now()}


def get_skip_reason(target, sender):
    if target["address"] == sender:
        return "self"
    if target.get("status") in SKIPPED_STATUSES:
        return target["status"]
    return None


def get_deliveries(envelope_id):
    return store.get_records(get_state_dir() / "deliveries" / f"{envelope_id}.jsonl")
