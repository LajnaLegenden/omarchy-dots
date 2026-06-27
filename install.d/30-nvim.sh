#!/usr/bin/env bash
# Neovim config (private kickstart fork): clone to ~/Personal/nvim and point
# ~/.config/nvim at it. Mirrors the home-manager setup.
# Idempotent: clone only if missing (never touches local changes on re-run);
# (re)create the symlink only when it's not already correct.
set -euo pipefail

REPO="git@github.com:LajnaLegenden/nvim.git"
DEST="$HOME/Personal/nvim"
LINK="$HOME/.config/nvim"

if [ ! -d "$DEST/.git" ]; then
  echo "cloning nvim config into $DEST"
  mkdir -p "$(dirname "$DEST")"
  git clone "$REPO" "$DEST"
else
  echo "nvim config present at $DEST (leaving it untouched)"
fi

if [ "$(readlink "$LINK" 2>/dev/null)" != "$DEST" ]; then
  if [ -e "$LINK" ] || [ -L "$LINK" ]; then
    echo "backing up existing $LINK -> $LINK.bak"
    mv "$LINK" "$LINK.bak"
  fi
  mkdir -p "$(dirname "$LINK")"
  ln -s "$DEST" "$LINK"
  echo "symlinked $LINK -> $DEST"
fi
echo "plugins install on first 'nvim' launch (lazy.nvim bootstraps automatically)"
