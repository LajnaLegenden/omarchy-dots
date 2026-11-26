import importlib.util
import json

import pytest

from conftest import agent

has_broadcast = importlib.util.find_spec("crew.broadcast") is not None


def in_bar(crew, answer=None):
    crew.monkeypatch.setenv("CREW_BAR_RUN", "b-test")
    if answer:
        crew.run("bar", "answer", "b-test", "1", answer)


def get_events(crew):
    path = crew.state_dir / "bar" / "b-test.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def get_herdr_do_calls(crew):
    path = crew.hc_dir / "herdr_calls.jsonl"
    calls = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [call for call in calls if call[0] == "do"]


def test_passes_hc_ls_through(crew):
    crew.set_terminals([agent("t1")])
    code, out, _ = crew.run("bar-exec", "hc", "ls", "--json")
    assert code == 0 and json.loads(out)["terminals"][0]["address"] == "t1"


def test_hc_send_is_not_allowed(crew):
    code, _, err = crew.run("bar-exec", "hc", "send", "t1", "x")
    assert code == 2 and "not allowed" in err
    assert crew.calls() == []


def test_pane_split_runs_without_asking(crew):
    in_bar(crew)
    code, _, _ = crew.run("bar-exec", "herdr-app", "do", "pane.split", "--direction", "right")
    assert code == 0 and get_herdr_do_calls(crew) == [["do", "pane.split", "--direction", "right"]]
    assert [e["type"] for e in get_events(crew)] == ["action"]


def test_space_close_runs_confirmed_after_yes(crew):
    in_bar(crew, answer="yes")
    crew.run("bar-exec", "herdr-app", "do", "space.close", "--id", "sp1")
    assert [(e["type"], e.get("status")) for e in get_events(crew)] == [("confirm", None), ("action", "ran")]
    assert get_herdr_do_calls(crew) == [["do", "space.close", "--id", "sp1", "--confirmed", "true"]]


def test_space_close_answered_no_does_not_run(crew):
    in_bar(crew, answer="no")
    crew.run("bar-exec", "herdr-app", "do", "space.close", "--id", "sp1")
    assert get_events(crew)[-1]["status"] == "denied" and get_herdr_do_calls(crew) == []


def test_unanswered_confirm_times_out(crew):
    in_bar(crew)
    crew.monkeypatch.setenv("CREW_BAR_CONFIRM_S", "0.2")
    code, _, _ = crew.run("bar-exec", "herdr-app", "do", "tab.close", "--id", "tb1")
    assert code == 1 and get_events(crew)[-1]["status"] == "timeout"


def test_confirm_outside_the_bar_is_refused(crew):
    code, _, _ = crew.run("bar-exec", "herdr-app", "do", "space.close", "--id", "sp1")
    assert code == 2 and get_herdr_do_calls(crew) == []


def test_confirm_names_the_space(crew):
    space = {"id": "sp1", "name": "nordpil", "tabs": [{"id": "tb1", "name": "1", "terminals": []}]}
    (crew.hc_dir / "herdr-ls.json").write_text(json.dumps({"spaces": [space]}))
    in_bar(crew, answer="no")
    crew.run("bar-exec", "herdr-app", "do", "space.close", "--id", "sp1")
    assert "nordpil" in get_events(crew)[0]["detail"]


def test_unknown_herdr_command_asks_first(crew):
    in_bar(crew, answer="no")
    crew.run("bar-exec", "herdr-app", "do", "app.something_new")
    assert get_events(crew)[0]["type"] == "confirm"


def test_starting_a_program_asks_first(crew):
    in_bar(crew, answer="no")
    crew.run("bar-exec", "herdr-app", "do", "tab.new", "--argv", '["bash", "-c", "rm -rf ~"]')
    assert get_events(crew)[0]["type"] == "confirm" and get_herdr_do_calls(crew) == []


@pytest.mark.skipif(not has_broadcast, reason="crew broadcast not built yet")
def test_broadcast_confirm_lists_dry_run_targets(crew):
    crew.set_terminals([agent("t5"), agent("t6")])
    in_bar(crew, answer="no")
    crew.run("bar-exec", "crew", "broadcast", "--all", "wrap up")
    confirm = get_events(crew)[0]
    assert confirm["type"] == "confirm" and "t5" in confirm["detail"] and "t6" in confirm["detail"]
    assert crew.calls("send") == []


@pytest.mark.skipif(not has_broadcast, reason="crew broadcast not built yet")
def test_preset_broadcast_asks_for_replies_instead_of_waiting(crew):
    crew.set_terminals([agent("t5")])
    in_bar(crew, answer="yes")
    code, _, _ = crew.run("bar-exec", "crew", "broadcast", "--all", "--preset", "shutdown")
    assert code == 0 and "--reply" in get_events(crew)[-1]["argv"]
    assert len(crew.calls("send")) == 1


@pytest.mark.parametrize("args", [
    ["tab.new", '{"mod":"worktree","props":{"folder":"/r","argv":["sh","-c","x"]}}'],
    ["pane.split", "--direction", "right", "--mod", "worktree", "--props", '{"action":"remove"}'],
    ["tab.new", "--props", '{"nested":{"task":"x"}}'],
    ["pane.split", "right"],
    ["terminal.open:sh"],
])
def test_launching_or_unparsed_herdr_calls_ask_first(crew, args):
    in_bar(crew, answer="no")
    crew.run("bar-exec", "herdr-app", "do", *args)
    assert get_events(crew)[0]["type"] == "confirm" and get_herdr_do_calls(crew) == []


def test_display_mod_tab_runs_without_asking(crew):
    in_bar(crew)
    crew.run("bar-exec", "herdr-app", "do", "tab.new", "--mod", "crew-office", "--props", '{"office":"x"}')
    assert len(get_herdr_do_calls(crew)) == 1


@pytest.mark.skipif(not has_broadcast, reason="needs crew.broadcast")
def test_abbreviated_collect_is_refused(crew):
    in_bar(crew)
    code, _, _ = crew.run("bar-exec", "crew", "broadcast", "--all", "--coll", "x")
    assert code == 2 and crew.calls("send") == []


def test_message_too_long_to_review_is_refused(crew):
    crew.set_terminals([agent("t7")])
    in_bar(crew, answer="yes")
    code, _, err = crew.run("bar-exec", "crew", "send", "t7", "x" * 5000)
    assert code == 2 and "too long" in err and crew.calls("send") == []
