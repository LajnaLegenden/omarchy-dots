import json
import time
from pathlib import Path

CONTEXT = json.dumps({"focused": {"space": "sp1", "tab": "tb1", "pane": "p1"}})


def text_delta(text):
    return {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}}


def result(text, is_error=False):
    return {"type": "result", "subtype": "success", "is_error": is_error, "result": text}


def script_claude(crew, lines=(), sleep=0, exit=0, stderr=""):
    script = {"lines": list(lines), "sleep": sleep, "exit": exit, "stderr": stderr}
    (crew.hc_dir / "claude.json").write_text(json.dumps(script))


def start(crew, text, *options):
    _, out, _ = crew.run("bar", "start", "--context", CONTEXT, *options, "--", text)
    return json.loads(out)


def read_events(run):
    return [json.loads(line) for line in Path(run["events"]).read_text().splitlines()]


def wait_for(get_value, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = get_value()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("timed out")


def wait_for_end(run):
    return wait_for(lambda: (events := read_events(run)) and events[-1]["type"] in ("done", "error") and events)


def get_claude_calls(crew):
    path = crew.hc_dir / "claude-calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def is_alive(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ")[1][0] != "Z"
    except (OSError, IndexError):
        return False


def test_start_returns_while_claude_works(crew):
    script_claude(crew, sleep=5)
    started = time.monotonic()
    run = start(crew, "split this window")
    elapsed = time.monotonic() - started
    wait_for(lambda: get_claude_calls(crew))
    crew.run("bar", "cancel", run["id"])
    assert elapsed < 1 and run["events"].endswith(f"{run['id']}.jsonl")


def test_stream_becomes_text_and_done_events(crew):
    script_claude(crew, [text_delta("Split "), text_delta("it."), result("Split it.")])
    events = wait_for_end(start(crew, "split this window"))
    assert "".join(e["text"] for e in events if e["type"] == "text") == "Split it."
    assert events[-1]["type"] == "done" and events[-1]["ok"] is True


def test_claude_runs_locked_down_with_context_in_prompt(crew):
    script_claude(crew, [result("ok")])
    wait_for_end(start(crew, "split this window"))
    [call] = get_claude_calls(crew)
    argv = call["argv"]
    pairs = set(zip(argv, argv[1:]))
    assert {("--tools", "Bash"), ("--allowedTools", "Bash(crew bar-exec *)"), ("--permission-mode", "dontAsk")} <= pairs
    assert "--safe-mode" in argv and argv.count("--allowedTools") == 1
    prompt = Path(argv[argv.index("--system-prompt-file") + 1]).read_text()
    assert '"space": "sp1"' in prompt


def test_cancel_ends_claude(crew):
    script_claude(crew, sleep=30)
    run = start(crew, "what are all agents working on")
    [call] = wait_for(lambda: get_claude_calls(crew))
    crew.run("bar", "cancel", run["id"])
    wait_for(lambda: not is_alive(call["pid"]), timeout=5)
    assert wait_for_end(run)[-1] == {"type": "error", "message": "cancelled"}


def test_prev_puts_previous_exchange_in_prompt(crew):
    script_claude(crew, [text_delta("What name?"), result("What name?")])
    first = start(crew, "rename this space")
    wait_for_end(first)
    wait_for_end(start(crew, "foo", "--prev", first["id"]))
    argv = get_claude_calls(crew)[-1]["argv"]
    prompt = Path(argv[argv.index("--system-prompt-file") + 1]).read_text()
    assert "User: rename this space" in prompt and "You: What name?" in prompt


def test_claude_failure_is_an_error_event(crew):
    script_claude(crew, exit=1, stderr="boom")
    events = wait_for_end(start(crew, "split this window"))
    assert events[-1]["type"] == "error" and "boom" in events[-1]["message"]
