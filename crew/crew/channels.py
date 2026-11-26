import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from crew import agents, delivery, hc, messages, office, store
from crew.errors import UsageError
from crew.paths import get_state_dir

CHANNEL_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,40}")
MENTION_PATTERN = re.compile(r"(?<![\w@/])@([a-zA-Z0-9_/-]+)")
DURATION_PATTERN = re.compile(r"(\d+)([smhd])")
DURATION_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
HUMAN_REFS = {"you", "human", "user"}
TEAM_REFS = {"all", "team"}
SYSTEM_SENDER = "crew"
MAX_POST_BYTES = 8 * 1024


def add_commands(sub):
    post = sub.add_parser("post", help="post to a channel; @mentioned agents get the post")
    post.add_argument("channel", help="channel name: general, an office name, ... (#name works when quoted)")
    post.add_argument("text", help="the post; - reads stdin")
    post.add_argument("--json", action="store_true")
    post.set_defaults(func=run_post)

    read = sub.add_parser("read", help="read a channel")
    read.add_argument("channel", nargs="?", default="general")
    read.add_argument("--since", help="30m, 2h, an ISO time or a post id")
    read.add_argument("--limit", type=int, default=20, help="last N posts (default 20, 0: all)")
    read.add_argument("--follow", action="store_true", help="keep printing new posts")
    read.add_argument("--json", action="store_true", help="one JSON post per line")
    read.set_defaults(func=run_read)


def run_post(args):
    text = (sys.stdin.read() if args.text == "-" else args.text).strip()
    if not text:
        raise UsageError("empty post")
    result = add_post(args.channel, text)
    post = result["post"]
    for ref in post.get("unresolved", []):
        print(f"crew: warning: @{ref} matches no running agent (kept in the post)", file=sys.stderr)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0
    print(f"{post['id']} → #{post['channel']}")
    if not result["deliveries"]:
        print("  no one mentioned: logged only")
    for record in result["deliveries"]:
        print(f"  {record['to']:<5} {to_outcome(record)}")
    return 0


def add_post(channel, text, sender=None):
    name = to_channel_name(channel)
    if len(text.encode()) > MAX_POST_BYTES:
        raise UsageError("post over 8 KB: write it to a file and post the path")
    refs = get_mention_refs(text)
    channel_office = office.get_office_for_channel(name)
    is_lookup_needed = sender is None or any(ref.lower() not in HUMAN_REFS for ref in refs)
    terminals = hc.get_terminals() if is_lookup_needed else []
    sender = sender or agents.get_sender(terminals)
    own_office = agents.get_office_roles().get(sender, (None, None))[0]
    if own_office and own_office != name:
        raise UsageError(f"office members post only in their office channel ({own_office})")
    all_agents = agents.get_agents(terminals) if terminals else []
    members = office.get_member_targets(channel_office, terminals) if channel_office else {}
    team = list(members.values()) if channel_office else all_agents
    targets, unresolved = get_mention_targets(refs, {"team": team, "members": members, "agents": all_agents}, sender)
    role = next((r for r, a in channel_office["members"].items() if a == sender), None) if channel_office else None
    post = {
        "id": store.get_new_id("p"),
        "channel": name,
        "from": sender,
        "from_label": get_poster_label(sender, role, all_agents),
        **({"role": role} if role else {}),
        "text": text,
        "mentions": refs,
        **({"unresolved": unresolved} if unresolved else {}),
        "at": store.get_now(),
    }
    store.append_record(get_channel_path(name), post)
    return {"post": post, "deliveries": get_post_deliveries(post, targets, channel_office)}


def get_post_deliveries(post, targets, channel_office):
    sender = post["from"]
    is_routed = channel_office is not None and sender != SYSTEM_SENDER
    routes, delay_s = office.route_post(channel_office["name"], post, sender, targets) if is_routed else ({}, 0)
    skipped = [
        {"to": t["address"], "status": "skipped", "reason": routes[t["address"]], "at": post["at"]}
        for t in targets
        if routes.get(t["address"])
    ]
    for record in skipped:
        store.append_record(get_state_dir() / "deliveries" / f"{post['id']}.jsonl", record)
    allowed = [t for t in targets if not routes.get(t["address"])]
    if allowed and delay_s > 0:
        print(f"crew: pacing, delivering in {delay_s:.0f}s (pair cooldown)", file=sys.stderr, flush=True)
        time.sleep(delay_s)
    sent = delivery.deliver(post["id"], to_wire(post), allowed, sender) if allowed else []
    by_address = {record["to"]: record for record in [*skipped, *sent]}
    return [by_address[t["address"]] for t in targets]


