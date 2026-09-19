#!/usr/bin/env bash
# Stop the screen locking while something is playing.
#
# Omarchy's idle service already honours Wayland idle inhibitors (its
# IdleMonitor sets respectInhibitors), but on a stock box nothing ever creates
# one: Firefox's wakelock reaches for the org.freedesktop.ScreenSaver /
# org.gnome.SessionManager D-Bus services, and Hyprland provides neither.
# wayland-pipewire-idle-inhibit watches PipeWire instead and holds a real
# inhibitor whenever audio is playing, which covers video, calls and music in
# any app. Idempotent.
set -euo pipefail

PKG="wayland-pipewire-idle-inhibit"          # AUR
UNIT="$PKG.service"                          # ships in /usr/lib/systemd/user/

if ! pacman -Q "$PKG" >/dev/null 2>&1; then
  if ! command -v yay >/dev/null 2>&1; then
    echo "'yay' not found — needed to build $PKG from the AUR"
    exit 1
  fi
  # No --noconfirm: it's an AUR build, so the PKGBUILD is worth a look.
  # Compiles from Rust source, so give it a minute.
  yay -S --needed "$PKG"
fi

if [ ! -e "/usr/lib/systemd/user/$UNIT" ]; then
  echo "$PKG installed but $UNIT is missing — did the package layout change?"
  exit 1
fi

systemctl --user daemon-reload
systemctl --user enable "$UNIT"

# On a fresh box this hook usually runs before Hyprland is up, and the daemon
# needs a compositor to hand its inhibitor to.
if systemctl --user is-active --quiet graphical-session.target; then
  systemctl --user start "$UNIT"
  echo "enabled and started $UNIT"
else
  echo "enabled $UNIT (starts on next login)"
fi
