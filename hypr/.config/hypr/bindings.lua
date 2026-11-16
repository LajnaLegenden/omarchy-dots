-- Personal keybinding overrides, layered on top of Omarchy's Lua defaults.
-- Omarchy's stock app/webapp bindings come from default.hypr.omarchy, so only
-- genuinely custom bindings belong here.
--
-- See current bindings:  omarchy menu keybindings --print

-- Attach (or create) the "Work" tmux session in a new terminal.
o.bind("SUPER + ALT + RETURN", "Tmux",
  'xdg-terminal-exec --dir="$(omarchy-cmd-terminal-cwd)" bash -c "tmux attach || tmux new -s Work"')

-- Move the current workspace to the next monitor (scripts stow package).
o.bind("SUPER + M", "Move workspace to monitor",
  os.getenv("HOME") .. "/.local/scripts/hypr-move-workspace")

-- Omarchy ships Grok at SUPER+SHIFT+ALT+A; I use Claude instead.
hl.unbind("SUPER + SHIFT + ALT + A")
o.bind("SUPER + SHIFT + ALT + A", "Claude", { webapp = "https://claude.ai" })

-- Omarchy ships HEY for mail and calendar (SUPER+SHIFT+E / ALT+E / C).
-- I'm on Google, so unbind those three defaults and point them at Gmail and
-- Google Calendar. `focus = true` reuses an existing window instead of
-- spawning a second one -- the same treatment Omarchy gives its other Google
-- webapps. Compose stays window-only: it's a throwaway, not a place to return to.
hl.unbind("SUPER + SHIFT + E")
o.bind("SUPER + SHIFT + E", "Email", { webapp = "https://mail.google.com/", focus = true })

hl.unbind("SUPER + SHIFT + ALT + E")
o.bind("SUPER + SHIFT + ALT + E", "New email",
  { webapp = "https://mail.google.com/mail/?view=cm&fs=1&tf=1" })

hl.unbind("SUPER + SHIFT + C")
o.bind("SUPER + SHIFT + C", "Calendar", { webapp = "https://calendar.google.com/", focus = true })

-- Brightness for all monitors at once: DDC backlight where the monitor supports
-- it, software gamma everywhere else. See ~/.local/scripts/monitors-brightness.
o.bind("SUPER + CTRL + UP", "Monitors brightness up",
  os.getenv("HOME") .. "/.local/scripts/monitors-brightness +10", { repeating = true })
o.bind("SUPER + CTRL + DOWN", "Monitors brightness down",
  os.getenv("HOME") .. "/.local/scripts/monitors-brightness -10", { repeating = true })

-- Dictation keys from before Alt + Space and Right Alt became the defaults.
-- Remove these lines to give the keys back to applications.
if o.dictation_installed and o.dictation_installed() then
  o.bind("SUPER + CTRL + X", "Toggle dictation", "omarchy-dictation toggle")
  o.bind_hold("F9", "Start dictation (push-to-talk)", "omarchy-dictation start", "Stop dictation (push-to-talk)", "omarchy-dictation stop")
end
