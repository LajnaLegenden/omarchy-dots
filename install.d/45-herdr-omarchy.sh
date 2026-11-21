#!/usr/bin/env bash
# Herdr app follows Omarchy's theme, font and wallpaper (see the `herdr-app`
# stow package and scripts/.local/scripts/herdr-omarchy-sync). Symlinks come
# from `stow herdr-app scripts`; this hook enables the wallpaper watcher and
# runs one sync. Idempotent.
set -euo pipefail

UNIT="herdr-omarchy-sync.path"
if [ ! -e "$HOME/.config/systemd/user/$UNIT" ]; then
  echo "$UNIT not found — run 'stow herdr-app scripts' first"
  exit 1
fi

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT"
"$HOME/.local/scripts/herdr-omarchy-sync"

# Omarchy renders themed/herdr-app.json.tpl only on a theme switch.
if [ ! -f "$HOME/.local/state/omarchy/current/theme/herdr-app.json" ]; then
  echo "herdr: run 'omarchy theme set <current theme>' once to render its colors"
fi
