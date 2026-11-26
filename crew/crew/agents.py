import os

from crew import hc, store
from crew.errors import CrewError, NotFoundError
from crew.paths import get_state_dir

SHELLS = {"bash", "zsh", "fish", "nu", "sh", "dash"}


def is_agent(terminal):
    return (
        terminal.get("state") == "live"
        and terminal.get("status") is not None
        and terminal.get("agent") not in SHELLS
    )


def get_machine(address):
    return address.split("/", 1)[0] if "/" in address else None


def get_sender(terminals=None):
    address = os.environ.get("HC_TERMINAL_ID")
    if not address:
        return "human"
    by_address = {t["address"]: t for t in terminals or hc.get_terminals()}
    seen = set()
    while address in by_address and address not in seen:
        terminal = by_address[address]
        if is_agent(terminal):
            return address
        seen.add(address)
        address = terminal.get("parent")
    return "human"


def get_agents(terminals=None):
    terminals = terminals if terminals is not None else hc.get_terminals()
    sender = get_sender(terminals)
    live = [t for t in terminals if is_agent(t)]
    tasks = get_tasks({t["address"] for t in live})
    roles = get_office_roles()
    return [
        {
            "address": t["address"],
            "machine": get_machine(t["address"]),
            "name": t.get("name"),
            "agent": t.get("agent"),
            "status": t.get("status"),
            "where": t.get("where"),
            "cwd": t.get("cwd"),
            "task": tasks.get(t["address"], {}).get("task"),
            "task_updated_at": tasks.get(t["address"], {}).get("updated_at"),
            "office": roles.get(t["address"], (None, None))[0],
            "role": roles.get(t["address"], (None, None))[1],
            "self": t["address"] == sender,
        }
        for t in live
    ]


def get_tasks(live_addresses):
    tasks_dir = get_state_dir() / "agents"
    if not tasks_dir.exists():
        return {}
    tasks = {}
    for path in tasks_dir.glob("*.json"):
        if path.stem not in live_addresses:
            path.unlink(missing_ok=True)
            continue
        tasks[path.stem] = store.get_json(path)
    return tasks


def get_office_roles():
    offices_dir = get_state_dir() / "offices"
    if not offices_dir.exists():
        return {}
    roles = {}
    for path in offices_dir.glob("*.json"):
        office = store.get_json(path)
        if office.get("state") == "stopped":
            continue
        for role, address in office.get("members", {}).items():
            roles[address] = (office["name"], role)
    return roles


def set_task(task):
    sender = get_sender()
    if sender == "human":
        raise CrewError("crew status only works inside an agent's hc terminal")
    path = get_state_dir() / "agents" / f"{sender}.json"
    if task is None:
        path.unlink(missing_ok=True)
        return sender
    store.write_json(path, {"address": sender, "task": task, "updated_at": store.get_now()})
    return sender


def get_targets(refs, agents):
    resolved = {}
    for ref in refs:
        ref = ref.removeprefix("@")
        if ref in ("all", "team"):
            resolved |= {a["address"]: a for a in agents if not a["self"]}
            continue
        matches = [a for a in agents if is_ref_match(a, ref)]
        if not matches:
            raise NotFoundError(f"no agent matches {ref!r} (see crew who)")
        if len(matches) > 1:
            names = ", ".join(a["address"] for a in matches)
            raise NotFoundError(f"{ref!r} matches several agents: {names}")
        resolved[matches[0]["address"]] = matches[0]
    return list(resolved.values())


def is_ref_match(agent, ref):
    office_role = f"{agent['office']}/{agent['role']}" if agent["office"] else None
    return ref in (agent["address"], agent["name"], office_role)
