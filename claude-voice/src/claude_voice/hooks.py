"""Claude Code hook entrypoint: `claude-voice-hook ask|permission|stop|display`, hook JSON on stdin.

Any failure (daemon down, silence) prints nothing, so Claude Code falls back to its normal
on-screen dialog. Keep imports stdlib-only: this runs on every hook event.
"""

import json
import os
import re
import sys
from urllib.parse import urlparse

from .client import DaemonUnavailable, request
from .wake import classify_yes_no

ANSWER_TIMEOUT_S = 45  # per attempt; one repeat, so ~90 s before falling back


def _ask(text: str) -> str | None:
    # Socket timeout: no limit; the daemon gives up after listen_s and the hook timeout caps the rest.
    reply = request(
        "ask", text=text, listen_s=ANSWER_TIMEOUT_S, pane=os.environ.get("TMUX_PANE"), timeout=None
    )
    return reply.get("answer")


def _ask_with_repeat(text: str) -> str | None:
    return _ask(text) or _ask("Sorry, didn't catch that. " + text)


def _speak(text: str) -> None:
    request("speak", text=text)


def _either(labels: list[str]) -> str:
    """'A', 'A or B', 'A, B, or C'."""
    if len(labels) <= 2:
        return " or ".join(labels)
    return ", ".join(labels[:-1]) + ", or " + labels[-1]


def render_question(q: dict, index: int, total: int) -> str:
    """Claude writes the question as spoken, choices included (voice prompt). Labels stay on screen."""
    prefix = "One more thing. " if index > 0 else ""
    question = q.get("question", "").strip()
    if not question:  # nothing to say but the labels
        labels = [o.get("label", "") for o in q.get("options", []) if o.get("label")]
        question = f"{_either(labels)}?" if labels else ""
    return prefix + question


def on_ask(data: dict) -> dict | None:
    tool_input = data.get("tool_input", {})
    questions = tool_input.get("questions", [])
    if not questions:
        return None
    answers: dict[str, str] = {}
    for i, q in enumerate(questions):
        answer = _ask_with_repeat(render_question(q, i, len(questions)))
        if not answer:
            _speak("No worries, I'll leave the question on screen.")
            return None
        answers[q.get("question", "")] = answer
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {**tool_input, "answers": answers},
        }
    }


def _verb_phrase(text: str) -> str:
    """'Run the unit tests.' -> 'run the unit tests' (keeps 'API ...' as is)."""
    text = text.strip().rstrip(".")
    if len(text) > 1 and text[0].isupper() and not text[1].isupper():
        text = text[0].lower() + text[1:]
    return text


def describe_tool(tool: str, ti: dict) -> str:
    """The permission question, as a coworker would ask it."""
    base = lambda p: os.path.basename(str(p)) or str(p)  # noqa: E731
    if tool == "Bash":
        if desc := ti.get("description"):
            return f"Okay if I {_verb_phrase(desc)}?"
        return f"Okay if I run this command: {ti.get('command', '')[:100]}?"
    if tool in ("Edit", "MultiEdit"):
        return f"Okay if I edit {base(ti.get('file_path', 'that file'))}?"
    if tool == "Write":
        return f"Okay if I write {base(ti.get('file_path', 'that file'))}?"
    if tool == "NotebookEdit":
        return f"Okay if I edit the notebook {base(ti.get('notebook_path', ''))}?"
    if tool == "WebFetch":
        return f"Okay if I grab a page from {urlparse(ti.get('url', '')).netloc or 'the web'}?"
    if tool.startswith("mcp__"):
        parts = tool.split("__")
        server = parts[1] if len(parts) > 1 else "an MCP server"
        name = parts[-1].replace("_", " ")
        return f"Okay if I use {name} from {server.replace('_', ' ')}?"
    return f"Okay if I use the {tool} tool?"


def on_permission(data: dict) -> dict | None:
    tool = data.get("tool_name", "")
    if tool in ("AskUserQuestion", "ExitPlanMode"):
        return None
    answer = _ask_with_repeat(describe_tool(tool, data.get("tool_input", {})))
    if not answer:
        _speak("No worries, I'll leave that one on screen.")
        return None
    verdict = classify_yes_no(answer)
    if verdict is True:
        decision: dict = {"behavior": "allow"}
    elif verdict is False:
        decision = {"behavior": "deny", "message": "The user said no (by voice)."}
    else:
        decision = {
            "behavior": "deny",
            "message": f'The user answered by voice instead of approving: "{answer}". '
            "Adjust based on this, or ask if it's unclear.",
        }
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}


def _message_text(msg) -> str:
    if isinstance(msg, str):
        return msg
    if isinstance(msg, dict):
        msg = msg.get("content", "")
        if isinstance(msg, str):
            return msg
    if isinstance(msg, list):
        return "\n".join(b.get("text", "") for b in msg if isinstance(b, dict) and b.get("type") == "text")
    return ""


_SPEAK_BLOCK = re.compile(r"<speak>(.*?)(?:</speak>|\Z)", re.S | re.I)
_SPEAK_TAG = re.compile(r"</?speak>", re.I)


def spoken_part(reply: str) -> str:
    """The <speak> blocks of a reply, or the whole reply if Claude didn't write any."""
    blocks = [b.strip() for b in _SPEAK_BLOCK.findall(reply)]
    return "\n\n".join(b for b in blocks if b) if blocks else reply


def on_stop(data: dict) -> None:
    # Always tell the daemon the turn ended, even with nothing to say: a confirmed
    # voice-session clear/close runs after this.
    text = spoken_part(_message_text(data.get("last_assistant_message"))).strip()
    request("speak", text=text, turn_end=True, pane=os.environ.get("TMUX_PANE"))
    return None


def on_display(data: dict) -> dict | None:
    """Hide <speak> tags on screen; the text inside stays visible."""
    delta = data.get("delta", "")
    if not _SPEAK_TAG.search(delta):
        return None
    kept = [
        _SPEAK_TAG.sub("", line)
        for line in delta.splitlines(keepends=True)
        if not _SPEAK_TAG.fullmatch(line.strip())  # drop lines that were only a tag
    ]
    return {"hookSpecificOutput": {"hookEventName": "MessageDisplay", "displayContent": "".join(kept)}}


HANDLERS = {"ask": on_ask, "permission": on_permission, "stop": on_stop, "display": on_display}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in HANDLERS:
        print(f"usage: claude-voice-hook {{{'|'.join(HANDLERS)}}} < hook.json", file=sys.stderr)
        sys.exit(1)
    data = json.load(sys.stdin)
    try:
        out = HANDLERS[sys.argv[1]](data)
    except DaemonUnavailable:
        out = None
    if out:
        print(json.dumps(out))
