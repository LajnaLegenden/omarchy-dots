# dotfiles

Personal dotfiles, managed with [GNU Stow](https://www.gnu.org/software/stow/).
Built to deploy onto a fresh [Omarchy](https://omarchy.org) machine (DHH's Arch +
Hyprland).

**Core principle:** these configs are *overrides*. On Omarchy my files live in
`~/.config/*` and `~/.bashrc`; Omarchy's own files live under
`~/.local/share/omarchy/` and are owned by `omarchy update`. This repo never
touches Omarchy internals — it only layers on top of them.

This is **v1** — intentionally small: tmux, the sessionizer, shell aliases, and
Neovim. Hyprland/waybar/walker/theming come in a later version.

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
│   └── 30-nvim.sh          #   clone the nvim repo -> ~/Personal/nvim, link ~/.config/nvim
├── bash/
│   └── .bashrc             # → ~/.bashrc — sources Omarchy defaults, then my aliases
├── shell/
│   └── .config/shell/
│       └── aliases.sh      # → ~/.config/shell/aliases.sh — git/cd/sessionizer aliases
├── tmux/
│   └── .config/tmux/
│       └── tmux.conf       # → ~/.config/tmux/tmux.conf — TPM plugins, matugen colors deferred
└── tmux-sessionizer/
    └── .config/tmux-sessionizer/
        └── config.json     # → ~/.config/tmux-sessionizer/config.json — go-folder-finder config
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
stow bash shell tmux tmux-sessionizer        # or: stow */  (stows every package dir)

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

> This v1 doesn't ship `hypr`, `waybar`, or `walker` yet. When it does: Omarchy
> ships its own copies, and **waybar/walker get overwritten by `omarchy update`
> / theme changes** — they'll need a reconcile step (re-stow after each update).
> Noted here so the workflow is documented ahead of time.

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
stow -R bash shell tmux tmux-sessionizer    # -R = restow (remove + re-link; picks up new/renamed files)
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
- **nvim** is cloned by `30-nvim.sh` from private
  `github.com/LajnaLegenden/nvim.git` to `~/Personal/nvim`, with `~/.config/nvim`
  symlinked at it. On re-run the hook leaves an existing clone untouched (so
  local edits are never clobbered). Plugins install on first `nvim` launch.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `stow: ... existing target is not owned by stow` | A real file is in the way — `mv` it aside (`*.omarchy-default`) or `stow --adopt`, then re-stow. |
| `ts` / `prefix+f`: command not found | `~/.local/bin` not on PATH, or binary not built. Re-run `./install.sh`; `exec bash`. |
| `go install` / nvim clone fails to fetch | Need SSH access to the private repos. Check `ssh -T git@github.com`; for `go install`, confirm the `url."git@github.com:LajnaLegenden/".insteadOf` rewrite is set (the hook sets it). |
| tmux statusline has no colors | Expected in v1 (matugen deferred). Comes back with the theming version. |
| tmux plugins not loading (no cpu/ram %) | `prefix + I`, or re-run `./install.sh`. |
| nvim opens with stock config / no plugins | `~/.config/nvim` not linked or repo not cloned — re-run `./install.sh`; first launch bootstraps plugins. |
