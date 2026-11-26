import json
from pathlib import Path

PLUGIN = Path(__file__).parent.parent / "claude-plugin"


def test_guide_prints_skill_without_frontmatter(crew):
    _, out, _ = crew.run("guide")
    assert out.startswith("# crew") and "name: crew" not in out


def test_session_context_is_silent_outside_hc(crew):
    _, out, _ = crew.run("guide", "--session")
    assert out == ""


def test_session_context_names_the_agent(crew):
    crew.be("t7")
    _, out, _ = crew.run("guide", "--session")
    assert "agent t7" in out and len(out.splitlines()) <= 6


def test_plugin_manifests_parse_and_hook_runs_crew():
    hooks = json.loads((PLUGIN / "crew" / "hooks" / "hooks.json").read_text())
    json.loads((PLUGIN / ".claude-plugin" / "marketplace.json").read_text())
    assert "crew guide --session" in hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
