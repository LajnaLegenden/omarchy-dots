import json
import shutil
from pathlib import Path

import pytest

from crew.cli import main

TESTS_DIR = Path(__file__).parent


class Crew:
    def __init__(self, root, monkeypatch, capsys):
        self.root = root
        self.hc_dir = root / "hc"
        self.hc_dir.mkdir()
        self.state_dir = root / "state" / "crew"
        self.monkeypatch = monkeypatch
        self.capsys = capsys

    def set_terminals(self, terminals):
        (self.hc_dir / "terminals.json").write_text(json.dumps(terminals))

    def fail_send(self, address, message="hc: refused"):
        (self.hc_dir / "fail.json").write_text(json.dumps({address: message}))

    def put_remote_file(self, machine, path, text):
        target = self.hc_dir / "remote" / machine / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def be(self, address):
        if address is None:
            self.monkeypatch.delenv("HC_TERMINAL_ID", raising=False)
        else:
            self.monkeypatch.setenv("HC_TERMINAL_ID", address)

    def calls(self, command=None):
        path = self.hc_dir / "calls.jsonl"
        calls = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [c for c in calls if command is None or c[0] == command]

    def run(self, *argv):
        self.capsys.readouterr()
        code = main(list(argv))
        out, err = self.capsys.readouterr()
        return code, out, err

    def run_json(self, *argv):
        code, out, err = self.run(*argv, "--json")
        return code, json.loads(out) if out.strip() else None, err


def agent(address, status="idle", agent="claude-code", where="space / 1", **extra):
    return {"address": address, "agent": agent, "status": status, "state": "live", "where": where, "cwd": "/w", **extra}


def shell(address, **extra):
    return {"address": address, "agent": "bash", "state": "live", "where": "space / 1", "cwd": "/w", **extra}


@pytest.fixture
def crew(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_HC_DIR", str(tmp_path / "hc"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", f"{TESTS_DIR / 'fakebin'}:/usr/bin:/bin")
    monkeypatch.delenv("HC_TERMINAL_ID", raising=False)
    for program in ("hc", "herdr-app", "claude"):
        assert shutil.which(program).startswith(str(TESTS_DIR / "fakebin")), f"{program} is not faked"
    instance = Crew(tmp_path, monkeypatch, capsys)
    instance.set_terminals([])
    return instance
