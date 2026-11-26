from conftest import agent, shell


def test_lists_agents_and_hides_shells(crew):
    crew.set_terminals([agent("t1"), agent("t2", agent="codex"), shell("t3")])
    code, out, _ = crew.run_json("who")
    assert code == 0
    assert [a["address"] for a in out["agents"]] == ["t1", "t2"]


def test_status_string_passes_through(crew):
    crew.set_terminals([agent("t1", status="working")])
    _, out, _ = crew.run_json("who")
    assert out["agents"][0]["status"] == "working"


def test_self_reported_task_shows_in_who(crew):
    crew.set_terminals([agent("t7")])
    crew.be("t7")
    crew.run("status", "fixing login")
    _, out, _ = crew.run_json("who")
    assert out["agents"][0]["task"] == "fixing login"


def test_status_clear_removes_task(crew):
    crew.set_terminals([agent("t7")])
    crew.be("t7")
    crew.run("status", "x")
    crew.run("status", "--clear")
    _, out, _ = crew.run_json("who")
    assert out["agents"][0]["task"] is None


def test_task_of_dead_terminal_is_pruned(crew):
    crew.set_terminals([agent("t7"), agent("t9")])
    crew.be("t9")
    crew.run("status", "x")
    crew.set_terminals([agent("t7")])
    crew.run("who")
    assert not (crew.state_dir / "agents" / "t9.json").exists()


def test_status_as_human_fails(crew):
    code, _, err = crew.run("status", "x")
    assert code == 1
    assert "agent" in err


def test_shell_child_of_agent_speaks_as_the_agent(crew):
    crew.set_terminals([agent("t7"), shell("t20", parent="t7")])
    crew.be("t20")
    crew.run("status", "building")
    assert (crew.state_dir / "agents" / "t7.json").exists()


def test_lists_agents_on_connected_machines(crew):
    crew.set_terminals([agent("t1"), agent("laptop/t4"), shell("laptop/t5")])
    _, out, _ = crew.run_json("who")
    assert [(a["address"], a["machine"]) for a in out["agents"]] == [("t1", None), ("laptop/t4", "laptop")]
