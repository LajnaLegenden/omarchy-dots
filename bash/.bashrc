# ~/.bashrc — personal overrides layered on top of Omarchy's defaults.
#
# Order matters: source Omarchy's stock bash config FIRST (so `omarchy update`
# stays authoritative over the base shell), then load my own aliases/functions
# LAST so they win. Both lines are guarded, so this file is also harmless on a
# plain Arch box where Omarchy isn't installed.

# Omarchy environment (sets OMARCHY_PATH + PATH); needed even for non-interactive shells
[ -r /usr/share/omarchy/default/bash/env-bootstrap ] && source /usr/share/omarchy/default/bash/env-bootstrap

# Make sure ~/.local/bin (where ./install.sh drops go-folder-finder) is on PATH.
# Omarchy already does this; the guard keeps it correct on plain Arch too.
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac

# ~/.local/scripts — the `scripts` stow package (e.g. hypr-move-workspace).
case ":$PATH:" in *":$HOME/.local/scripts:"*) ;; *) export PATH="$HOME/.local/scripts:$PATH" ;; esac

# If not running interactively, stop here (leave this above the rc source)
[[ $- != *i* ]] && return

# Omarchy's stock bash config (no-op if not on an Omarchy machine)
[ -r "$OMARCHY_PATH/default/bash/rc" ] && source "$OMARCHY_PATH/default/bash/rc"

# My shell overrides, in dependency order. Everything here runs AFTER Omarchy's
# `default/bash/rc` above, which is what makes the overrides stick:
#   - history.sh's HISTSIZE beats default/bash/shell's
#   - options.sh's `bind` calls land after default/bash/rc's final `bind -f`
#   - completions.sh needs `alias g='git'` and fzf's completion.bash to exist
[ -f ~/.config/shell/env.sh ] && source ~/.config/shell/env.sh
[ -f ~/.config/shell/aliases.sh ] && source ~/.config/shell/aliases.sh
[ -f ~/.config/shell/functions.sh ] && source ~/.config/shell/functions.sh
[ -f ~/.config/shell/history.sh ] && source ~/.config/shell/history.sh
[ -f ~/.config/shell/options.sh ] && source ~/.config/shell/options.sh
[ -f ~/.config/shell/completions.sh ] && source ~/.config/shell/completions.sh

# fnm
FNM_PATH="/home/lajna/.local/share/fnm"
if [ -d "$FNM_PATH" ]; then
  export PATH="$FNM_PATH:$PATH"
  eval "$(fnm env --shell bash)"
fi

# fnm
FNM_PATH="/home/lajna/.local/share/fnm"
if [ -d "$FNM_PATH" ]; then
  export PATH="$FNM_PATH:$PATH"
  eval "$(fnm env --shell bash)"
fi
