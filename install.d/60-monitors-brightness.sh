#!/usr/bin/env bash
# Packages for scripts/.local/scripts/monitors-brightness (Super+Ctrl+Up/Down).
#
# ddcutil drives the backlight on monitors that speak DDC/CI; wl-gammarelay-rs
# dims everything else (TVs, monitors without DDC) in software, one output at a
# time. The script starts the relay itself, and autostart.lua re-applies the
# saved level at login, so there is no service to enable here. Idempotent.
set -euo pipefail

if ! pacman -Q ddcutil >/dev/null 2>&1; then
  sudo pacman -S --needed ddcutil
fi

PKG="wl-gammarelay-rs"                       # AUR
if ! pacman -Q "$PKG" >/dev/null 2>&1; then
  if ! command -v yay >/dev/null 2>&1; then
    echo "'yay' not found — needed to build $PKG from the AUR"
    exit 1
  fi
  # No --noconfirm: it's an AUR build, so the PKGBUILD is worth a look.
  # Compiles from Rust source, so give it a minute.
  yay -S --needed "$PKG"
fi

# ddcutil talks to monitors through /dev/i2c-*, which needs the i2c-dev module.
if ! lsmod | grep -q '^i2c_dev'; then
  echo i2c-dev | sudo tee /etc/modules-load.d/i2c-dev.conf >/dev/null
  sudo modprobe i2c-dev
fi
