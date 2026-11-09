#!/usr/bin/env bash
# Python libraries for the lajna.clock shell plugin's calendar helper
# (omarchy-plugins/.config/omarchy/plugins/lajna.clock/calendar_events.py):
#   python-icalendar              -> parses the ICS feeds
#   python-recurring-ical-events  -> expands RRULE/EXDATE/RECURRENCE-ID occurrences
# The helper runs under /usr/bin/python3, so these must be the system packages.
# Idempotent: --needed makes an already-installed package a no-op.
set -euo pipefail

PKGS=(python-icalendar python-recurring-ical-events)

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
