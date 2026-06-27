#!/usr/bin/env bash
# go-folder-finder (sessionizer) binary -> ~/.local/bin, via `go install`.
# Idempotent: re-running upgrades to the latest master.
set -euo pipefail

MOD="github.com/LajnaLegenden/go-folder-finder"   # private repo, default branch: master

if ! command -v go >/dev/null 2>&1; then
  echo "'go' not found — install with: sudo pacman -S go"
  exit 1
fi

export GOPRIVATE="github.com/LajnaLegenden/*"      # private module: skip proxy + checksum db
# go install fetches over HTTPS; rewrite just the LajnaLegenden namespace to SSH (narrow). Idempotent.
if ! git config --global --get url."git@github.com:LajnaLegenden/".insteadOf >/dev/null 2>&1; then
  echo "enabling git https->ssh rewrite for github.com/LajnaLegenden/*"
  git config --global url."git@github.com:LajnaLegenden/".insteadOf "https://github.com/LajnaLegenden/"
fi

# Untagged repo => @latest won't resolve; fall back to the master branch.
GOBIN="$HOME/.local/bin" go install "${MOD}@latest" \
  || GOBIN="$HOME/.local/bin" go install "${MOD}@master"
echo "installed: $(command -v go-folder-finder || echo "$HOME/.local/bin/go-folder-finder")"
