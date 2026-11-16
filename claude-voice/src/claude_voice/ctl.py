"""Debug CLI for the voice daemon.

  claude-voice-ctl ping | status | quit
  claude-voice-ctl say TEXT...       speak TEXT (markdown cleanup applied), wait until done
  claude-voice-ctl queue TEXT...     queue TEXT for speaking and return immediately
  claude-voice-ctl ask TEXT...       speak TEXT, chime, print what you answer
  claude-voice-ctl hear TEXT...      pretend TEXT was just heard (wake word logic, injection)
  claude-voice-ctl target PANE       set the tmux pane that prompts are typed into
  claude-voice-ctl session clear|close   ask the user to confirm, then clear/close after the turn
  claude-voice-ctl speech TEXT...    print the speech-cleaned version of TEXT (no daemon)
"""

import json
import os
import sys

from .client import DaemonUnavailable, request
from .speech_text import to_speech


SESSION_DONE = {
    "clear": "Confirmed. The context will be cleared once this turn ends and your reply has been "
    "spoken. End your turn now with a short <speak> block.",
    "close": "Confirmed. The voice session (Claude and Neovim) will close once this turn ends and "
    "your reply has been spoken. End your turn now with a short <speak> goodbye.",
}


def _session(action: str) -> int:
    """Message for Claude on stdout. Exit 0 = confirmed and scheduled, 1 = not confirmed or error."""
    reply = request("session", action=action, pane=os.environ.get("TMUX_PANE"), timeout=None)
    if not reply.get("ok"):
        print(f"Error: {reply.get('error')}. Nothing was done.")
        return 1
    if reply.get("confirmed"):
        print(SESSION_DONE[action])
        return 0
    answer = reply.get("answer")
    if answer is None:
        print("Not confirmed: no answer was heard. Nothing was done.")
    else:
        print(f'Not confirmed. The user said: "{answer}" Nothing was done.')
    return 1


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        sys.exit(0 if len(sys.argv) >= 2 else 1)
    cmd, rest = sys.argv[1], " ".join(sys.argv[2:])
    if cmd == "speech":
        print(to_speech(rest if rest else sys.stdin.read()))
        return
    try:
        if cmd in ("ping", "status", "quit"):
            reply = request(cmd)
        elif cmd == "say":
            reply = request("speak", text=rest, wait=True, timeout=None)
        elif cmd == "queue":
            reply = request("speak", text=rest)
        elif cmd == "ask":
            reply = request("ask", text=rest, timeout=None)
            print(reply.get("answer") or "(no answer)")
            return
        elif cmd == "hear":
            reply = request("hear", text=rest)
        elif cmd == "session":
            sys.exit(_session(rest))
        elif cmd == "target":
            reply = request("target", pane=rest)
        else:
            print(f"unknown command {cmd!r}\n\n{__doc__.strip()}", file=sys.stderr)
            sys.exit(1)
    except DaemonUnavailable as e:
        print(f"daemon not running ({e})", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(reply, indent=2))
    sys.exit(0 if reply.get("ok") else 1)
