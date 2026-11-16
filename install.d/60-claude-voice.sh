#!/usr/bin/env bash
# claude-voice: hands-free voice layer around Claude Code, vendored in
# claude-voice/. Its setup.sh builds the venv, fetches the Kokoro models,
# writes ~/.claude-voice/settings.json and links the launcher into ~/.local/bin.
# Idempotent: setup.sh skips models it already has and merges settings.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v uv >/dev/null || { echo "uv not found — sudo pacman -S uv"; exit 1; }

"$REPO/claude-voice/setup.sh"
