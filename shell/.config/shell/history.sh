# History — shared live across every terminal, tmux pane and SSH session.
#
# MUST be sourced AFTER $OMARCHY_PATH/default/bash/rc, which is the only
# other place history is configured (default/bash/shell sets histappend,
# HISTCONTROL=ignoreboth and HISTSIZE=32768) -- these values deliberately win.
#
# Out of the box each shell keeps its history in memory and appends it to
# ~/.bash_history only at exit, so two panes never see each other's commands and
# the last one to close can clobber the others. The PROMPT_COMMAND hook below
# fixes that.

[[ $- == *i* ]] || return 0

shopt -s histappend   # append instead of overwriting (Omarchy sets this too)
shopt -s cmdhist      # keep a multi-line command as a single history entry
shopt -s lithist      # ...with real newlines rather than folded onto ; separators

HISTSIZE=200000                    # entries kept in memory
HISTFILESIZE=400000                # entries kept on disk
HISTCONTROL=ignoreboth:erasedups   # no dupes, no leading-space commands
HISTTIMEFORMAT='%F %T '            # timestamps, and `history` prints them

# Noise not worth recording. Patterns must match the WHOLE line.
HISTIGNORE='ls:ll:la:lsa:lt:lta:cd:cd -:..:...:....:pwd:exit:clear:reload'
HISTIGNORE+=':history:h:hgrep *:gst:g st:git status:t:lg'

# Flush this shell's new commands and pull in everyone else's, on every prompt.
#   history -a  appends only what THIS shell added since the last append
#   history -n  reads only lines OTHER shells appended since our last read
# Together that gives live sharing without re-reading the whole file each prompt.
__lj_history_sync() {
  history -a
  history -n
}

# PROMPT_COMMAND is an ARRAY on bash >= 5.1 and already holds starship_precmd,
# /etc/bash.bashrc's terminal-title setter and __zoxide_hook. It must be APPENDED
# to -- a plain assignment would silently break the prompt and zoxide.
case " ${PROMPT_COMMAND[*]-} " in
  *" __lj_history_sync "*) ;;   # already installed (e.g. re-sourced .bashrc)
  *)
    if ((BASH_VERSINFO[0] > 5 || (BASH_VERSINFO[0] == 5 && BASH_VERSINFO[1] >= 1))); then
      PROMPT_COMMAND+=(__lj_history_sync)
    else
      PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND$'\n'}__lj_history_sync"
    fi
    ;;
esac
