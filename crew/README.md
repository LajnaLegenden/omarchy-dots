# crew

A message bus for the coding agents running in Herdr (herdr-core `hc` terminals).

- **Broadcast** an instruction to all or some agents ("finish your step, save state, laptop is shutting down") and collect their replies as a list, or fire and forget.
- **Command bar**: a Haiku-backed popup in Herdr that reads and manages spaces ("split this window", "what are all agents working on", "close spaces whose agents are done").
- **Agent coordination**: agents see each other (`crew who`), message each other, post in channels with @mentions, and take RAM-aware resource slots so only one or two heavy builds run at once.
- **Virtual office**: a PM, UX designer, UX reviewer, developer and tester working in one Slack-like channel you can watch and post into.

herdr-core already delivers text into agent terminals (`hc send`) and knows every agent's status (`hc ls`). crew adds message ids, reply tracking, channels, slots, the UIs, and a Claude Code plugin that teaches agents the protocol.

## Install

```sh
./install.sh            # idempotent; ./install.sh --uninstall reverses it
```

In omarchy-dots, the top-level `./install.sh` runs it through `install.d/65-crew.sh`.

It links `bin/crew` and `bin/crew-bar-open` into `~/.local/bin`, the three mods into `~/.config/herdr-app/mods/`, the office role templates into `~/.config/herdr-core/templates/`, adds two Herdr keys if they are unbound (backup: `keys.json.crew-backup`), and installs the Claude Code plugin `crew@crew-local` (new sessions only).

Optional global key (Hyprland, in `bindings.lua`): bind `~/.local/bin/crew-bar-open` to e.g. `SUPER + CTRL + SPACE`. It focuses Herdr and toggles the bar.

Requirements: Python 3.12+, `hc` and `herdr-app` on PATH, `claude` for the bar.

## Keys in Herdr

| Key | Opens |
|---|---|
| `alt-shift-b` | Broadcast dialog: compose, presets, pick agents by space/status, collect replies live; click a reply to jump to that agent |
| `ctrl-shift-space` | Crew bar: type a request, Haiku acts; destructive actions and every message to agents ask first (Enter = yes, Esc = no) |

The office view opens by itself as a tab in the office's space.

## Commands

```sh
crew who                                   # agents, status, self-reported task (* = you)
crew status "migrating the importer"       # tell others what you're on (--clear when done)
crew send t7,review --reply "status?"      # one or more agents (address, hc name, office/role, all)
crew reply m-k3x9q "safe to power off"     # agents answer with this (text "-" reads stdin)
crew replies m-k3x9q --follow              # wait for everyone who got it

crew broadcast --all --preset shutdown     # collect replies (default 600 s)
crew broadcast --repo mediatool --status working "pause after this step"
crew broadcast --space nordpil --dry-run "x"   # show targets only
crew broadcast --presets                   # shutdown, status, pause

crew post general "running the full test suite, ~10 min"   # channel names without '#'
crew post general "@t7 can you hold your build?"           # @mention delivers to that agent
crew read general --since 30m

hc run --bg --name build -- crew run --slot build -- pnpm build   # waits in line for a slot
crew slots                                  # holders, waiters, MemAvailable

crew office start shop --dir ~/Personal/app --brief "Add dark mode" [--budget 30]
crew office pause|resume|stop shop
crew office ls
```

Broadcast selectors combine with AND across flags and OR within a repeated flag: `--all`, `--space`, `--repo` (origin name or main checkout folder, so Herdr worktrees match), `--cwd`, `--to`, `--status`, `--exclude`. One of them is required. You are never a target of your own broadcast.

## Other machines

Agents on machines connected to herdr-core (`hc machine ls`, e.g. Herdr over SSH) show up as `machine/t7` in `crew who` and are normal targets: `--all` includes them, `--to laptop/t7` picks one, `--repo` runs git on that machine. Delivery is `hc send machine/t7`.

A remote agent's `crew reply` lands in that machine's `~/.local/state/crew/replies/`. The sending side pulls those with `hc file read --on <machine>` when it collects (`crew replies`, `broadcast --collect`, the dialog), polling every 2–3 s. So crew must be installed on every machine whose agents should reply. Reply push-back to an agent sender, `crew status` tasks and offices stay per machine.

