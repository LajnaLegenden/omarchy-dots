import functools
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import PurePosixPath

from crew import agents, delivery, hc, messages, replies
from crew.errors import NotFoundError, UsageError

PRESETS = {
    "shutdown": {
        "text": "Prepare for laptop shutdown: finish your current step, save your state (update notes/devlog if you "
        "keep them), do not start new work, then reply when it is safe to power off.",
        "collect": True,
    },
    "status": {
        "text": "Status report: reply with one line on what you are doing right now and what is left.",
        "collect": True,
    },
    "pause": {"text": "Pause after your current step and wait for further instructions.", "collect": False},
}
STATUSES = ("working", "idle", "done", "blocked")
LEADING_SYMBOLS = re.compile(r"^\W+")

MATCHERS = {
    "to": lambda agent, refs: any(agents.is_ref_match(agent, ref) for ref in refs),
    "space": lambda agent, names: bool(get_space_keys(agent["where"]) & set(names)),
    "repo": lambda agent, names: bool(get_repo_names(agent.get("machine"), agent["cwd"]) & set(names)),
    "cwd": lambda agent, prefixes: any(is_under(agent["cwd"], prefix) for prefix in prefixes),
    "status": lambda agent, statuses: agent["status"] in statuses,
}


def add_commands(sub):
    parser = sub.add_parser("broadcast", help="message many agents at once, optionally collecting replies")
    parser.add_argument("text", nargs="?", help="the message; - reads stdin")
    parser.add_argument("--all", action="store_true", help="every agent but yourself")
    parser.add_argument("--space", action="append", default=[], metavar="NAME", help="space name, emoji optional")
    parser.add_argument("--repo", action="append", default=[], metavar="NAME", help="origin or main checkout name")
    parser.add_argument("--cwd", action="append", default=[], metavar="PREFIX", help="folder the agent works under")
    parser.add_argument("--to", action="append", default=[], metavar="ADDR", help="address or hc name; commas ok")
    parser.add_argument("--status", action="append", default=[], help="working,idle,done,blocked")
    parser.add_argument("--exclude", action="append", default=[], metavar="ADDR")
    parser.add_argument("--preset", metavar="NAME", help="a canned message (see --presets)")
    parser.add_argument("--presets", action="store_true", help="list the presets")
    parser.add_argument("--reply", action="store_true", help="ask for replies and return at once")
    parser.add_argument("--collect", action="store_true", help="ask for replies and wait for them")
    parser.add_argument("--timeout", type=float, default=600, metavar="SEC", help="how long --collect waits")
    parser.add_argument("--dry-run", action="store_true", help="show who would get it, send nothing")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run_broadcast)


def run_broadcast(args):
    if args.presets:
        return print_presets(args.json)
    text, wants_reply, is_collect = get_plan(args)
    targets, missing_refs = get_targets(args)
    message_id, rows = send(text, targets, wants_reply, args)
    rows += [to_row({"address": ref}, "skipped", "not-found") for ref in missing_refs]
    replies_path = str(replies.get_replies_path(message_id)) if message_id and wants_reply else None
    result = {"id": message_id, "text": text, "reply": wants_reply, "replies_path": replies_path, "targets": rows}
    if not args.json:
        print_deliveries(result)
    received, is_interrupted = collect(message_id, rows, args) if is_collect and message_id else ([], False)
    rows_by_address = {row["address"]: row for row in rows}
    for record in received:
        if record["from"] in rows_by_address:
            rows_by_address[record["from"]]["reply"] = {"text": record["text"], "at": record.get("at")}
    is_waiting = any(row["delivery"] == "sent" and row["reply"] is None for row in rows)
    result["summary"] = get_summary(rows, is_collect and is_waiting and not is_interrupted)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    elif is_collect and message_id:
        print_missing(rows)
    if is_interrupted:
        return 130
    if not any(row["delivery"] in ("sent", "would-send") for row in rows):
        raise NotFoundError("nothing delivered" if targets else "no agent matches")
    summary = result["summary"]
    return 1 if summary["skipped"] or summary["failed"] or summary["timed_out"] else 0


def get_plan(args):
    if args.reply and args.collect:
        raise UsageError("--collect already asks for replies; drop --reply")
    if args.preset and args.text is not None:
        raise UsageError("give a preset or a message, not both")
    if not args.preset and args.text is None:
        raise UsageError("give a message (- reads stdin) or --preset NAME")
    preset = PRESETS.get(args.preset) if args.preset else {"text": None, "collect": False}
    if preset is None:
        raise UsageError(f"unknown preset {args.preset!r} (see crew broadcast --presets)")
    text = preset["text"] or (sys.stdin.read() if args.text == "-" else args.text).strip()
    if not text:
        raise UsageError("empty message")
    is_collect = args.collect or (preset["collect"] and not args.reply)
    return text, is_collect or args.reply, is_collect


