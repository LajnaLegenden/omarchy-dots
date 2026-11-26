#!/usr/bin/env bash
# crew: message bus for the coding agents in Herdr, vendored in crew/.
# Its install.sh links the CLI, Herdr mods and hc templates, adds two Herdr
# keys if free, and installs the crew Claude Code plugin. Idempotent.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }

"$REPO/crew/install.sh"
