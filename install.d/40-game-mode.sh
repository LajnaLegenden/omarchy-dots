#!/usr/bin/env bash
# Game mode: enable the user service that stops the local AI services
# (llama-server, voicemode) while a Steam game runs, freeing VRAM.
# Symlinks come from `stow game-mode scripts`; this hook only tells systemd
# about the unit. Idempotent.
set -euo pipefail

UNIT="game-mode-ai.service"
UNIT_DIR="$HOME/.config/systemd/user"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Same stow folding trap as 40-nightlight.sh: if ~/.config/systemd/user is a
# link into this package, systemctl would write *.wants/ into the repo.
if [ "$(readlink -f "$UNIT_DIR")" = "$REPO/game-mode/.config/systemd/user" ]; then
  echo "unfolding: stow had linked a whole directory into the repo"
  stow -d "$REPO" -t "$HOME" -D game-mode
  mkdir -p "$UNIT_DIR"
  stow -d "$REPO" -t "$HOME" game-mode
fi

if [ ! -e "$UNIT_DIR/$UNIT" ]; then
  echo "$UNIT not found — run 'stow game-mode scripts' first"
  exit 1
fi

systemctl --user daemon-reload
systemctl --user enable "$UNIT"

if systemctl --user is-active --quiet graphical-session.target; then
  systemctl --user start "$UNIT"
  echo "enabled and started $UNIT"
else
  echo "enabled $UNIT (starts on next login)"
fi
