#!/usr/bin/env bash
# One-time setup: venv, models, ~/.claude-voice config, launcher on PATH. Safe to re-run.
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
CONFIG_DIR="${CLAUDE_VOICE_CONFIG_DIR:-$HOME/.claude-voice}"
MODELS="${CLAUDE_VOICE_MODELS:-$HOME/.local/share/claude-voice/models}"
KOKORO_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

echo "==> Python env"
(cd "$ROOT" && uv sync -q)

echo "==> Models in $MODELS"
mkdir -p "$MODELS"
for f in kokoro-v1.0.int8.onnx voices-v1.0.bin; do
  [ -f "$MODELS/$f" ] || curl -fSL --progress-bar -o "$MODELS/$f" "$KOKORO_URL/$f"
done
"$ROOT/.venv/bin/python" -c "
from claude_voice.engines import STT
from claude_voice.config import load_settings
STT(load_settings().stt_model)
" 2>/dev/null

echo "==> Config in $CONFIG_DIR"
mkdir -p "$CONFIG_DIR"
# Merge: our hooks replace the "hooks" key, our allow rules are added, everything else
# (theme, tui, rules Claude Code saved) is kept.
settings="$CONFIG_DIR/settings.json"
[ -f "$settings" ] && cp "$settings" "$settings.bak"
sed "s|@ROOT@|$ROOT|g" "$ROOT/config/settings.json" | python3 -c '
import json, sys
path = sys.argv[1]
ours = json.load(sys.stdin)
try:
    current = json.load(open(path))
except FileNotFoundError:
    current = {}
perms = current.setdefault("permissions", {})
perms["defaultMode"] = ours["permissions"]["defaultMode"]
allow = perms.setdefault("allow", [])
allow += [rule for rule in ours["permissions"]["allow"] if rule not in allow]
current["hooks"] = ours["hooks"]
json.dump(current, open(path, "w"), indent=2)
open(path, "a").write("\n")
' "$settings"

# Your global CLAUDE.md minus the "## Response Style" section (caveman mode doesn't suit speech).
if [ ! -f "$CONFIG_DIR/CLAUDE.md" ] && [ -f "$HOME/.claude/CLAUDE.md" ]; then
  awk '/^## /{skip = ($0 == "## Response Style")} !skip' "$HOME/.claude/CLAUDE.md" >"$CONFIG_DIR/CLAUDE.md"
  echo "    CLAUDE.md copied from ~/.claude (without Response Style)"
fi

echo "==> Launcher + helpers in ~/.local/bin"
# Helpers must be on the PATH from your shell profile: Claude's Bash tool rebuilds PATH from it,
# so a PATH set only on the tmux pane is lost.
mkdir -p "$HOME/.local/bin"
chmod +x "$ROOT/bin/"*
for cmd in claude-voice voice-show voice-say voice-session; do
  ln -sf "$ROOT/bin/$cmd" "$HOME/.local/bin/$cmd"
done

cat <<EOF

Done. One manual step left: log in once inside the separate config:

    CLAUDE_CONFIG_DIR=$CONFIG_DIR claude      # then run /login, pick theme, exit

Then start a session in any project:  claude-voice [dir]
EOF
