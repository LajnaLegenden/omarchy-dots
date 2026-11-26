import contextlib
import fcntl
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from crew import cli, store
from crew.paths import get_state_dir

CREW_BIN = Path(__file__).resolve().parent.parent / "bin" / "crew"
RUN_ID_PATTERN = re.compile(r"b-[a-z0-9]{1,32}")
CONFIRM_TIMEOUT_S = 60
COMMAND_TIMEOUT_S = 90
MAX_OUTPUT_CHARS = 16000
MAX_DETAIL_CHARS = 4000
MAX_PROJECTS = 20

POLICY = {
    "herdr-app ls": "auto",
    "herdr-app status": "auto",
    "herdr-app commands": "auto",
    "hc ls": "auto",
    "hc get": "auto",
    "hc read": "auto",
    "crew who": "auto",
    "crew send": "confirm",
    "crew broadcast": "confirm",
    "projects": "auto",
}

# herdr-app do commands that only move or add things on screen; every other one asks first.
HERDR_AUTO_COMMANDS = {
    "space.new", "space.rename", "space.move", "space.select", "space.next", "space.prev",
    "tab.new", "tab.rename", "tab.move", "tab.select", "tab.next", "tab.prev", "tab.settle", "tab.unsettle",
    "pane.split", "pane.zoom", "pane.focus", "pane.go", "pane.swap",
    "terminal.open", "terminal.keep", "terminal.peek", "terminal.show", "terminal.pin", "terminal.scroll",
    "agent.focus", "agent.next", "agent.prev",
    "layout.switch", "layout.toggle", "layout.show", "layout.hide", "layout.resize", "layout.select",
    "mod.open", "overlay.close", "app.help", "app.palette", "app.settings",
    "app.zoom_in", "app.zoom_out", "app.zoom_reset",
}

# Args that start a program or type into an agent: those ask first even on a harmless command, nested too.
HERDR_RISKY_ARGS = {"argv", "task"}

# Mods that only display things; any other mod (e.g. worktree) acts on its props, so it asks first.
DISPLAY_MODS = {"crew-office", "crew-broadcast", "files", "changes"}

CONFIRM_TITLES = {
    "space.close": "Close space",
    "tab.close": "Close tab",
    "pane.close": "Close pane",
    "terminal.kill": "Kill terminal",
    "terminal.park": "Send terminal back",
    "crew send": "Message an agent",
    "crew broadcast": "Message agents",
}


def get_bar_dir():
    return get_state_dir() / "bar"


def get_events_path(run_id):
    return get_bar_dir() / f"{run_id}.jsonl"


def is_run_id(value):
    return bool(value and RUN_ID_PATTERN.fullmatch(value))


def add_event(run_id, event):
    store.append_record(get_events_path(run_id), event)


def get_next_action_n(run_id):
    path = get_bar_dir() / f"{run_id}.seq"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as file:
        fcntl.flock(file, fcntl.LOCK_EX)
        file.seek(0)
        n = int(file.read() or 0) + 1
        file.seek(0)
        file.truncate()
        file.write(str(n))
    return n


def run_bar_exec(argv):
    run_id = os.environ.get("CREW_BAR_RUN")
    run_id = run_id if is_run_id(run_id) else None
    argv = to_bar_argv(argv)
    policy = get_policy(argv)
    n = get_next_action_n(run_id) if run_id else None
    if policy == "refuse":
        return refuse(run_id, n, argv, "not allowed: see the commands in your instructions")
    if policy == "confirm" and not run_id:
        return refuse(run_id, n, argv, "needs the user's OK, and only the crew bar can ask for it")
    dry_run = get_dry_run(argv) if policy == "confirm" else None
    if dry_run and dry_run.returncode >= 2:
        return finish(run_id, n, dry_run.args, dry_run)
    if policy == "confirm":
        title, detail = get_confirm_text(argv, dry_run)
        if len(detail) > MAX_DETAIL_CHARS:
            return refuse(run_id, n, argv, f"too long to show the user for approval; keep it under {MAX_DETAIL_CHARS} characters")
        answer = ask_user(run_id, n, argv, title, detail)
        if answer != "yes":
            status = "denied" if answer == "no" else "timeout"
            add_event(run_id, {"type": "action", "n": n, "argv": argv, "status": status, "code": None})
            reason = "the user said no" if answer == "no" else f"no answer from the user in {get_confirm_timeout():g} s"
            print(f"crew bar: {reason}; nothing ran", file=sys.stderr)
            return 1
        argv = to_confirmed_argv(argv)
    return finish(run_id, n, argv, execute(argv))


