#!/usr/bin/env bash
# Links crew into the live setup. Idempotent. ./install.sh --uninstall reverses it.
set -euo pipefail

REPO="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN_DIR="$HOME/.local/bin"
MODS_DIR="$HOME/.config/herdr-app/mods"
TEMPLATES_DIR="$HOME/.config/herdr-core/templates"
KEYS_FILE="$HOME/.config/herdr-app/keys.json"
MARKETPLACE="crew-local"
declare -A KEYS=(["alt-shift-b"]="mod.open:crew-broadcast" ["ctrl-shift-space"]="mod.open:crew-bar")

link() {
  local source="$1" target="$2"
  if [ -L "$target" ] && [ "$(readlink -f "$target")" = "$(readlink -f "$source")" ]; then return; fi
  if [ -e "$target" ] || [ -L "$target" ]; then
    echo "skip $target (exists, not ours)"
    return
  fi
  mkdir -p "$(dirname "$target")"
  ln -s "$source" "$target"
  echo "linked $target"
}

unlink_ours() {
  local source="$1" target="$2"
  if [ -L "$target" ] && [ "$(readlink -f "$target")" = "$(readlink -f "$source")" ]; then
    rm "$target"
    echo "removed $target"
  fi
}

each_link() {
  local action="$1"
  "$action" "$REPO/bin/crew" "$BIN_DIR/crew"
  "$action" "$REPO/bin/crew-bar-open" "$BIN_DIR/crew-bar-open"
  for mod in "$REPO"/herdr-mods/*/; do
    "$action" "${mod%/}" "$MODS_DIR/$(basename "$mod")"
  done
  for template in "$REPO"/hc-templates/*.md; do
    "$action" "$template" "$TEMPLATES_DIR/$(basename "$template")"
  done
}

merge_keys() {
  [ -f "$KEYS_FILE" ] || return 0
  local tmp
  tmp="$(mktemp)"
  local filter='.'
  for key in "${!KEYS[@]}"; do
    filter+=" | if (.global[\"$key\"] // null) == null then .global[\"$key\"] = \"${KEYS[$key]}\" else . end"
  done
  jq "$filter" "$KEYS_FILE" > "$tmp"
  if cmp -s "$tmp" "$KEYS_FILE"; then rm "$tmp"; return; fi
  cp "$KEYS_FILE" "$KEYS_FILE.crew-backup"
  mv "$tmp" "$KEYS_FILE"
  echo "added Herdr keys (backup: $KEYS_FILE.crew-backup)"
}

remove_keys() {
  [ -f "$KEYS_FILE" ] || return 0
  local tmp filter='.'
  tmp="$(mktemp)"
  for key in "${!KEYS[@]}"; do
    filter+=" | if .global[\"$key\"] == \"${KEYS[$key]}\" then del(.global[\"$key\"]) else . end"
  done
  jq "$filter" "$KEYS_FILE" > "$tmp" && mv "$tmp" "$KEYS_FILE"
}

if [ "${1:-}" = "--uninstall" ]; then
  each_link unlink_ours
  remove_keys
  claude plugin uninstall "crew@$MARKETPLACE" >/dev/null 2>&1 || true
  claude plugin marketplace remove "$MARKETPLACE" >/dev/null 2>&1 || true
  echo "crew uninstalled (state in ~/.local/state/crew kept)"
  exit 0
fi

each_link link
merge_keys
if command -v claude >/dev/null; then
  claude plugin marketplace add "$REPO/claude-plugin" >/dev/null 2>&1 || claude plugin marketplace update "$MARKETPLACE" >/dev/null 2>&1 || true
  claude plugin install "crew@$MARKETPLACE" >/dev/null 2>&1 || true
  claude plugin list 2>/dev/null | grep -q "crew@$MARKETPLACE" && echo "Claude Code plugin crew@$MARKETPLACE installed (new sessions)"
else
  echo "skip Claude Code plugin (claude not found)"
fi
echo "done. Try: crew who"
