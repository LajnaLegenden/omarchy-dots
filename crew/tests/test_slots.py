import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

CREW = str(Path(__file__).parent.parent / "bin" / "crew")


def start(crew, *argv):
    return subprocess.Popen([sys.executable, CREW, *argv], env=os.environ.copy(), stderr=subprocess.PIPE, text=True)


def get_slot(crew, key):
    slots = crew.run_json("slots")[1]["slots"]
    return slots[0][key] if slots else []


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_returns_the_command_exit_code(crew):
    code, _, _ = crew.run("run", "--slot", "build", "--", "sh", "-c", "exit 7")
    assert code == 7


def test_second_holder_waits_for_the_first(crew, tmp_path):
    log = tmp_path / "log"
    script = f"echo start >> {log}; sleep 0.6; echo end >> {log}"
    first = start(crew, "run", "--slot", "e2e", "--max", "1", "--", "sh", "-c", script)
    assert wait_for(lambda: log.exists())
    second = start(crew, "run", "--slot", "e2e", "--max", "1", "--", "sh", "-c", script)
    first.wait(10), second.wait(10)
    assert log.read_text().split() == ["start", "end", "start", "end"]


def test_no_wait_exits_75_when_busy(crew):
    holder = start(crew, "run", "--slot", "e2e", "--max", "1", "--", "sleep", "3")
    assert wait_for(lambda: get_slot(crew, "holders"))
    code, _, _ = crew.run("run", "--slot", "e2e", "--max", "1", "--no-wait", "--", "true")
    holder.kill()
    assert code == 75


def test_wait_timeout_exits_124(crew):
    holder = start(crew, "run", "--slot", "e2e", "--max", "1", "--", "sleep", "5")
    assert wait_for(lambda: get_slot(crew, "holders"))
    code, _, _ = crew.run("run", "--slot", "e2e", "--max", "1", "--wait-timeout", "0.5", "--", "true")
    holder.kill()
    assert code == 124


def test_slot_frees_when_holder_is_killed(crew):
    holder = start(crew, "run", "--slot", "e2e", "--max", "1", "--", "sleep", "30")
    assert wait_for(lambda: get_slot(crew, "holders"))
    holder.send_signal(signal.SIGKILL)
    holder.wait()
    code, _, _ = crew.run("run", "--slot", "e2e", "--max", "1", "--wait-timeout", "3", "--", "true")
    assert code == 0


def test_slots_json_shows_holder_and_waiter(crew):
    holder = start(crew, "run", "--slot", "e2e", "--max", "1", "--", "sleep", "3")
    assert wait_for(lambda: get_slot(crew, "holders"))
    waiter = start(crew, "run", "--slot", "e2e", "--max", "1", "--", "true")
    assert wait_for(lambda: get_slot(crew, "waiters"))
    _, out, _ = crew.run_json("slots")
    holder.kill(), waiter.kill()
    assert out["slots"][0]["holders"][0]["cmd"] == "sleep 3"


def test_low_memory_blocks_only_the_second_holder(crew, tmp_path, monkeypatch):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 32000000 kB\nMemAvailable: 1000000 kB\n")
    monkeypatch.setenv("CREW_MEMINFO", str(meminfo))
    holder = start(crew, "run", "--slot", "build", "--", "sleep", "3")
    assert wait_for(lambda: get_slot(crew, "holders"))
    code, _, err = crew.run("run", "--slot", "build", "--no-wait", "--", "true")
    holder.kill()
    assert code == 75 and "MemAvailable" in err


def test_config_overrides_defaults(crew, tmp_path):
    config = tmp_path / "config" / "crew" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('[slots.build]\nmax = 3\nmin_free_mem = "1G"\n')
    crew.run("run", "--slot", "build", "--", "true")
    _, out, _ = crew.run_json("slots")
    assert (out["slots"][0]["max"], out["slots"][0]["min_free_mem"]) == (3, 1024**3)
