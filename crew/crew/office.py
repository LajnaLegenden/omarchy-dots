import fcntl
import json
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from crew import agents, channels, delivery, hc, store
from crew.errors import CrewError, NotFoundError, UsageError
from crew.paths import get_state_dir

ROLES = ("pm", "ux-designer", "ux-reviewer", "developer", "tester")
NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,19}")
LIVE_STATES = {"running", "paused"}
RATE_LIMIT = 10
RATE_WINDOW = timedelta(minutes=10)
PAIR_COOLDOWN = timedelta(seconds=20)
DIGEST_SIZE = 3
DIGEST_TEXT_CHARS = 400


def add_commands(sub):
    office = sub.add_parser("office", help="a team of role agents working in one channel")
    actions = office.add_subparsers(metavar="action")
    office.set_defaults(func=lambda _args: office.print_help() or 2)

    start = actions.add_parser("start", help="start an office: 5 role agents, a channel and a Herdr space")
    start.add_argument("name", help="1-20 of a-z 0-9 - _; also the channel name")
    start.add_argument("--dir", required=True, help="project folder; a git repo gets its own worktree")
    start.add_argument("--brief", help="the goal; posted to the channel for @pm")
    start.add_argument("--budget", type=int, default=30, help="agent posts without a human post before auto-pause")
    start.set_defaults(func=run_start)

    for action, func, about in (
        ("stop", run_stop, "kill the members; the worktree and channel stay"),
        ("pause", run_pause, "keep logging posts but deliver nothing"),
        ("resume", run_resume, "deliver again; each member gets a digest of what it missed"),
    ):
        parser = actions.add_parser(action, help=about)
        parser.add_argument("name")
        parser.set_defaults(func=func)

    ls = actions.add_parser("ls", help="list offices and their members")
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(func=run_ls)


def run_start(args):
    name = to_office_name(args.name)
    source = Path(args.dir).expanduser().resolve()
    if not source.is_dir():
        raise NotFoundError(f"no folder {args.dir}")
    if args.budget < 1:
        raise UsageError("--budget must be at least 1")
    existing = get_office(name)
    if existing and existing["state"] in LIVE_STATES:
        raise CrewError(f"office {name} is already {existing['state']} (crew office stop {name} first)")
    repo = get_repo(source)
    worktree = Path.home() / ".herdr" / "worktrees" / repo["main_root"].name / f"office-{name}" if repo else None
    cwd = worktree / source.relative_to(repo["toplevel"]) if repo else source
    if not is_trusted_dir(cwd, repo):
        trusted = repo["main_root"] if repo else cwd
        raise CrewError(
            f"Claude Code doesn't trust {trusted} yet, so office agents would hang on the trust dialog. "
            f"Run claude once in {trusted}, accept the dialog, then start the office again."
        )
    branch = f"office/{name}" if repo else None
    if repo:
        add_worktree(source, worktree, branch)
    brief_path = cwd / ".office" / "brief.md"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(f"# Brief for office {name}\n\n{args.brief or '(none yet: wait for the user in the channel)'}\n")
    members, first_message = start_members(name, cwd)
    store.write_json(get_office_path(name), {
        "name": name,
        "dir": str(source),
        "cwd": str(cwd),
        "channel": name,
        "members": members,
        "state": "running",
        "budget": args.budget,
        "agent_posts_since_human": 0,
        "paused_reason": None,
        "space": f"crew-{name}",
        "worktree": str(worktree) if worktree else None,
        "branch": branch,
        "started_at": store.get_now(),
        "first_message": first_message,
        "history": {"posts": {}, "pairs": {}},
        "missed": {},
    })
    show_in_herdr(name)
    roster = ", ".join(f"{role} {address}" for role, address in members.items())
    channels.add_post(name, f"Office {name} started in {cwd}. Members: {roster}.", sender="crew")
    if args.brief:
        channels.add_post(name, f"@pm {args.brief}", sender="human")
    print(f"office {name} running in {cwd}" + (f" (branch {branch})" if branch else ""))
    for role, address in members.items():
        print(f"  {role:<12} {address}{get_first_message_warning(first_message[role])}")
    print(f"follow it: crew read {name} --follow, or the 🏢 {name} space in Herdr")
    return 0


