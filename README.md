# dotfiles

Personal dotfiles, managed with [GNU Stow](https://www.gnu.org/software/stow/).
Built to deploy onto a fresh [Omarchy](https://omarchy.org) machine (DHH's Arch +
Hyprland).

**Core principle:** these configs are *overrides*. On Omarchy my files live in
`~/.config/*` and `~/.bashrc`; Omarchy's own files are packaged under
`/usr/share/omarchy/` (what `$OMARCHY_PATH` points at) and are owned by
`omarchy update`. This repo never touches Omarchy internals — it only layers on
top of them. `~/.local/share/omarchy` still exists as a back-compat symlink to
`/usr/share/omarchy`, but don't write new references against it.

Beyond the v1 set (tmux, the sessionizer, shell aliases, Neovim) this now also
carries Hyprland keybindings and the night light schedule. Waybar/walker/theming
still come later.

Two kinds of setup:
- **Stow packages** — plain config files symlinked into `$HOME` by `stow`.
- **Install hooks** (`install.d/`) — for things symlinks can't do: cloning repos,
  building/installing binaries. Run by `./install.sh`.

## Layout

```
dotfiles/
├── install.sh              # runner: executes every install.d/*.sh hook, in order
├── install.d/              # one hook per tool — drop a new NN-name.sh here to extend
│   ├── 10-tmux-tpm.sh      #   TPM + tmux plugins
│   ├── 20-go-folder-finder.sh  #   `go install` the sessionizer binary -> ~/.local/bin
│   ├── 30-nvim.sh          #   clone the nvim repo -> ~/Personal/nvim, link ~/.config/nvim
│   ├── 40-cli-tools.sh     #   pacman: git-delta (git pager) + git-town (stacked PRs)
│   ├── 40-nightlight.sh    #   enable the night light fade user timer
│   └── 50-idle-inhibit.sh  #   AUR audio idle-inhibitor, so video stops the lock
├── bash/
│   └── .bashrc             # → ~/.bashrc — sources Omarchy defaults, then everything below
├── shell/
│   └── .config/shell/      # → ~/.config/shell/ — all sourced from .bashrc, in this order
│       ├── env.sh          #   exported env vars (Nx tuning)
│       ├── aliases.sh      #   git/cd/sessionizer aliases
│       ├── functions.sh    #   ask(), wtreset()
│       ├── history.sh      #   big history, timestamps, shared live across all shells
│       ├── options.sh      #   shopt + readline (`bind`) overrides
│       └── completions.sh  #   git completion for the `g`/`gco`/... aliases, git-town
├── git/
│   └── .config/git/
│       ├── config          # → ~/.config/git/config — aliases, rebase/diff/rerere, delta
│       └── ignore          # → ~/.config/git/ignore — global gitignore
├── scripts/
│   └── .local/scripts/     # → ~/.local/scripts/ (on PATH) — hypr-move-workspace, etc.
├── hypr/
│   └── .config/hypr/       # → bindings.lua, autostart.lua (Omarchy 4 "quattro" is Lua)
├── tmux/
│   └── .config/tmux/
│       └── tmux.conf       # → ~/.config/tmux/tmux.conf — TPM plugins, matugen colors deferred
├── tmux-sessionizer/
│   └── .config/tmux-sessionizer/
│       └── config.json     # → ~/.config/tmux-sessionizer/config.json — go-folder-finder config
├── hypr/
│   └── .config/hypr/
│       ├── bindings.lua    # → ~/.config/hypr/bindings.lua — my keybindings
│       ├── autostart.lua   # → ~/.config/hypr/autostart.lua — starts hyprsunset
│       └── hyprsunset.conf # → ~/.config/hypr/hyprsunset.conf — night light baseline
├── scripts/
│   └── .local/scripts/     # → ~/.local/scripts (on PATH)
│       ├── hypr-move-workspace
│       └── omarchy-nightlight-schedule   # night light fade, run by the timer
└── nightlight/
    └── .config/
        ├── omarchy/nightlight-schedule.toml   # location, temperatures, fade length
        └── systemd/user/                      # the timer + oneshot service
```

Each top-level config dir is one Stow *package* whose inner tree mirrors `$HOME`,
so `stow <pkg>` symlinks it into the right place. **Neovim is not a Stow
package** — it's a standalone git repo, so `install.d/30-nvim.sh` clones it and
symlinks `~/.config/nvim` at it (keeping its own history/upstream intact).

## Deploy on a fresh Omarchy machine

```bash
git clone git@github.com:LajnaLegenden/omarchy-dots.git ~/dotfiles
cd ~/dotfiles

# 1. symlink the config packages into $HOME
mkdir -p ~/.config/systemd/user     # so stow links units into it, not over it
stow bash shell scripts hypr tmux tmux-sessionizer nightlight
stow --no-folding git    # keeps ~/.config/git a real dir; see Notes
#   NB: `alacritty` is intentionally left out — the repo copy is behind the live
#   file (missing its CSI-u Shift+Return bindings), so stowing it would regress.

# 2. run the install hooks (TPM + sessionizer binary + nvim clone)
./install.sh                                  # needs git, go, and SSH access to GitHub

# 3. reload
exec bash          # pick up the new ~/.bashrc
tmux               # prefix is C-k; prefix+f opens the sessionizer; prefix+I (re)installs plugins
nvim               # first launch: lazy.nvim bootstraps the plugins
```

Prereqs the hooks expect: `sudo pacman -S go fzf` if missing, and a working
SSH key for GitHub (the sessionizer + nvim repos are private — verify with
`ssh -T git@github.com`).

### If stow reports a conflict

Omarchy may already ship a file where a package wants to link (e.g. a stock
`~/.bashrc`). Stow refuses to clobber it. Two fixes:

- **Back up then re-stow** — keep Omarchy's version for reference:
  ```bash
  mv ~/.bashrc ~/.bashrc.omarchy-default
  stow bash
  ```
- **Adopt** — pull the existing file *into* the repo, then review:
  ```bash
  stow --adopt bash      # moves ~/.bashrc into the repo and links it back
  git diff               # see what Omarchy's file differed; keep or revert
  ```
  `--adopt` overwrites the repo copy with the live file, so always `git diff`
  afterwards and `git checkout` if you want my version instead.

> `waybar`/`walker` are not shipped here. If they ever are: Omarchy ships its own
> copies and **they get overwritten by `omarchy update` / theme changes** — so
> they'd need a reconcile step (re-stow after each update).

## Extending the installer

Anything beyond plain symlinks (clone a repo, build a binary, register a
service) goes in an install hook. To add one:

```bash
# create an executable, idempotent hook — NN prefix sets run order
cat > ~/dotfiles/install.d/40-btop-theme.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "…do setup here; make it safe to run repeatedly…"
EOF
chmod +x ~/dotfiles/install.d/40-btop-theme.sh
git add install.d/40-btop-theme.sh && git commit -m "Add btop-theme install hook"
```

`./install.sh` picks it up automatically — no edit to the runner. Rules for a
good hook: **idempotent** (safe to run on every deploy *and* every later
`git pull`), self-contained, and it should `exit` non-zero on real failure so
the runner reports it (one failing hook won't block the others).

## How to add a new config (Stow package)

Mirror the target path inside a new package dir, move the real file in, and let
stow re-link it. Worked example — adding `btop`:

```bash
# 1. create the package mirroring the target ($HOME/.config/btop/...)
mkdir -p ~/dotfiles/btop/.config/btop

# 2. move the live config into the package
mv ~/.config/btop/btop.conf ~/dotfiles/btop/.config/btop/btop.conf

# 3. link it back
cd ~/dotfiles && stow btop

# 4. commit
git add btop && git commit -m "Add btop config"
```

(`stow --adopt btop` also works if the file is already where stow wants to link
— it absorbs the live file into the repo; `git diff` to review.)

## Update / pull changes on another machine

```bash
cd ~/dotfiles
git pull
stow -R bash shell scripts hypr tmux tmux-sessionizer   # -R = restow (picks up new/renamed files)
stow -R --no-folding git
./install.sh                                 # re-run hooks (idempotent) to pick up new tools
```

## Remove a config

```bash
cd ~/dotfiles
stow -D tmux        # -D = delete: removes the symlinks, leaves the repo untouched
```

## Secrets policy

- **Nothing secret is in this repo.** Verified at capture time — the configs
  here contain no keys/tokens/passwords.
- `.gitignore` blocks credential patterns (`*.key`, `id_*`, `.env`, `.netrc`,
  `.ssh/`, `.gnupg/`, etc.) as a safety net regardless.
- Machine-specific values, if any get added later, go in a gitignored
  `local.conf` with a committed `local.conf.example` template. None needed yet.

## Notes / dependencies

- **Shell load order matters.** `bash/.bashrc` sources Omarchy's
  `$OMARCHY_PATH/default/bash/rc` *first*, then the `~/.config/shell/*.sh`
  files. That ordering is what makes the overrides stick, and two of them only
  work in that position:
  - `options.sh` uses `bind` calls rather than a `~/.inputrc`, because the last
    line of Omarchy's `rc` is `bind -f .../default/bash/inputrc` — which runs
    *after* readline has read `~/.inputrc`, so a `~/.inputrc` here would be
    silently clobbered.
  - `completions.sh` must run after Omarchy's `bash/init` sources fzf's
    `completion.bash`. fzf claims `git` with `_fzf_path_completion`; for `git`
    itself it recovers git's real completion lazily, but the `g`/`gco`/`gr`
    aliases had no spec at all and completed *filenames* instead of branches.
    `completions.sh` loads git's completion eagerly (≈9 ms) so `__git_complete`
    exists, points each alias at its subcommand's completion, then re-applies
    fzf's wrapper so the `**` trigger still works. Keep its alias list in sync
    with `aliases.sh`.
- **History is shared live** across every terminal, tmux pane and SSH session:
  `history.sh` appends `__lj_history_sync` (`history -a; history -n`) to
  `PROMPT_COMMAND`. `PROMPT_COMMAND` is an *array* on bash ≥ 5.1 and already
  holds `starship_precmd`, the `/etc/bash.bashrc` title setter and
  `__zoxide_hook` — it must be appended to, never assigned.
- **git** config is a Stow package, deployed with `stow --no-folding git` so
  `~/.config/git` stays a real directory (anything git writes there won't land in
  the repo). `install.d/20-go-folder-finder.sh` runs `git config --global`, which
  writes *through* the symlink into `git/.config/git/config` — so that hook can
  show up as a dirty file in this repo. Per-directory work identity is scaffolded
  (commented out) at the bottom of the config.
- **git-delta** is wired as `core.pager` / `interactive.diffFilter`, but both
  values are shell snippets that fall back to `less` / `cat`, so the config stays
  harmless on a machine without delta. **git-town** backs the `gt`/`gts`/`gtp`
  aliases and gets shell completion in `completions.sh`. Both are installed by
  `40-cli-tools.sh`, which needs `sudo`.
- **tmux** uses [TPM](https://github.com/tmux-plugins/tpm); `10-tmux-tpm.sh`
  clones it and installs the plugins (`sensible`, `better-mouse-mode`,
  `vim-tmux-navigator`, `cpu`). Inside tmux, `prefix + I` reinstalls.
- tmux statusline colors come from `~/.config/tmux/colors.conf` (matugen). That
  file isn't shipped yet, so the bar is **uncolored** until the theming version
  lands — the `source-file -q` line fails quietly, no errors.
- **go-folder-finder** (the `ts` alias / `prefix+f`) is installed by
  `20-go-folder-finder.sh` via `go install` from private
  `github.com/LajnaLegenden/go-folder-finder` (default branch `master`, untagged
  → falls back from `@latest` to `@master`). Needs `go` + GitHub SSH; the hook
  enables a narrow `https→ssh` git rewrite for `LajnaLegenden/*`. Binary lands in
  `~/.local/bin`. Needs `fzf` at runtime.
- **night light** (`nightlight` package + `40-nightlight.sh`) fades the screen
  temperature instead of Omarchy's instant on/off toggle. hyprsunset can only
  switch profiles abruptly, so `omarchy-nightlight-schedule` walks the
  temperature in one-minute steps over an hour and pushes each step through
  `hyprctl hyprsunset temperature` — the same IPC the bar indicator and
  `omarchy toggle nightlight` use, so both keep working. Sunrise/sunset are
  computed locally from the lat/long in
  `~/.config/omarchy/nightlight-schedule.toml` (no network, no geolocation),
  then clamped so a 59°N winter doesn't turn the screen orange at 14:48.
  Toggling by hand pauses the schedule until the current stretch ends.
  Inspect with `omarchy-nightlight-schedule schedule` (upcoming boundaries),
  `curve` (today's full ramp) or `status` (what it wants right now).
- **idle inhibit** (`50-idle-inhibit.sh`) installs the AUR package
  `wayland-pipewire-idle-inhibit` and enables its user service. Without it the
  screen locks mid-video: Omarchy's idle service does respect Wayland idle
  inhibitors, but nothing creates one — Firefox only knows how to ask the
  `org.freedesktop.ScreenSaver` / `org.gnome.SessionManager` D-Bus services,
  which don't exist under Hyprland. The daemon watches PipeWire instead and
  holds an inhibitor whenever audio is playing, so it covers every app. Nothing
  to stow — the unit ships with the package. Silent video still won't inhibit;
  the bar's Stay Awake toggle is the manual override.
- **nvim** is cloned by `30-nvim.sh` from private
  `github.com/LajnaLegenden/nvim.git` to `~/Personal/nvim`, with `~/.config/nvim`
  symlinked at it. On re-run the hook leaves an existing clone untouched (so
  local edits are never clobbered). Plugins install on first `nvim` launch.
- **hypr is Lua as of Omarchy 4 "quattro".** The old `.conf` tree is gone:
  `~/.config/hypr/hyprland.lua` is the entrypoint, it loads Omarchy's defaults
  and then `require`s `hypr.monitors`, `hypr.input`, `hypr.bindings`,
  `hypr.looknfeel` and `hypr.autostart`. The quattro migration generated fresh
  stub `.lua` files and did **not** convert user `.conf` content, so the old
  `bindings.conf`/`autostart.conf`/`windows.conf` symlinks silently stopped
  being read — everything had to be ported by hand.
  The package now ships two files:
  - `bindings.lua` — personal overrides only, layered on Omarchy's defaults.
    Most of the old `bindings.conf` was a verbatim copy of Omarchy 3's defaults
    and is now redundant. What's left: `SUPER+M` (hypr-move-workspace) plus
    Google/Claude web apps in place of Omarchy's HEY/Grok defaults. **Rebinding
    a default needs `hl.unbind("KEYS")` before the `o.bind`** — without it both
    bindings stay registered.
  - `autostart.lua` — autostarts 1Password/Slack/Claude **and** holds the two
    `o.window()` workspace rules (Slack→ws9, Claude→ws8) that place them.
  **`hyprland.lua` is deliberately NOT a Stow package**, for the same reason
  `hyprland.conf` never was: Hyprland watches the main config and regenerates an
  `-- AUTOGENERATED HYPRLAND CONFIG` stub the instant it's briefly unlinked, so
  `stow`/`stow -R` (which unlink then relink, non-atomically) would wipe the live
  config and break the desktop. That's why the window rules live in
  `autostart.lua` rather than a `windows.lua` — adding one would mean editing
  `hyprland.lua` to `require` it.
  Helper reference: `$OMARCHY_PATH/default/hypr/helpers.lua` (`o.bind`,
  `o.window`, `o.launch_on_start`, `o.launch_webapp`, ...). Binding targets take
  table forms: `{ launch = ... }`, `{ webapp = ... }`, `{ tui = ..., focus = true }`,
  `{ omarchy = "browser" }`. After any change: `hyprctl reload` then
  `hyprctl configerrors`; `omarchy menu keybindings --print` lists what's bound.
  Window rules only apply to windows mapped *after* the reload, so restart an app
  to see its rule take effect.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `gco <Tab>` completes filenames, not branches | `completions.sh` isn't loading — check it's sourced *after* the Omarchy `rc` line in `.bashrc`, and that `declare -F __git_complete` is non-empty. |
| `stow: ... existing target is not owned by stow` | A real file is in the way — `mv` it aside (`*.omarchy-default`) or `stow --adopt`, then re-stow. |
| `ts` / `prefix+f`: command not found | `~/.local/bin` not on PATH, or binary not built. Re-run `./install.sh`; `exec bash`. |
| `go install` / nvim clone fails to fetch | Need SSH access to the private repos. Check `ssh -T git@github.com`; for `go install`, confirm the `url."git@github.com:LajnaLegenden/".insteadOf` rewrite is set (the hook sets it). |
| tmux statusline has no colors | Expected in v1 (matugen deferred). Comes back with the theming version. |
| Night light never changes | `systemctl --user status omarchy-nightlight-schedule.timer`; check `hyprctl hyprsunset temperature` answers (hyprsunset must be running — `autostart.lua` starts it). |
| Night light stuck at one temperature | A manual toggle pauses the schedule until the current stretch ends. To resume now: `rm ~/.local/state/omarchy/nightlight-schedule.json`. |
| Fades at the wrong time | Wrong lat/long in `~/.config/omarchy/nightlight-schedule.toml`. Check with `omarchy-nightlight-schedule schedule`. |
| Screen still locks during video | `systemctl --user status wayland-pipewire-idle-inhibit`. Confirm audio is actually playing: `pw-dump \| grep -A2 'Stream/Output/Audio'`. Muted video won't inhibit — use the bar's Stay Awake toggle. |
| Screen now *never* locks | The inhibitor may be stuck on. Check with `systemctl --user stop wayland-pipewire-idle-inhibit && wayland-pipewire-idle-inhibit -v INFO` and watch for `DISABLED` when audio stops. |
| tmux plugins not loading (no cpu/ram %) | `prefix + I`, or re-run `./install.sh`. |
| A custom Hyprland bind does nothing | Check it's in `~/.config/hypr/bindings.lua` (a symlink into this repo), that a default isn't shadowing it (`omarchy menu keybindings --print` shows a key twice if `hl.unbind` is missing), then `hyprctl reload && hyprctl configerrors`. |
| After `omarchy update`, personal hypr config is ignored | Confirm `~/.config/hypr/hyprland.lua` still `require`s `hypr.bindings` and `hypr.autostart` — `omarchy refresh hyprland` resets it to upstream's list. |
| nvim opens with stock config / no plugins | `~/.config/nvim` not linked or repo not cloned — re-run `./install.sh`; first launch bootstraps plugins. |
