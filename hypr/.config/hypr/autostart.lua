-- Extra autostart processes, plus the window rules that place them.
o.launch_on_start("1password --silent")
o.launch_on_start("slack.desktop")
o.launch_on_start("claude-desktop")

-- Night light. hyprsunset holds the colour temperature; the actual schedule and
-- the fading live in the omarchy-nightlight-schedule user timer.
o.launch_on_start("hyprsunset")

-- Mouse & keyboard sharing daemon (no systemd unit shipped by the package).
-- Wrapped so a system without lan-mouse installed notifies instead of failing silently.
-- Disabled for now; uncomment to start it again at login.
-- o.launch_on_start("launch-or-notify lan-mouse daemon")

-- Steam, straight to the tray. Wrapped like lan-mouse so a system without Steam
-- notifies instead of failing silently.
o.launch_on_start("launch-or-notify steam -silent")

-- Re-apply the saved monitor brightness (software dimming resets each session).
o.launch_on_start(os.getenv("HOME") .. "/.local/scripts/monitors-brightness restore")

-- Pin those autostarted single-instance Electron apps to fixed workspaces.
-- Class-based because PID-based initial-workspace tracking does not stick to
-- them. `silent` places the window without pulling focus, on every launch.
-- See https://wiki.hypr.land/Configuring/Basics/Window-Rules/
o.window("^(slack)$", { workspace = "9 silent" })
o.window("^(claude-desktop)$", { workspace = "8 silent" })

-- Power the Samsung TV off/on over the network when the other monitors blank and
-- wake, so it never sees the signal drop (which makes it flap the HDMI link).
o.launch_on_start(os.getenv("HOME") .. "/.local/scripts/tv-follow-dpms")

-- Apply the matching nwg-displays monitor profile on login and hotplug.
require("hypr.monitor-profiles")