def start_members(name, cwd):
    members, first_message = {}, {}
    try:
        for role in ROLES:
            task = f"You are the {role} of office {name}. Read your role instructions, then wait for @mentions in channel {name}. Post nothing yet."
            result = hc.start_terminal(
                [f"office-{role}", task],
                name=f"{name}-{role}",
                cwd=cwd,
                labels={
                    "herdr.space": f"crew-{name}",
                    "herdr.tab": f"crew-{name}-{role}",
                    "crew.office": name,
                    "crew.role": role,
                },
            )
            members[role] = result["address"]
            first_message[role] = result.get("first_message")
    except CrewError:
        for address in members.values():
            hc.kill_terminal(address)
        raise
    return members, first_message


def get_first_message_warning(first_message):
    if not first_message or first_message.get("sent") is not False:
        return ""
    return f"  first message NOT sent ({first_message.get('reason')}): hc read it, then send the task"


def get_repo(source):
    toplevel = run_git(source, "rev-parse", "--path-format=absolute", "--show-toplevel")
    if toplevel.returncode != 0:
        return None
    worktrees = run_git(source, "worktree", "list", "--porcelain").stdout.splitlines()
    main_root = next(line.removeprefix("worktree ") for line in worktrees if line.startswith("worktree "))
    return {"toplevel": Path(toplevel.stdout.strip()), "main_root": Path(main_root)}


def add_worktree(source, worktree, branch):
    if (worktree / ".git").exists():
        return
    has_branch = run_git(source, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0
    worktree.parent.mkdir(parents=True, exist_ok=True)
    args = [str(worktree), branch] if has_branch else ["-b", branch, str(worktree)]
    result = run_git(source, "worktree", "add", *args)
    if result.returncode != 0:
        raise CrewError(f"git worktree add failed: {result.stderr.strip()}")


def run_git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=False, capture_output=True, text=True, timeout=60)


def is_trusted_dir(path, repo):
    claude_json = Path.home() / ".claude.json"
    projects = json.loads(claude_json.read_text()).get("projects", {}) if claude_json.exists() else {}
    candidates = [path, *((repo["main_root"], repo["toplevel"]) if repo else ())]
    return any(projects.get(str(candidate), {}).get("hasTrustDialogAccepted") is True for candidate in candidates)


def show_in_herdr(name):
    space = f"crew-{name}"
    results = [
        run_herdr("space.rename", {"id": space, "name": f"🏢 {name}"}, attempts=3),
        *(run_herdr("tab.rename", {"id": f"{space}-{role}", "name": role}) for role in ROLES),
        run_herdr("tab.new", {"space": space, "name": "office", "mod": "crew-office", "props": {"office": name}}),
        run_herdr("space.select", {"id": space}),
    ]
    if not all(results):
        print("crew: note: Herdr didn't take every layout change (window closed?); the agents run anyway", file=sys.stderr)