def get_targets(args):
    selectors = {
        "to": [ref.removeprefix("@") for ref in to_values(args.to)],
        "space": [name.strip().lower() for name in args.space if name.strip()],
        "repo": [name.strip().lower() for name in args.repo if name.strip()],
        "cwd": [os.path.abspath(os.path.expanduser(prefix)) for prefix in args.cwd],
        "status": to_values(args.status),
    }
    if not args.all and not any(selectors.values()):
        raise UsageError("pick targets: --all, --space, --repo, --cwd, --to or --status")
    unknown_statuses = sorted(set(selectors["status"]) - set(STATUSES))
    if unknown_statuses:
        raise UsageError(f"unknown status {', '.join(unknown_statuses)} (use {','.join(STATUSES)})")
    excluded = set(to_values(args.exclude))
    all_agents = agents.get_agents()
    targets = [
        agent
        for agent in all_agents
        if agent["address"] not in excluded
        and not agent["self"]
        and all(MATCHERS[name](agent, values) for name, values in selectors.items() if values)
    ]
    missing_refs = [ref for ref in selectors["to"] if not any(agents.is_ref_match(a, ref) for a in all_agents)]
    return targets, missing_refs


def send(text, targets, wants_reply, args):
    if args.dry_run or not targets:
        sender = next((target["address"] for target in targets if target["self"]), "human")
        reasons = [(target, delivery.get_skip_reason(target, sender)) for target in targets]
        return None, [to_row(target, "skipped" if reason else "would-send", reason) for target, reason in reasons]
    ttl_s = max(600, args.timeout)
    sent = messages.send_message(text, targets, kind="broadcast", wants_reply=wants_reply, ttl_s=ttl_s)
    by_address = {record["to"]: record for record in sent["deliveries"]}
    rows = [to_row(t, by_address[t["address"]]["status"], by_address[t["address"]]["reason"]) for t in targets]
    return sent["id"], rows


def collect(message_id, rows, args):
    expected = [row["address"] for row in rows if row["delivery"] == "sent"]
    if not expected:
        return [], False
    received = []

    def on_reply(record):
        received.append(record)
        if not args.json:
            print_reply(record)

    if not args.json:
        print(f"waiting up to {args.timeout:g}s for {len(expected)} replies (ctrl-c stops)", file=sys.stderr)
    try:
        replies.wait_for_replies(message_id, expected, args.timeout, on_reply=on_reply)
    except KeyboardInterrupt:
        return received, True
    return received, False


def to_row(agent, delivery_status, reason):
    fields = {key: agent.get(key) for key in ("address", "agent", "where", "cwd", "status")}
    return {**fields, "delivery": delivery_status, "reason": reason, "reply": None}


def to_values(values):
    return [value.strip() for raw in values for value in raw.split(",") if value.strip()]


def get_space_keys(where):
    space = (where or "").split(" / ", 1)[0].strip().lower()
    return {key for key in (space, LEADING_SYMBOLS.sub("", space)) if key}


def is_under(cwd, prefix):
    return bool(cwd) and PurePosixPath(cwd).is_relative_to(prefix)


@functools.cache
def get_repo_names(machine, cwd):
    if not cwd:
        return frozenset()
    origin = get_git_output(machine, cwd, "remote", "get-url", "origin")
    common_dir = get_git_output(machine, cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    origin_name = origin and re.split(r"[/:]", origin.rstrip("/"))[-1]
    common_path = common_dir and PurePosixPath(common_dir)
    main_name = common_path and (common_path.parent.name if common_path.name == ".git" else common_path.name)
    return frozenset(name.removesuffix(".git").lower() for name in (origin_name, main_name) if name)


def get_git_output(machine, cwd, *args):
    if machine:
        return hc.exec_on(machine, ["git", *args], cwd=cwd)
    try:
        result = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def get_summary(rows, is_timed_out):
    counts = Counter(row["delivery"] for row in rows)
    return {
        "targets": len(rows),
        "sent": counts["sent"],
        "skipped": counts["skipped"],
        "failed": counts["failed"],
        "replied": sum(row["reply"] is not None for row in rows),
        "timed_out": is_timed_out,
    }


def print_presets(as_json):
    presets = [
        {"name": name, "text": preset["text"], "reply": preset["collect"], "collect": preset["collect"]}
        for name, preset in PRESETS.items()
    ]
    if as_json:
        print(json.dumps({"presets": presets}, ensure_ascii=False))
        return 0
    for preset in presets:
        print(f"{preset['name']:<9} {'collect' if preset['collect'] else 'no reply':<9} {preset['text']}")
    return 0


def print_deliveries(result):
    rows = result["targets"]
    print(f"{result['id'] or 'dry run'}: {len(rows)} target{'' if len(rows) == 1 else 's'}")
    for row in rows:
        label = row["delivery"] + (f" ({row['reason']})" if row["reason"] else "")
        print(f"  {row['address']:<5} {label:<20} {row['where'] or '':<28} {row['agent'] or ''}".rstrip(), flush=True)


def print_reply(record):
    where, agent = record.get("where") or "", record.get("agent") or ""
    print(f"{record['from']:<5} {where:<28} {agent:<12} {record['text']}", flush=True)


def print_missing(rows):
    missing = [row for row in rows if row["delivery"] == "sent" and row["reply"] is None]
    if not missing:
        return
    print("no reply from:")
    for row in missing:
        print(f"  {row['address']:<5} {row['where'] or '':<28} {row['agent'] or ''}".rstrip())
