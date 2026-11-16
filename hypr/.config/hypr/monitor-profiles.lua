-- Apply the nwg-displays profile that matches the connected monitors, on login and
-- on every hotplug. Matching and applying live in ~/.local/scripts/monitor-profile,
-- run out of process: it calls hyprctl, which would block on Hyprland from in here.
-- Lid close/open while docked is Omarchy's own clamshell handling, not this.
local monitor_profile = os.getenv("HOME") .. "/.local/scripts/monitor-profile"

o.exec_on_start(monitor_profile)
hl.on("monitor.added", function() hl.exec_cmd(monitor_profile) end)
hl.on("monitor.removed", function() hl.exec_cmd(monitor_profile) end)
