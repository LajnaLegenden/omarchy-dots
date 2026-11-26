import subprocess
import threading
import time

from conftest import agent, shell

from crew import store


def addresses(out):
    return [target["address"] for target in out["targets"]]


def reply_when_sent(crew, *senders):
    messages_dir = crew.state_dir / "messages"

    def reply():
        deadline = time.monotonic() + 5
        while not list(messages_dir.glob("*.json")) and time.monotonic() < deadline:
            time.sleep(0.05)
        [envelope] = messages_dir.glob("*.json")
        for sender in senders:
            record = {"id": f"r-{sender}", "msg": envelope.stem, "from": sender, "text": "safe", "at": "now"}
            store.append_record(crew.state_dir / "replies" / f"{envelope.stem}.jsonl", record)

    threading.Thread(target=reply, daemon=True).start()


def test_no_selector_exits_2_without_asking_hc(crew):
    code, _, _ = crew.run("broadcast", "hello")
    assert (code, crew.calls()) == (2, [])


def test_preset_and_text_exits_2(crew):
    code, _, _ = crew.run("broadcast", "--all", "--preset", "pause", "hello")
    assert code == 2


def test_dry_run_sends_and_writes_nothing(crew):
    crew.set_terminals([agent("t7")])
    code, out, _ = crew.run_json("broadcast", "--all", "--dry-run", "hello")
    assert (code, out["id"], out["targets"][0]["delivery"]) == (0, None, "would-send")
    assert crew.calls("send") == [] and not (crew.state_dir / "messages").exists()


def test_all_skips_self_and_shells(crew):
    crew.set_terminals([agent("t1"), agent("t2"), shell("t3")])
    crew.be("t1")
    code, out, _ = crew.run_json("broadcast", "--all", "hello")
    assert (code, addresses(out), out["replies_path"]) == (0, ["t2"], None)
    assert [call[1] for call in crew.calls("send")] == ["t2"]


def test_blocked_target_is_skipped_and_exits_1(crew):
    crew.set_terminals([agent("t1"), agent("t2", status="blocked")])
    code, out, _ = crew.run_json("broadcast", "--all", "hello")
    assert code == 1
    assert [(t["delivery"], t["reason"]) for t in out["targets"]] == [("sent", None), ("skipped", "blocked")]


def test_no_match_exits_3(crew):
    crew.set_terminals([agent("t1")])
    code, _, _ = crew.run("broadcast", "--space", "nowhere", "hello")
    assert code == 3


def test_unknown_to_is_skipped_as_not_found(crew):
    crew.set_terminals([agent("t1")])
    _, out, _ = crew.run_json("broadcast", "--to", "t1,t9", "--dry-run", "hello")
    assert [(t["address"], t["reason"]) for t in out["targets"]] == [("t1", None), ("t9", "not-found")]


def test_space_ignores_case_and_emoji(crew):
    crew.set_terminals([agent("t1", where="🎬 MediaTool / 1"), agent("t2", where="crew / 1")])
    _, out, _ = crew.run_json("broadcast", "--space", "mediatool", "--dry-run", "hello")
    assert addresses(out) == ["t1"]


def test_cwd_matches_whole_path_components(crew):
    crew.set_terminals([agent("t1", cwd="/a/b/c"), agent("t2", cwd="/a/bc"), agent("t3", cwd="/a/b")])
    _, out, _ = crew.run_json("broadcast", "--cwd", "/a/b", "--dry-run", "hello")
    assert addresses(out) == ["t1", "t3"]


def test_status_filter(crew):
    crew.set_terminals([agent("t1", status="working"), agent("t2", status="idle"), agent("t3", status="done")])
    _, out, _ = crew.run_json("broadcast", "--status", "idle,done", "--dry-run", "hello")
    assert addresses(out) == ["t2", "t3"]


def test_repo_matches_worktree_by_origin_or_main_checkout(crew):
    main, worktree = crew.root / "src" / "main-folder", crew.root / "worktrees" / "fix-login"

    def git(*args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)

    git("init", "-q", str(main))
    git("-C", str(main), "commit", "-q", "--allow-empty", "-m", "init")
    git("-C", str(main), "remote", "add", "origin", "git@github.com:me/media-tool.git")
    git("-C", str(main), "worktree", "add", "-q", str(worktree))
    crew.set_terminals([agent("t1", cwd=str(worktree)), agent("t2", cwd=str(crew.root))])
    _, by_origin, _ = crew.run_json("broadcast", "--repo", "media-tool", "--dry-run", "hello")
    _, by_folder, _ = crew.run_json("broadcast", "--repo", "main-folder", "--dry-run", "hello")
    assert addresses(by_origin) == addresses(by_folder) == ["t1"]


def test_collect_returns_once_everyone_replied(crew):
    crew.set_terminals([agent("t1"), agent("t2")])
    reply_when_sent(crew, "t1", "t2")
    code, out, _ = crew.run_json("broadcast", "--all", "--collect", "--timeout", "5", "hello")
    assert (code, out["summary"]["replied"], out["targets"][0]["reply"]["text"]) == (0, 2, "safe")


def test_collect_timeout_reports_missing(crew):
    crew.set_terminals([agent("t1")])
    code, out, _ = crew.run_json("broadcast", "--all", "--collect", "--timeout", "0.5", "hello")
    assert (code, out["summary"]["timed_out"], out["targets"][0]["reply"]) == (1, True, None)


def test_presets_lists_three(crew):
    _, out, _ = crew.run_json("broadcast", "--presets")
    assert [p["name"] for p in out["presets"]] == ["shutdown", "status", "pause"]


def test_all_includes_agents_on_connected_machines(crew):
    crew.set_terminals([agent("t1"), agent("laptop/t4")])
    _, out, _ = crew.run_json("broadcast", "--all", "--dry-run", "x")
    assert [t["address"] for t in out["targets"]] == ["t1", "laptop/t4"]