def get_mention_refs(text):
    refs = [match.rstrip("-/") for match in MENTION_PATTERN.findall(text)]
    return list(dict.fromkeys(ref for ref in refs if ref))


def get_mention_targets(refs, pools, sender):
    targets, unresolved = {}, []
    for ref in refs:
        lowered = ref.lower()
        if lowered in HUMAN_REFS:
            continue
        if lowered in TEAM_REFS:
            targets |= {t["address"]: t for t in pools["team"] if t["address"] != sender}
            continue
        matches = [pools["members"][lowered]] if lowered in pools["members"] else [
            a for a in pools["agents"] if agents.is_ref_match(a, ref)
        ]
        if len(matches) != 1:
            unresolved.append(ref)
            continue
        targets[matches[0]["address"]] = matches[0]
    return list(targets.values()), unresolved


def get_poster_label(sender, role, all_agents):
    if sender in ("human", SYSTEM_SENDER):
        return sender
    if role:
        return f"{sender} {role}"
    return messages.get_sender_label(sender, all_agents)


def to_wire(post):
    channel = post["channel"]
    sender = messages.escape_attr(post["from_label"])
    hint = f"crew post {channel} '<text>'"
    footer = (
        f'(To answer, run: crew post {channel} "<text>" — only if you have something to add. '
        "Text you write in chat is not seen by the team.)"
    )
    return f'<crew channel="{channel}" from="{sender}" post="{hint}">\n{messages.escape(post["text"])}\n{footer}\n</crew>'


def to_outcome(record):
    if record["status"] == "sent":
        return "sent"
    if record["status"] == "skipped":
        return f"not delivered ({record['reason']})"
    return f"failed ({record['reason']})"


def to_channel_name(channel):
    name = channel.removeprefix("#")
    if not CHANNEL_PATTERN.fullmatch(name):
        raise UsageError(f"bad channel name {channel!r}: 1-41 of a-z 0-9 - _, starting with a letter or digit")
    return name


def get_channel_path(name):
    return get_state_dir() / "channels" / f"{name}.jsonl"


def get_posts(channel):
    return store.get_records(get_channel_path(to_channel_name(channel)))


def run_read(args):
    if args.limit < 0:
        raise UsageError("--limit must be 0 or more")
    path = get_channel_path(to_channel_name(args.channel))
    records, offset = store.get_records_from(path, 0)
    posts = get_posts_since(records, args.since)
    print_post = (lambda p: print(json.dumps(p, ensure_ascii=False), flush=True)) if args.json else print_post_line
    for post in posts[max(0, len(posts) - args.limit) if args.limit else 0:]:
        print_post(post)
    while args.follow:
        time.sleep(0.5)
        new_records, offset = store.get_records_from(path, offset)
        for post in new_records:
            print_post(post)
    return 0


def get_posts_since(posts, since):
    if since is None:
        return posts
    if since.startswith("p-"):
        ids = [post["id"] for post in posts]
        return posts[ids.index(since) + 1:] if since in ids else posts
    cutoff = to_cutoff(since)
    return [post for post in posts if to_time(post["at"]) > cutoff]


def to_cutoff(since):
    duration = DURATION_PATTERN.fullmatch(since)
    if duration:
        amount, unit = duration.groups()
        return datetime.now(timezone.utc) - timedelta(**{DURATION_UNITS[unit]: int(amount)})
    try:
        return datetime.fromisoformat(since).astimezone(timezone.utc)
    except ValueError as error:
        raise UsageError(f"bad --since {since!r}: use 30m, 2h, 1d, an ISO time or a post id") from error


def to_time(iso):
    return datetime.fromisoformat(iso)


def print_post_line(post):
    at = to_time(post["at"]).astimezone()
    stamp = at.strftime("%H:%M") if at.date() == datetime.now().date() else at.strftime("%b %d %H:%M")
    first, *rest = post["text"].splitlines() or [""]
    print(f"{stamp} {post['from_label']}: {first}", flush=True)
    for line in rest:
        print(f"      {line}", flush=True)
