#!/usr/bin/env bash
# Post-stow setup for things symlinks can't do:
#   1. TPM (tmux plugin manager) + the plugins declared in tmux.conf
#   2. the go-folder-finder (sessionizer) binary, via `go install`
# Idempotent — safe to re-run.
set -euo pipefail

MOD="github.com/LajnaLegenden/go-folder-finder"   # private repo, default branch: master

# --- TPM (tmux plugin manager) ---------------------------------------------
TPM_DIR="$HOME/.tmux/plugins/tpm"
if [ ! -d "$TPM_DIR" ]; then
  echo "==> Cloning TPM into $TPM_DIR"
  git clone --depth 1 https://github.com/tmux-plugins/tpm "$TPM_DIR"
else
  echo "==> TPM already present, skipping clone"
fi
if [ -x "$TPM_DIR/bin/install_plugins" ]; then
  echo "==> Installing tmux plugins"
  "$TPM_DIR/bin/install_plugins" || echo "   (plugin install reported an issue — run prefix+I inside tmux)"
fi

# --- go-folder-finder (sessionizer) ----------------------------------------
if command -v go >/dev/null 2>&1; then
  echo "==> Installing $MOD into ~/.local/bin"
  export GOPRIVATE="github.com/LajnaLegenden/*"   # private module: skip proxy + checksum db
  # `go install` fetches over HTTPS. For this private repo, rewrite just the
  # LajnaLegenden namespace to SSH (narrow blast radius). Idempotent.
  if ! git config --global --get url."git@github.com:LajnaLegenden/".insteadOf >/dev/null 2>&1; then
    echo "    enabling git https->ssh rewrite for github.com/LajnaLegenden/* (needed to fetch the private module)"
    git config --global url."git@github.com:LajnaLegenden/".insteadOf "https://github.com/LajnaLegenden/"
  fi
  # Repo is untagged, so @latest won't resolve — fall back to the master branch.
  GOBIN="$HOME/.local/bin" go install "${MOD}@latest" \
    || GOBIN="$HOME/.local/bin" go install "${MOD}@master"
  echo "    installed: $(command -v go-folder-finder || echo '~/.local/bin/go-folder-finder')"
else
  echo "!! 'go' not found. Install it, then re-run:  sudo pacman -S go && ./install.sh"
fi

echo
echo "==> Done. Open a new shell (or: source ~/.bashrc), then start tmux."
echo "    Sessionizer: 'ts' from the shell, or prefix+f inside tmux. (needs fzf)"