def to_bar_argv(argv):
    # A preset broadcast waits for replies by default; the bar can't wait, so it asks for them and returns.
    if argv[:2] != ["crew", "broadcast"]:
        return argv
    args = get_crew_args(argv)
    if args is None or not args.preset or args.reply or args.collect:
        return argv
    return [*argv[:2], "--reply", *argv[2:]]


def get_crew_args(argv):
    try:
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            return cli.get_parser().parse_args(argv[1:])
    except SystemExit:
        return None


def to_confirmed_argv(argv):
    # The user just said yes here, so Herdr shouldn't ask a second time.
    if argv[:2] != ["herdr-app", "do"] or len(argv) < 3 or argv[2] not in ("space.close", "tab.close"):
        return argv
    args = to_herdr_args(argv[3:])
    if args is None or "confirmed" in args or any(token.lstrip().startswith("{") for token in argv[3:]):
        return argv
    return [*argv, "--confirmed", "true"]


def finish(run_id, n, argv, result):
    if run_id:
        add_event(run_id, {"type": "action", "n": n, "argv": argv, "status": "ran", "code": result.returncode})
    print(to_short_output(result.stdout), end="")
    print(to_short_output(result.stderr), end="", file=sys.stderr)
    return result.returncode


def get_policy(argv):
    if not argv:
        return "refuse"
    if argv[:2] == ["herdr-app", "do"]:
        return get_herdr_do_policy(argv[2:])
    policy = POLICY.get(" ".join(argv[:2])) or POLICY.get(argv[0], "refuse")
    if policy != "confirm" or argv[0] != "crew":
        return policy
    args = get_crew_args(argv)
    if args is None or getattr(args, "collect", False):
        return "refuse"
    return "auto" if getattr(args, "dry_run", False) else "confirm"


def get_herdr_do_policy(tokens):
    if not tokens:
        return "refuse"
    command = tokens[0]
    args = to_herdr_args(tokens[1:])
    if args is None or command not in HERDR_AUTO_COMMANDS or has_risky_arg(args):
        return "confirm"
    return "confirm" if "mod" in args and args["mod"] not in DISPLAY_MODS else "auto"


def has_risky_arg(value):
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        value = to_json_value(value)
    if isinstance(value, dict):
        return bool(HERDR_RISKY_ARGS & value.keys()) or any(has_risky_arg(v) for v in value.values())
    if isinstance(value, list):
        return any(has_risky_arg(v) for v in value)
    return False


def to_herdr_args(tokens):
    args, index = {}, 0
    while index < len(tokens):
        token = tokens[index]
        if token.lstrip().startswith("{"):
            parsed = to_json_object(token)
            if parsed is None:
                return None
            args |= parsed
            index += 1
            continue
        if not token.startswith("--") or len(token) == 2:
            return None
        key, has_value, value = token[2:].partition("=")
        if not has_value and index + 1 >= len(tokens):
            return None
        args[key] = value if has_value else tokens[index + 1]
        index += 1 if has_value else 2
    return args


