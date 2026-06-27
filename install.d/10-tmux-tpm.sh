#!/usr/bin/env bash
# TPM (tmux plugin manager) + the plugins declared in tmux.conf.
# Idempotent: clone if missing (else fast-forward), plugin install repeats safely.
set -euo pipefail

TPM_DIR="$HOME/.tmux/plugins/tpm"
if [ ! -d "$TPM_DIR" ]; then
  echo "cloning TPM into $TPM_DIR"
  git clone --depth 1 https://github.com/tmux-plugins/tpm "$TPM_DIR"
else
  echo "TPM present; updating"
  git -C "$TPM_DIR" pull --ff-only || true
fi

[ -x "$TPM_DIR/bin/install_plugins" ] && "$TPM_DIR/bin/install_plugins"