def run_herdr(command, args, attempts=1):
    for attempt in range(attempts):
        if attempt:
            time.sleep(1)
        try:
            result = subprocess.run(
                ["herdr-app", "do", command, json.dumps(args, ensure_ascii=False)],
                check=False, capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode == 0:
            return True
    return False


def run_stop(args):
    name = to_office_name(args.name)
    with hold_lock(name):
        office = get_existing_office(name)
        for address in office["members"].values():
            hc.kill_terminal(address)
        store.write_json(get_office_path(name), {**office, "state": "stopped", "stopped_at": store.get_now()})
    run_herdr("space.close", {"id": office["space"], "confirmed": True})
    channels.add_post(name, "Office stopped. The worktree and this channel stay.", sender="crew")
    print(f"office {name} stopped; worktree {office['worktree'] or office['cwd']} kept")
    return 0


def run_pause(args):
    name = to_office_name(args.name)
    with hold_lock(name):
        office = get_existing_office(name)
        if office["state"] == "running":
            store.write_json(get_office_path(name), {
                **office, "state": "paused", "paused_reason": "manual", "paused_at": store.get_now(),
            })
    if office["state"] != "running":
        print(f"office {name} is {office['state']}")
        return 0
    channels.add_post(name, f"Paused. Posts are logged but not delivered. Resume with crew office resume {name}.", sender="crew")
    print(f"office {name} paused")
    return 0


def run_resume(args):
    name = to_office_name(args.name)
    sender = agents.get_sender()
    with hold_lock(name):
        office = get_existing_office(name)
        if sender in office["members"].values():
            raise CrewError("office members can't resume their own office; ask the user (@you)")
        if office["state"] == "stopped":
            raise CrewError(f"office {name} is stopped; start it again with crew office start")
        if office["state"] == "paused":
            store.write_json(get_office_path(name), {
                **office, "state": "running", "paused_reason": None, "paused_at": None,
                "agent_posts_since_human": 0, "missed": {},
            })
    if office["state"] == "running":
        print(f"office {name} is already running")
        return 0
    channels.add_post(name, "Resumed.", sender="crew")
    print(f"office {name} resumed")
    for record in send_digests(office):
        print(f"  digest → {record['to']:<5} {channels.to_outcome(record)}")
    return 0


def send_digests(office):
    posts_by_id = {post["id"]: post for post in channels.get_posts(office["channel"])}
    targets = get_member_targets(office, hc.get_terminals())
    deliveries = []
    for target in targets.values():
        post_ids = office.get("missed", {}).get(target["address"], [])[-DIGEST_SIZE:]
        posts = [posts_by_id[post_id] for post_id in post_ids if post_id in posts_by_id]
        if not posts:
            continue
        deliveries += delivery.deliver(store.get_new_id("d"), to_digest_wire(office["channel"], posts), [target], "crew")
    return deliveries


def to_digest_wire(channel, posts):
    lines = [f"[{post['from_label']}] {post['text'][:DIGEST_TEXT_CHARS]}" for post in posts]
    text = "\n".join([
        "The office was paused. While it was, you were mentioned in:",
        *lines,
        f"Older posts: crew read {channel}.",
    ])
    return channels.to_wire({"channel": channel, "from_label": "crew", "text": text})


def run_ls(args):
    offices = get_offices()
    live = {t["address"]: t for t in (hc.get_terminals() if offices else []) if t.get("state") == "live"}
    rows = [
        {**office, "members_live": {role: get_live_status(live.get(a)) for role, a in office["members"].items()}}
        for office in offices
    ]
    if args.json:
        print(json.dumps({"offices": rows}, ensure_ascii=False))
        return 0
    for row in rows:
        posts = f"{row['agent_posts_since_human']}/{row['budget']} agent posts"
        print(f"{row['name']}  {row['state']}  {posts}  {row['cwd']}")
        for role, address in row["members"].items():
            warning = get_first_message_warning(row.get("first_message", {}).get(role))
            print(f"  {role:<12} {address:<5} {row['members_live'][role]}{warning}")
    return 0


def get_live_status(terminal):
    if terminal is None:
        return "gone"
    return terminal.get("status") or "starting"


def get_route(office, post, sender, targets):
    is_human = sender == "human"
    now = to_time(post["at"])
    history = office.get("history", {"posts": {}, "pairs": {}})
    posts_by_sender = {
        address: [at for at in times if now - to_time(at) < RATE_WINDOW]
        for address, times in history["posts"].items()
    }
    recent_posts = posts_by_sender.get(sender, [])
    count = 0 if is_human else office["agent_posts_since_human"] + 1
    is_over_budget = office["state"] == "running" and count >= office["budget"]
    routed = {
        **office,
        "agent_posts_since_human": count,
        "history": {
            "posts": posts_by_sender | ({} if is_human else {sender: [*recent_posts, post["at"]]}),
            "pairs": {pair: at for pair, at in history["pairs"].items() if now - to_time(at) < PAIR_COOLDOWN},
        },
        **({"state": "paused", "paused_reason": "hop budget", "paused_at": post["at"]} if is_over_budget else {}),
    }
    if routed["state"] != "running":
        paused = {t["address"]: "paused" for t in targets}
        return {**routed, "missed": get_missed(office, post, sender, targets)}, paused, 0
    is_rate_limited = not is_human and len(recent_posts) >= RATE_LIMIT
    routes = {
        t["address"]: get_skip_reason(t["address"], sender, is_rate_limited)
        for t in targets
    }
    allowed = [address for address, reason in routes.items() if not reason]
    delay = get_pair_delay(sender, allowed, routed["history"]["pairs"], now) if not is_human else timedelta(0)
    sent_at = (now + delay).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    sent_pairs = {f"{sender}>{address}": sent_at for address in allowed if not is_human}
    pairs = routed["history"]["pairs"] | sent_pairs
    return {**routed, "history": {**routed["history"], "pairs": pairs}}, routes, delay.total_seconds()


def get_skip_reason(address, sender, is_rate_limited):
    if address == sender:
        return "self"
    if is_rate_limited:
        return "rate"
    return None


def get_pair_delay(sender, addresses, recent_pairs, now):
    waits = [
        PAIR_COOLDOWN - (now - to_time(recent_pairs[f"{sender}>{address}"]))
        for address in addresses
        if f"{sender}>{address}" in recent_pairs
    ]
    return min(PAIR_COOLDOWN, max([timedelta(0), *waits]))


def get_missed(office, post, sender, targets):
    missed = office.get("missed", {})
    return missed | {
        t["address"]: [*missed.get(t["address"], []), post["id"]][-DIGEST_SIZE:]
        for t in targets
        if t["address"] != sender
    }


def route_post(name, post, sender, targets):
    with hold_lock(name):
        office = get_office(name)
        routed, routes, delay_s = get_route(office, post, sender, targets)
        store.write_json(get_office_path(name), routed)
    if routed["state"] == "paused" and office["state"] == "running":
        channels.add_post(
            name,
            f"Paused after {routed['agent_posts_since_human']} agent messages without a human message. "
            f"Resume with crew office resume {name}.",
            sender="crew",
        )
    return routes, delay_s


def get_member_targets(office, terminals):
    live = {t["address"]: t for t in terminals if t.get("state") == "live"}
    return {
        role: {"address": address, "status": live[address].get("status"), "name": live[address].get("name"), "role": role}
        for role, address in office["members"].items()
        if address in live and live[address].get("agent") not in agents.SHELLS
    }


def get_office_for_channel(channel):
    office = get_office(channel)
    return office if office and office["state"] in LIVE_STATES else None


def get_offices():
    offices_dir = get_state_dir() / "offices"
    return [store.get_json(path) for path in sorted(offices_dir.glob("*.json"))] if offices_dir.exists() else []


def get_office(name):
    return store.get_json(get_office_path(name))


def get_existing_office(name):
    office = get_office(name)
    if office is None:
        raise NotFoundError(f"no office {name!r} (see crew office ls)")
    return office


def get_office_path(name):
    return get_state_dir() / "offices" / f"{name}.json"


@contextmanager
def hold_lock(name):
    path = get_state_dir() / "offices" / f"{name}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as file:
        fcntl.flock(file, fcntl.LOCK_EX)
        yield


def to_office_name(name):
    if not NAME_PATTERN.fullmatch(name):
        raise UsageError(f"bad office name {name!r}: 1-20 of a-z 0-9 - _, starting with a letter or digit")
    return name


def to_time(iso):
    return datetime.fromisoformat(iso)