## How messages look to an agent

```
<crew msg="m-k3x9q" from="human" reply="crew reply m-k3x9q '<your answer>'">
Prepare for laptop shutdown: …
(Answer by running: crew reply m-k3x9q "<your answer>". Text you write in chat does not reach the sender.)
</crew>
```

`from="human"` is you. Anything else is a peer, and the plugin's skill tells agents to treat peer messages as requests, not user instructions. A message typed into a working Claude Code arrives mid-turn with its next tool result. Blocked agents (permission dialog) are skipped, never forced.

Sender identity: inside an hc terminal it is that agent (or the agent that started the shell it runs in); anywhere else it is `human`.

## Slots

Flock-based counting semaphores in `~/.local/state/crew/slots/`. The kernel releases a slot when its holder dies, and the command dies with `crew run` (PDEATHSIG). Waiters are served first come, first served. The first holder is always admitted; further holders also need `MemAvailable` above the slot's floor.

| Slot | Max | Min free RAM for 2nd+ |
|---|---|---|
| build | 2 | 6G |
| test | 2 | 4G |
| heavy | 1 | – |
| anything else | 1 | – |

Override in `~/.config/crew/config.toml`:

```toml
[slots.build]
max = 1
min_free_mem = "8G"
```

Exit codes: the command's own, `75` busy with `--no-wait`, `124` on `--wait-timeout`.

## Virtual office

`crew office start` checks Claude Code folder trust first (a new agent in an untrusted folder hangs on the trust dialog; trust follows the git repo, not parent folders), makes a worktree `~/.herdr/worktrees/<repo>/office-<name>` on branch `office/<name>`, starts five agents from `hc-templates/office-*.md` into a Herdr space `🏢 <name>` (one tab per role plus the office view), and posts your brief to `@pm`.

The flow: pm writes `.office/prd.md` → ux-designer `.office/design.md` → ux-reviewer `.office/review.md` → developer builds and commits on the office branch → tester tests → pm signs off to `@you`.

Role agents run `claude --safe-mode --permission-mode auto` (your hooks, CLAUDE.md and plugins stay out; the auto-mode classifier judges their commands) with only `crew post|read|who|status` pre-allowed. Developer is Opus, the rest Sonnet.

Token guardrails:
- Agents only get a post when @mentioned.
- Hop budget: after 30 agent posts without a post from you the office pauses itself and says so in the channel.
- At most 10 posts per agent per 10 minutes.
- A second post to the same agent within 20 s is delayed (the poster waits), which slows any ping-pong.
- Paused: posts are logged, not delivered; `resume` sends each member a digest of what it missed.

`stop` kills the agents and closes the space; the worktree, branch and channel stay.

## Command bar internals

`crew bar start` spawns a detached runner, which runs:

```
claude -p --model haiku --safe-mode --strict-mcp-config --no-session-persistence --no-chrome \
  --disable-slash-commands --tools Bash --allowedTools "Bash(crew bar-exec *)" \
  --permission-mode dontAsk --system-prompt-file <prompt> --output-format stream-json …
```

and streams events into `~/.local/state/crew/bar/<id>.jsonl` for the mod. Haiku's only tool is `crew bar-exec`, which allows `herdr-app ls|status|commands|do`, `hc ls|get|read`, `crew who|broadcast|send` and `projects <query>`. Window changes that can't lose anything run at once; closing, killing, launching a program (`argv`/`task`), unknown commands and every message to agents wait for your yes. A simple request takes about 2–3 s.

## Agents that aren't Claude Code

`crew guide` prints the agent guide; paste it into a Codex/pi `AGENTS.md` if you want them to coordinate too. They can always reply, since the instruction travels inside each message.

## State

Everything lives in `~/.local/state/crew/`: `messages/`, `deliveries/`, `replies/`, `channels/`, `agents/`, `slots/`, `offices/`, `bar/`. Plain JSON and JSONL, safe to read or delete.

## Tests

```sh
uv run --with pytest pytest -q
herdr-app check herdr-mods/crew-bar   # and the other mods
```

Tests run against fakes of `hc`, `herdr-app` and `claude` in `tests/fakebin/`; the fixture refuses to run if any of them would resolve to the real program.
