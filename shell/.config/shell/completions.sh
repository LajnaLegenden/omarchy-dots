# Completions — layered on top of Omarchy's defaults.
#
# MUST be sourced AFTER $OMARCHY_PATH/default/bash/rc, because that is
# what defines `alias g='git'` (default/bash/aliases) and what sources fzf's
# completion.bash (default/bash/init).
#
# The problem this solves:
#   fzf's completion.bash claims a long list of commands -- `git` among them --
#   with `complete -o default -o bashdefault -F _fzf_path_completion`. For `git`
#   itself that turns out fine: git's completion is lazily loaded by
#   bash-completion, so fzf saved no original at setup time, but on first Tab
#   `_fzf_handle_dynamic_completion` runs `_comp_load git`, captures
#   `__git_wrap__git_main`, and returns 124 to make readline retry. Net effect:
#   `git checkout <Tab>` correctly lists branches.
#
#   Nothing, however, tells readline that `g` and `gco` are git. They have no
#   completion spec at all, so they fall through to bash's default and complete
#   FILENAMES -- `gco <Tab>` offered `bash/ hypr/ shell/ ...` instead of branches.
#
# The fix is to load git's completion eagerly (so `__git_complete` and the
# `_git_<sub>` functions exist at rc time) and then point every git alias at the
# completion for the subcommand it actually wraps.

[[ $- == *i* ]] || return 0

# --- git ---------------------------------------------------------------------

# Load git's completion now rather than on first Tab. Sourcing it also
# re-registers `git` itself via `___git_complete git __git_main`, which drops
# fzf's wrapper -- we put that back below so the `**` trigger keeps working.
if ! declare -F __git_complete >/dev/null 2>&1; then
  for _f in /usr/share/bash-completion/completions/git \
            /usr/share/git/completion/git-completion.bash; do
    [[ -r $_f ]] && { source "$_f"; break; }
  done
  unset _f
fi

if declare -F __git_complete >/dev/null 2>&1; then
  # `g` is git, so it gets the full dispatcher: `g <Tab>` lists subcommands,
  # `g checkout <Tab>` lists branches, `g log --<Tab>` lists options.
  __git_complete g __git_main

  # Prefix aliases: each is bound to the completion of the subcommand it wraps,
  # so `gco <Tab>` behaves exactly like `git checkout <Tab>`. Keep this list in
  # sync with aliases.sh.
  __git_complete gco   _git_checkout
  __git_complete gc    _git_commit
  __git_complete gcan  _git_commit
  __git_complete 'gcan!' _git_commit
  __git_complete gfo   _git_fetch
  __git_complete gfp   _git_push
  __git_complete gp    _git_push
  __git_complete gl    _git_log
  __git_complete glo   _git_log
  __git_complete glg   _git_log
  __git_complete gr    _git_rebase
  __git_complete grc   _git_rebase
  __git_complete grio  _git_rebase
  __git_complete gst   _git_status
  __git_complete gsw   _git_switch
  __git_complete gswc  _git_switch
  __git_complete gb    _git_branch
  __git_complete gba   _git_branch
  __git_complete gdf   _git_diff
  __git_complete gdc   _git_diff
  __git_complete gaa   _git_add
  __git_complete gap   _git_add
  __git_complete gsta  _git_stash
  __git_complete gstp  _git_stash
  __git_complete gm    _git_merge

  # Omarchy's own git aliases (default/bash/aliases) -- it never wires these up.
  __git_complete gcm   _git_commit
  __git_complete gcam  _git_commit
  __git_complete gcad  _git_commit

  # Re-apply fzf's wrapper now that a real spec exists to fall back to. This
  # restores `git **<Tab>` / `g **<Tab>` fuzzy path completion without costing
  # us branch completion, and makes the fallback eager instead of 124-retry.
  if declare -F _fzf_setup_completion >/dev/null 2>&1; then
    _fzf_setup_completion path git g 2>/dev/null
  fi
fi

# --- git-town ----------------------------------------------------------------
# Stacked-PR tool (installed by install.d/40-cli-tools.sh). Ships its own
# completion generator; `gt` is aliased to `git town` in aliases.sh.
if command -v git-town >/dev/null 2>&1; then
  source <(git-town completions bash) 2>/dev/null
  complete -F __start_git-town gt 2>/dev/null
fi
