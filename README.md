# dotfiles

Personal dotfiles, managed with [GNU Stow](https://www.gnu.org/software/stow/).
Built to deploy onto a fresh [Omarchy](https://omarchy.org) machine (DHH's Arch +
Hyprland).

**Core principle:** these configs are *overrides*. On Omarchy my files live in
`~/.config/*` and `~/.bashrc`; Omarchy's own files live under
`~/.local/share/omarchy/` and are owned by `omarchy update`. This repo never
touches Omarchy internals — it only layers on top of them.

This is **v1** — intentionally small: tmux, the sessionizer, and shell aliases.
Hyprland/waybar/walker/theming come in a later version.

## Layout

```
dotfiles/
├── install.sh          # post-stow setup: TPM + go-folder-finder (run once after stowing)
├── bash/
│   └── .bashrc         # → ~/.bashrc — sources Omarchy defaults, then my aliases
├── shell/
│   └── .config/shell/
│       └── aliases.sh  # → ~/.config/shell/aliases.sh — git/cd/sessionizer aliases (shell-agnostic)
├── tmux/
│   └── .config/tmux/
│       └── tmux.conf   # → ~/.config/tmux/tmux.conf — TPM plugins, matugen colors deferred
└── tmux-sessionizer/
    └── .config/tmux-sessionizer/
        └── config.json # → ~/.config/tmux-sessionizer/config.json — go-folder-finder config
```

Each top-level dir is one Stow *package* whose inner tree mirrors `$HOME`, so
`stow <pkg>` symlinks it into the right place.

## Deploy on a fresh Omarchy machine

```bash
git clone <remote-url> ~/dotfiles
cd ~/dotfiles

# 1. symlink the configs into $HOME
stow bash shell tmux tmux-sessionizer        # or: stow */  (stows every package)

# 2. build the binary + tmux plugins (needs `go` and `git`)
./install.sh                                  # sudo pacman -S go fzf   if missing

# 3. reload
exec bash          # pick up the new ~/.bashrc
tmux               # prefix is C-k; prefix+f opens the sessionizer; prefix+I (re)installs plugins
```

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
> ships its own copies of those, and **waybar/walker get overwritten by
> `omarchy update` / theme changes** — they'll need a reconcile step (re-stow
> after each update). Noted here so the workflow is documented ahead of time.

## How to add a new config

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

Alternatively, capture a config that's already in place without moving it first:

```bash
mkdir -p ~/dotfiles/btop/.config/btop
cp ~/.config/btop/btop.conf ~/dotfiles/btop/.config/btop/   # copy into repo
rm ~/.config/btop/btop.conf                                  # remove the real file
cd ~/dotfiles && stow btop                                   # link replaces it
```

(`stow --adopt btop` also works if the file is already where stow wants to link
— it absorbs the live file into the repo; `git diff` to review.)

## Update / pull changes on another machine

```bash
cd ~/dotfiles
git pull
stow -R bash shell tmux tmux-sessionizer    # -R = restow (remove + re-link; picks up new/renamed files)
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

- **tmux** uses [TPM](https://github.com/tmux-plugins/tpm); `install.sh` clones
  it and installs the plugins (`sensible`, `better-mouse-mode`,
  `vim-tmux-navigator`, `cpu`). Inside tmux, `prefix + I` reinstalls.
- The statusline pulls colors from `~/.config/tmux/colors.conf` (matugen). That
  file isn't shipped yet, so the bar is **uncolored** until the theming version
  lands — the `source-file -q` line fails quietly, no errors.
- **go-folder-finder** (the `ts` alias / `prefix+f`) is installed by `install.sh`
  via `go install` from the private repo `github.com/LajnaLegenden/go-folder-finder`
  (default branch `master`, untagged → it falls back from `@latest` to `@master`).
  Requires `go` and SSH access to GitHub; the script enables a narrow
  `https→ssh` git rewrite for `LajnaLegenden/*` so `go install` can fetch it.
  The binary lands in `~/.local/bin`. Needs `fzf` at runtime.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `stow: ... existing target is not owned by stow` | A real file is in the way — `mv` it aside (`*.omarchy-default`) or `stow --adopt`, then re-stow. |
| `ts` / `prefix+f`: command not found | `~/.local/bin` not on PATH, or binary not built. Re-run `./install.sh`; `exec bash`. |
| `go install` fails to fetch the module | Need SSH access to the private repo. Check `ssh -T git@github.com` and that the `url."git@github.com:LajnaLegenden/".insteadOf` rewrite is set (install.sh sets it). |
| tmux statusline has no colors | Expected in v1 (matugen deferred). Comes back with the theming version. |
| tmux plugins not loading (no cpu/ram %) | `prefix + I` to install, or re-run `./install.sh`. |
