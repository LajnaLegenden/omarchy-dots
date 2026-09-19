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
