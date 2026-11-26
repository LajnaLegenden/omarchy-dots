import json
import subprocess

from crew.errors import CrewError


def run_hc(args, timeout=60):
    try:
        return subprocess.run(["hc", *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as error:
        raise CrewError("hc (herdr-core) not found on PATH") from error
    except subprocess.TimeoutExpired as error:
        raise CrewError(f"hc {args[0]} timed out after {timeout}s") from error


def get_terminals():
    result = run_hc(["ls", "--json"])
    if result.returncode != 0:
        raise CrewError(f"hc ls failed: {result.stderr.strip()}")
    return json.loads(result.stdout)["terminals"]


def send_text(address, text):
    result = run_hc(["send", address, text], timeout=120)
    if result.returncode == 0:
        return None
    return "hc: " + (result.stderr.strip() or f"exit {result.returncode}")


def start_terminal(argv, *, name, cwd, labels):
    label_args = [arg for key, value in labels.items() for arg in ("--label", f"{key}={value}")]
    args = ["run", "--bg", "--json", "--no-parent", "--keep", "--name", name, "--cwd", str(cwd)]
    result = run_hc([*args, *label_args, "--", *argv], timeout=120)
    if result.returncode != 0:
        raise CrewError(f"hc run {name} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def read_file_on(machine, path):
    result = run_hc(["file", "read", "--on", machine, path], timeout=20)
    return result.stdout if result.returncode == 0 else None


def exec_on(machine, argv, cwd=None):
    cwd_args = ["--cwd", cwd] if cwd else []
    result = run_hc(["exec", "--on", machine, *cwd_args, "--timeout", "10", "--", *argv], timeout=20)
    return result.stdout.strip() if result.returncode == 0 else None


def kill_terminal(address):
    result = run_hc(["kill", address])
    return result.returncode == 0
