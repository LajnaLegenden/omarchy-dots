# ~/.bashrc — personal overrides layered on top of Omarchy's defaults.
#
# Order matters: source Omarchy's stock bash config FIRST (so `omarchy update`
# stays authoritative over the base shell), then load my own aliases/functions
# LAST so they win. Both lines are guarded, so this file is also harmless on a
# plain Arch box where Omarchy isn't installed.

# Omarchy defaults (no-op if not on an Omarchy machine)
[ -f ~/.local/share/omarchy/default/bash/rc ] && source ~/.local/share/omarchy/default/bash/rc

# Make sure ~/.local/bin (where ./install.sh drops go-folder-finder) is on PATH.
# Omarchy already does this; the guard keeps it correct on plain Arch too.
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac

# My shell overrides — aliases shared across bash/zsh/fish live in one file.
[ -f ~/.config/shell/aliases.sh ] && source ~/.config/shell/aliases.sh