def to_json_value(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def to_json_object(text):
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def refuse(run_id, n, argv, reason):
    if run_id:
        add_event(run_id, {"type": "action", "n": n, "argv": argv, "status": "refused", "code": 2})
    print(f"crew bar-exec: {reason}", file=sys.stderr)
    return 2


def ask_user(run_id, n, argv, title, detail):
    add_event(run_id, {"type": "confirm", "n": n, "argv": argv, "title": title, "detail": detail})
    answer_path = get_bar_dir() / f"{run_id}.answer-{n}"
    deadline = time.monotonic() + get_confirm_timeout()
    while time.monotonic() < deadline:
        if answer_path.exists():
            return answer_path.read_text().strip()
        time.sleep(0.1)
    return None


def get_confirm_timeout():
    return float(os.environ.get("CREW_BAR_CONFIRM_S") or CONFIRM_TIMEOUT_S)


def get_confirm_text(argv, dry_run):
    if argv[:2] == ["crew", "send"]:
        return CONFIRM_TITLES["crew send"], " ".join(argv[2:])
    if dry_run:
        return CONFIRM_TITLES["crew broadcast"], to_broadcast_detail(dry_run.stdout)
    command = argv[2].split(":")[0] if len(argv) > 2 else ""
    args = to_herdr_args(argv[3:]) or {}
    target = next((args[key] for key in ("id", "pane", "terminal", "space") if args.get(key)), None)
    label = get_herdr_labels().get(target) if target else None
    summary = f"{command} {' '.join(argv[3:])}".strip()
    return CONFIRM_TITLES.get(command, f"Run {command}"), f"{label}\n{summary}" if label else summary


def get_dry_run(argv):
    if argv[:2] != ["crew", "broadcast"]:
        return None
    return execute([*argv[:2], "--dry-run", "--json", *argv[2:]])


def to_broadcast_detail(stdout):
    result = to_json_object(stdout)
    if not result or not isinstance(result.get("targets"), list):
        return stdout.strip()
    rows = [
        f"{t.get('address')}  {t.get('where') or ''}  {t.get('reason') or t.get('delivery') or ''}".rstrip()
        for t in result["targets"]
    ]
    return "\n".join([f"To {len(rows)} agent{'s' if len(rows) != 1 else ''}:", *rows, "", result.get("text") or ""]).strip()


def get_herdr_labels():
    result = execute(["herdr-app", "ls"])
    if result.returncode != 0:
        return {}
    labels = {}
    for space in (to_json_object(result.stdout) or {}).get("spaces", []):
        space_terminals = [t for tab in space.get("tabs", []) for t in tab.get("terminals", [])]
        labels[space["id"]] = f"space “{space['name']}”: {to_terminal_list(space_terminals)}"
        for tab in space.get("tabs", []):
            where = f"{space['name']} / {tab['name']}"
            labels[tab["id"]] = f"tab “{where}”: {to_terminal_list(tab.get('terminals', []))}"
            labels |= {t[key]: f"{t['terminal']} in “{where}”" for t in tab.get("terminals", []) for key in ("pane", "terminal")}
    return labels


def to_terminal_list(terminals):
    if not terminals:
        return "no terminals"
    return ", ".join(" ".join(filter(None, (t["terminal"], t.get("app") or "shell", t.get("status")))) for t in terminals)


def execute(argv):
    if argv[0] == "projects":
        return get_projects(argv)
    command = [sys.executable, str(CREW_BIN), *argv[1:]] if argv[0] == "crew" else argv
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return subprocess.CompletedProcess(argv, 127, "", f"{argv[0]}: not found\n")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", f"{argv[0]}: timed out after {COMMAND_TIMEOUT_S}s\n")
    result.args = argv
    return result


def get_projects(argv):
    words = [word.lower() for word in argv[1:]]
    finder = shutil.which("go-folder-finder")
    if not words or not finder:
        reason = "usage: projects <words>" if not words else "go-folder-finder not found"
        return subprocess.CompletedProcess(argv, 1, "", reason + "\n")
    result = subprocess.run([finder, "list"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    matches = [path for path in result.stdout.splitlines() if all(word in path.lower() for word in words)]
    ranked = sorted(matches, key=lambda path: (Path(path).name.lower() != words[0], len(path)))
    stdout = "".join(f"{path}\n" for path in ranked[:MAX_PROJECTS]) or "no project folder matches\n"
    return subprocess.CompletedProcess(argv, 0, stdout, result.stderr)


def to_short_output(text):
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n… ({len(text) - MAX_OUTPUT_CHARS} more characters cut)\n"
