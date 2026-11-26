import ctypes
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from crew import agents, store
from crew.config import get_slot_config
from crew.errors import CrewError, UsageError
from crew.paths import get_state_dir

POLL_S = 1.0
STATUS_EVERY_S = 30
EXIT_WAIT_TIMEOUT = 124
EXIT_BUSY = 75
PR_SET_PDEATHSIG = 1


def add_commands(sub):
    run = sub.add_parser("run", help="run a command inside a resource slot (one build at a time, RAM-aware)")
    run.add_argument("--slot", required=True)
    run.add_argument("--max", type=int, help="holders allowed at once (default: config)")
    run.add_argument("--no-wait", action="store_true", help=f"exit {EXIT_BUSY} instead of waiting")
    run.add_argument("--wait-timeout", type=float, help=f"give up waiting after S seconds (exit {EXIT_WAIT_TIMEOUT})")
    run.add_argument("command", nargs="+", help="the command, after --")
    run.set_defaults(func=lambda args: run_in_slot(
        args.slot, args.command, max_override=args.max, wait_timeout_s=args.wait_timeout, no_wait=args.no_wait))

    slots = sub.add_parser("slots", help="show slot holders and waiters")
    slots.add_argument("--json", action="store_true")
    slots.set_defaults(func=print_slots)


def run_in_slot(name, argv, *, max_override=None, wait_timeout_s=None, no_wait=False):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", name):
        raise UsageError(f"bad slot name {name!r}")
    slot = get_slot_config(name, max_override)
    slot_dir = get_state_dir() / "slots" / name
    (slot_dir / "waiters").mkdir(parents=True, exist_ok=True)
    holder = {"address": get_address(), "pid": os.getpid(), "cmd": " ".join(argv), "cwd": os.getcwd()}
    lock_fd = acquire_slot(slot, slot_dir, holder, wait_timeout_s, no_wait)
    if lock_fd is None:
        return EXIT_BUSY if no_wait else EXIT_WAIT_TIMEOUT
    try:
        return run_child(argv)
    finally:
        os.close(lock_fd)


def acquire_slot(slot, slot_dir, holder, wait_timeout_s, no_wait):
    waiter_path = slot_dir / "waiters" / f"{time.time_ns()}-{os.getpid()}.json"
    draft_path = waiter_path.with_suffix(".draft")
    waiter_fd = os.open(draft_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(waiter_fd, fcntl.LOCK_EX)
    os.write(waiter_fd, json.dumps({**holder, "since": store.get_now()}).encode())
    os.rename(draft_path, waiter_path)
    deadline = None if wait_timeout_s is None else time.monotonic() + wait_timeout_s
    last_reason, last_print = None, 0.0
    try:
        while True:
            reason = get_wait_reason(slot, slot_dir, waiter_path)
            if reason is None:
                lock_fd = take_free_slot(slot, slot_dir, holder)
                if lock_fd is not None:
                    return lock_fd
                reason = "all slots taken"
            if no_wait or (deadline is not None and time.monotonic() >= deadline):
                print(f"crew: slot {slot['name']} busy: {reason}", file=sys.stderr)
                return None
            if reason != last_reason or time.monotonic() - last_print > STATUS_EVERY_S:
                print(f"crew: waiting for slot {slot['name']}: {reason}", file=sys.stderr, flush=True)
                last_reason, last_print = reason, time.monotonic()
            time.sleep(POLL_S)
    finally:
        waiter_path.unlink(missing_ok=True)
        os.close(waiter_fd)


def get_wait_reason(slot, slot_dir, waiter_path):
    waiters = get_live_waiters(slot_dir)
    ahead = [w for w in waiters if w["path"].name < waiter_path.name]
    if ahead:
        return f"{len(ahead)} waiting ahead (next: {to_label(ahead[0])})"
    holders = get_holders(slot, slot_dir)
    if len(holders) >= slot["max"]:
        return f"{len(holders)}/{slot['max']} held by " + ", ".join(to_label(h) for h in holders)
    mem_available = get_mem_available()
    if holders and mem_available < slot["min_free_mem"]:
        return f"MemAvailable {to_gib(mem_available)} < {to_gib(slot['min_free_mem'])} with {len(holders)} running"
    return None


def take_free_slot(slot, slot_dir, holder):
    for index in range(slot["max"]):
        fd = os.open(slot_dir / f"slot-{index}.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            continue
        os.ftruncate(fd, 0)
        os.pwrite(fd, json.dumps({**holder, "since": store.get_now()}).encode(), 0)
        return fd
    return None


def get_holders(slot, slot_dir):
    paths = sorted(slot_dir.glob("slot-*.lock"))
    return [record for path in paths if (record := get_locked_record(path))]


def get_live_waiters(slot_dir):
    waiters = []
    for path in sorted((slot_dir / "waiters").glob("*.json")):
        record = get_locked_record(path)
        if record is None:
            path.unlink(missing_ok=True)
            continue
        waiters.append({**record, "path": path})
    return waiters


def get_locked_record(path):
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    except BlockingIOError:
        data = Path(path).read_text()
        return json.loads(data) if data.strip() else {"pid": None, "cmd": "?"}
    finally:
        os.close(fd)


def run_child(argv):
    try:
        child = subprocess.Popen(argv, preexec_fn=set_parent_death_signal)
    except FileNotFoundError as error:
        raise CrewError(f"command not found: {argv[0]}") from error
    forward = lambda signum, _frame: child.send_signal(signum)
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, forward)
    code = child.wait()
    return 128 - code if code < 0 else code


def set_parent_death_signal():
    ctypes.CDLL(None, use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


def get_address():
    if not os.environ.get("HC_TERMINAL_ID"):
        return "human"
    try:
        return agents.get_sender()
    except CrewError:
        return os.environ["HC_TERMINAL_ID"]


def get_mem_available():
    meminfo = Path(os.environ.get("CREW_MEMINFO", "/proc/meminfo")).read_text()
    kib = re.search(r"^MemAvailable:\s+(\d+) kB", meminfo, re.MULTILINE)
    return int(kib.group(1)) * 1024 if kib else 0


def get_slots():
    slots_dir = get_state_dir() / "slots"
    slot_dirs = sorted(p for p in slots_dir.iterdir() if p.is_dir()) if slots_dir.exists() else []
    slots = []
    for slot_dir in slot_dirs:
        slot = get_slot_config(slot_dir.name)
        waiters = [{k: v for k, v in w.items() if k != "path"} for w in get_live_waiters(slot_dir)]
        slots.append({**slot, "holders": get_holders(slot, slot_dir), "waiters": waiters})
    return {"mem_available": get_mem_available(), "slots": slots}


def print_slots(args):
    data = get_slots()
    if args.json:
        print(json.dumps(data, ensure_ascii=False))
        return 0
    print(f"MemAvailable {to_gib(data['mem_available'])}")
    for slot in data["slots"]:
        print(f"{slot['name']}: {len(slot['holders'])}/{slot['max']} (min free {to_gib(slot['min_free_mem'])})")
        for holder in slot["holders"]:
            print(f"  holds  {to_label(holder)}  since {holder.get('since', '?')}")
        for waiter in slot["waiters"]:
            print(f"  waits  {to_label(waiter)}  since {waiter.get('since', '?')}")
    return 0


def to_label(record):
    return f"{record.get('address', '?')} '{record.get('cmd', '?')}'"


def to_gib(size):
    return f"{size / 1024**3:.1f}G"
