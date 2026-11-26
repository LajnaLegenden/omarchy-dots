import json
import os
import subprocess
import time
from datetime import timedelta
from pathlib import Path

from conftest import agent

from crew import office, store

ROLES = ["pm", "ux-designer", "ux-reviewer", "developer", "tester"]
MEMBERS = [agent(f"t9{n}", name=f"demo-{role}") for n, role in enumerate(ROLES, 1)]


def trust(*paths):
    home = Path(os.environ["HOME"])
    home.mkdir(exist_ok=True)
    projects = {str(path): {"hasTrustDialogAccepted": True} for path in paths}
    (home / ".claude.json").write_text(json.dumps({"projects": projects}))


def start(crew, *extra):
    project = crew.root / "project"
    project.mkdir(exist_ok=True)
    trust(project)
    crew.set_terminals(MEMBERS)
    return crew.run("office", "start", "demo", "--dir", str(project), *extra)


def get_office(crew):
    return store.get_json(crew.state_dir / "offices" / "demo.json")


def get_posts(crew):
    return store.get_records(crew.state_dir / "channels" / "demo.jsonl")


def post_as(crew, address, text):
    crew.be(address)
    _, out, _ = crew.run_json("post", "demo", text)
    return out["deliveries"]


def test_start_runs_five_role_agents_in_one_herdr_space(crew):
    code, _, _ = start(crew)
    runs = crew.calls("run")
    assert (code, list(get_office(crew)["members"])) == (0, ROLES)
    assert [run[run.index("--") + 1] for run in runs] == [f"office-{role}" for role in ROLES]
    assert all("herdr.space=crew-demo" in run for run in runs)


def test_start_opens_the_office_view_in_herdr(crew):
    start(crew)
    calls = [json.loads(line) for line in (crew.hc_dir / "herdr_calls.jsonl").read_text().splitlines()]
    new_tab = next(json.loads(call[2]) for call in calls if call[1] == "tab.new")
    assert new_tab == {"space": "crew-demo", "name": "office", "mod": "crew-office", "props": {"office": "demo"}}


def test_start_posts_the_brief_to_pm(crew):
    start(crew, "--brief", "build a todo app")
    [[_, address, wire]] = crew.calls("send")
    assert address == "t91" and "@pm build a todo app" in wire


def test_untrusted_dir_starts_nothing(crew):
    (crew.root / "project").mkdir()
    code, _, _ = crew.run("office", "start", "demo", "--dir", str(crew.root / "project"))
    assert (code, crew.calls("run"), get_office(crew)) == (1, [], None)


def test_plain_subfolder_of_a_trusted_folder_is_untrusted(crew):
    (crew.root / "work" / "project").mkdir(parents=True)
    trust(crew.root / "work")
    code, _, _ = crew.run("office", "start", "demo", "--dir", str(crew.root / "work" / "project"))
    assert (code, crew.calls("run")) == (1, [])


def test_git_repo_gets_a_worktree_trusted_through_the_repo(crew):
    repo = crew.root / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    trust(repo)
    crew.set_terminals(MEMBERS)
    code, _, _ = crew.run("office", "start", "demo", "--dir", str(repo))
    worktree = Path(os.environ["HOME"]) / ".herdr" / "worktrees" / "repo" / "office-demo"
    branch = subprocess.run(["git", "-C", str(worktree), "branch", "--show-current"], check=False, capture_output=True, text=True).stdout
    assert (code, get_office(crew)["cwd"], branch.strip()) == (0, str(worktree), "office/demo")
    assert (worktree / ".office" / "brief.md").exists()


def test_role_mention_reaches_that_member(crew):
    start(crew)
    post_as(crew, "t91", "@developer build it")
    assert [call[1] for call in crew.calls("send")] == ["t94"]


def test_team_mention_reaches_everyone_but_the_poster(crew):
    start(crew)
    post_as(crew, "t91", "@team standup")
    assert sorted(call[1] for call in crew.calls("send")) == ["t92", "t93", "t94", "t95"]


def test_paused_office_logs_but_does_not_deliver(crew):
    start(crew)
    crew.run("office", "pause", "demo")
    deliveries = post_as(crew, None, "@pm hello")
    assert (deliveries[0]["reason"], crew.calls("send")) == ("paused", [])


def test_hop_budget_pauses_the_office(crew):
    start(crew, "--budget", "3")
    for address, text in (("t91", "@developer go"), ("t94", "@tester go"), ("t95", "@pm go")):
        post_as(crew, address, text)
    deliveries = post_as(crew, "t91", "@ux-designer go")
    system_post = get_posts(crew)[-2]
    assert (system_post["from"], system_post["text"][:15]) == ("crew", "Paused after 3 ")
    assert (deliveries[0]["reason"], len(crew.calls("send"))) == ("paused", 2)


def test_human_post_resets_the_hop_counter(crew):
    start(crew, "--budget", "3")
    post_as(crew, "t91", "@developer go")
    post_as(crew, "t94", "@tester go")
    post_as(crew, None, "@pm status?")
    assert get_office(crew)["agent_posts_since_human"] == 0


def test_same_pair_within_cooldown_is_delayed_not_dropped(crew, monkeypatch):
    monkeypatch.setattr(office, "PAIR_COOLDOWN", timedelta(seconds=0.4))
    start(crew)
    post_as(crew, "t91", "@developer one")
    started = time.monotonic()
    deliveries = post_as(crew, "t91", "@developer two")
    assert deliveries[0]["status"] == "sent" and time.monotonic() - started >= 0.2


def test_resume_sends_each_member_a_digest_of_missed_mentions(crew):
    start(crew)
    crew.run("office", "pause", "demo")
    for text in ("@developer first", "@developer second", "@tester third"):
        crew.run("post", "demo", text)
    crew.run("office", "resume", "demo")
    sends = {address: wire for _, address, wire in crew.calls("send")}
    assert sorted(sends) == ["t94", "t95"]
    assert "first" in sends["t94"] and "second" in sends["t94"]


def test_stop_kills_members_and_marks_stopped(crew):
    start(crew)
    crew.run("office", "stop", "demo")
    assert sorted(call[1] for call in crew.calls("kill")) == ["t91", "t92", "t93", "t94", "t95"]
    assert get_office(crew)["state"] == "stopped"


def test_missing_dir_exits_3(crew):
    code, _, _ = crew.run("office", "start", "demo", "--dir", str(crew.root / "nope"))
    assert code == 3


def test_duplicate_running_office_exits_1(crew):
    start(crew)
    code, _, _ = start(crew)
    assert (code, len(crew.calls("run"))) == (1, 5)


def test_member_that_fell_back_to_a_shell_gets_nothing(crew):
    start(crew)
    crew.set_terminals([*MEMBERS[:3], {**MEMBERS[3], "agent": "bash", "status": None}, MEMBERS[4]])
    deliveries = post_as(crew, None, "@developer are you there?")
    assert deliveries == [] and all(call[1] != "t94" for call in crew.calls("send"))


def test_members_cannot_post_outside_their_office(crew):
    start(crew)
    crew.be("t91")
    code, _, err = crew.run("post", "general", "@all hi")
    assert code == 2 and "office" in err


def test_pair_cooldown_wait_is_capped(crew, monkeypatch):
    monkeypatch.setattr(office, "PAIR_COOLDOWN", timedelta(seconds=0.3))
    start(crew)
    for text in ("one", "two"):
        post_as(crew, "t91", f"@developer {text}")
    started = time.monotonic()
    post_as(crew, "t91", "@developer three")
    assert time.monotonic() - started < 0.45
