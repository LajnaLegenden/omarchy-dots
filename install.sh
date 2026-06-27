#!/usr/bin/env bash
# Runner: executes every hook in install.d/ in filename order.
# Hooks are independent and idempotent, so this is safe to run on every
# deploy AND every later `git pull` ("each time"). One failing hook doesn't
# block the rest — failures are collected and summarized at the end.
#
# Add setup for a new tool by dropping an executable NN-name.sh into install.d/
# (NN = two-digit order prefix). No edits to this runner needed.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install.d"
[ -d "$DIR" ] || { echo "no install.d/ directory next to install.sh"; exit 1; }

failed=()
for hook in "$DIR"/*.sh; do
  [ -e "$hook" ] || continue            # glob stayed literal => no hooks
  name="$(basename "$hook")"
  echo "==> $name"
  if bash "$hook"; then
    echo "    ok"
  else
    echo "    FAILED"
    failed+=("$name")
  fi
  echo
done

if [ ${#failed[@]} -gt 0 ]; then
  echo "Done with errors in: ${failed[*]}"
  exit 1
fi
echo "Done. Open a new shell (source ~/.bashrc) and start tmux."
