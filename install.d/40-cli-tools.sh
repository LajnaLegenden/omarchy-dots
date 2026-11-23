#!/usr/bin/env bash
# CLI tools the shell/git config expects:
#   git-delta -> syntax-highlighted diffs, wired as core.pager in git/.config/git/config
#   git-town  -> stacked-branch PR workflow (`gt` alias, completion in completions.sh)
#   github-cli -> `gh`, used by the herdr-app my-prs mod
#   herdr-app -> Herdr desktop app (omarchy repo) that the herdr-app stow package configures;
#                installed here so it exists before 45-herdr-omarchy.sh runs
# Idempotent: --needed makes an already-installed package a no-op.
set -euo pipefail

PKGS=(git-delta git-town github-cli herdr-app)

if ! command -v pacman >/dev/null 2>&1; then
  echo "not an Arch-based system (no pacman) — install manually: ${PKGS[*]}"
  exit 0
fi

missing=()
for p in "${PKGS[@]}"; do
  pacman -Qq "$p" >/dev/null 2>&1 || missing+=("$p")
done

if [ ${#missing[@]} -eq 0 ]; then
  echo "already installed: ${PKGS[*]}"
  exit 0
fi

echo "installing: ${missing[*]}"
sudo pacman -S --needed --noconfirm "${missing[@]}"
