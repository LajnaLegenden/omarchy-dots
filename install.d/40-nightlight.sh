#!/usr/bin/env bash
# Night light fade: enable the user timer that steps hyprsunset's colour
# temperature across sunset/sunrise (see the `nightlight` stow package).
# Symlinks come from `stow nightlight scripts`; this hook only does the part
# a symlink can't — telling systemd about the unit. Idempotent.
set -euo pipefail

UNIT="omarchy-nightlight-schedule.timer"
UNIT_DIR="$HOME/.config/systemd/user"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# On a fresh box ~/.config/systemd/ usually doesn't exist yet, so stow "folds":
# instead of linking the unit files one by one it links the highest missing
# directory straight into this repo. systemctl would then write its *.wants/
# symlinks inside the dotfiles rather than $HOME. Folding can happen at any
# level, so test where the path really lands rather than checking one symlink.
if [ "$(readlink -f "$UNIT_DIR")" = "$REPO/nightlight/.config/systemd/user" ]; then
  echo "unfolding: stow had linked a whole directory into the repo"
  stow -d "$REPO" -t "$HOME" -D nightlight     # remove the folded symlink
  mkdir -p "$UNIT_DIR" "$HOME/.config/omarchy" # real dirs for stow to link into
  stow -d "$REPO" -t "$HOME" nightlight
fi

if [ ! -e "$UNIT_DIR/$UNIT" ]; then
  echo "$UNIT not found — run 'stow nightlight scripts' first"
  exit 1
fi

if ! command -v hyprsunset >/dev/null 2>&1; then
  echo "'hyprsunset' not found — install with: sudo pacman -S hyprsunset"
  exit 1
fi

systemctl --user daemon-reload
systemctl --user enable "$UNIT"

# On a fresh box the hook often runs before Hyprland is up; the timer would
# then just fail every tick with no compositor to talk to. Start it now only
# if there's a graphical session, otherwise leave it to the next login.
if systemctl --user is-active --quiet graphical-session.target; then
  systemctl --user start "$UNIT"
  echo "enabled and started $UNIT"
else
  echo "enabled $UNIT (starts on next login)"
fi

echo "schedule: omarchy-nightlight-schedule schedule"
