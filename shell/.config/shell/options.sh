# Shell + readline options.
#
# MUST be sourced AFTER $OMARCHY_PATH/default/bash/rc. That file's LAST
# line is `bind -f $OMARCHY_PATH/default/bash/inputrc`, which runs after
# readline has already read ~/.inputrc at startup. So a ~/.inputrc of our own
# would be silently clobbered -- readline overrides have to be `bind` calls from
# here, where they land after Omarchy's.
#
# Already set by Omarchy's inputrc (do not duplicate): completion-ignore-case,
# completion-prefix-display-length, show-all-if-ambiguous, show-all-if-unmodified,
# mark-symlinked-directories, match-hidden-files off, page-completions off,
# completion-query-items, visible-stats, skip-completed-text, colored-stats,
# TAB: menu-complete, menu-complete-display-prefix, and history-search on Up/Down.

[[ $- == *i* ]] || return 0

# --- shell options -----------------------------------------------------------
shopt -s cdspell                # fix minor typos in `cd` arguments
shopt -s dirspell               # ...and in directory names while completing
shopt -s globstar               # `**/` recurses: rg -g '**/*.ts', ls **/*.json
shopt -s extglob                # !(pattern), +(pattern), @(a|b)
shopt -s checkwinsize           # keep $LINES/$COLUMNS correct after a resize
shopt -s no_empty_cmd_completion  # don't scan all of $PATH when Tab on empty line
shopt -s checkhash              # re-check $PATH if a hashed command has moved

# Deliberately NOT enabled: `autocd`. It would let a bare `shell/` cd into it,
# but it invokes the cd BUILTIN, bypassing Omarchy's `cd` -> `zd` zoxide wrapper,
# so those jumps would never be recorded in the zoxide database.

# --- readline ----------------------------------------------------------------
bind 'set colored-completion-prefix on'  # highlight the part already typed
bind 'set completion-map-case on'        # `foo_bar` also matches `foo-bar`
bind 'set bell-style none'               # no beep/flash on an ambiguous Tab
bind 'set revert-all-at-newline on'      # discard half-edited history lines

# Ctrl+Left / Ctrl+Right word movement (Omarchy's inputrc binds plain arrows
# only). Both the modern CSI-u and the legacy xterm forms, so this works in
# alacritty, foot and inside tmux.
bind '"\e[1;5D": backward-word'
bind '"\e[1;5C": forward-word'
bind '"\e[5D": backward-word'
bind '"\e[5C": forward-word'

# Ctrl+Backspace / Ctrl+Delete delete a word.
bind '"\C-h": backward-kill-word'
bind '"\e[3;5~": kill-word'
