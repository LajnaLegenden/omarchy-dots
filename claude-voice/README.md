# claude-voice

Hands-free voice layer around stock Claude Code. Claude reads its questions, permission prompts, and replies aloud. You answer by voice. Everything runs locally: faster-whisper for speech-to-text, Kokoro for text-to-speech.

```
tmux: ┌──────────── nvim (55%) ────────────┬──── claude (45%) ────┐
      │ voice-show opens + highlights here │ stock Claude Code    │
      └────────────────────────────────────┴──────────────────────┘
voice daemon (one per machine): mic → VAD → STT → wake word → tmux send-keys
                                speaker ← Kokoro ← hooks (ask / permission / stop)
```

## Setup

```sh
./setup.sh                                  # venv, models, ~/.claude-voice, ~/.local/bin/claude-voice
CLAUDE_CONFIG_DIR=~/.claude-voice claude    # once: /login, pick theme, exit
claude-voice [project-dir]                  # start (or reattach) a session
```

Requires PipeWire (`pw-record`, `pw-play`), tmux, nvim, uv.

## Talking to it

- **Persona:** Claude goes by **Ada**, a knowledgeable senior-engineer coworker (voice af_heart). Persona and tone live in `config/voice-prompt.md`.
- **New prompt:** "Ada, run the tests." ("Claude, …" works too.) Speech without the wake word is ignored. Saying only "Ada" plays a chime, and your next phrase (within 8 s) is the prompt.
- **Reply window:** for 10 s after Claude's end-of-turn reply is spoken, you can answer without "Claude". Every phrase that starts in the window is sent.
- **Interrupt:** "Ada, stop" sends Esc to the Claude pane.
- **Clear / close:** "Ada, clear the context" or "Ada, close the session". Claude runs `voice-session clear|close`, which asks "Just to check, want me to clear the context?" by voice. On yes, it runs after Claude's reply is spoken: Ctrl+U and `/clear` in the Claude pane, or kill the whole voice tmux session (Claude and nvim). A new prompt or "Ada, stop" before the turn ends cancels it.
- **Tone:** the voice prompt makes Claude talk like a coworker at the next desk: opinions, choices in a sentence ("we could do X, or Y, I'd lean X"), no numbered lists aloud. It asks at real forks and does the obvious stuff without mentioning it. See the examples in `config/voice-prompt.md`.
- **Claude's questions** (AskUserQuestion): only the question text is read, so Claude writes it as spoken, choices included ("Should I put the cache in Redis, or just keep it in memory?"). Option labels stay on screen. Then a chime plays. Just talk, no wake word needed. Your words go to Claude verbatim, so "the Redis one" and "explain why first" both work. If you stay silent, it asks once more and then leaves the dialog on screen.
- **Permission prompts** are asked as "Okay if I run the unit tests?". "Yeah", "sure", or "go ahead" allows, "no" or "not yet" denies, and anything else denies with your words as feedback to Claude.
- **Replies:** Claude starts each final message with a `<speak>…</speak>` block, one or two sentences: the result plus anything that needs you. Only that block is spoken, and the detail after it is screen-only. The tags are hidden on screen by a MessageDisplay hook. If there's no block, the whole reply is spoken with markdown stripped.
- **Hands-off:** Claude works silently. It speaks only when it needs you, when it's done, or for a "come look" callout via `voice-say "the sandbox is open in your browser"` (queued, returns at once). Routine fixes are never spoken. During code walkthroughs it uses `voice-say --wait` so the Neovim highlight stays in sync with the speech.
- The mic is ignored while Claude speaks (half-duplex), so there's no barge-in.
- The daemon quits by itself (mic off) once no voice-Claude pane has existed for 60 s. `claude-voice` starts it again.

## Pieces

| Path | Role |
|---|---|
| `bin/claude-voice` | Launcher: starts the daemon, builds the tmux layout, registers the Claude pane |
| `bin/claude-voice-pane` | Runs `claude --permission-mode auto --append-system-prompt <voice-prompt>` |
| `bin/voice-show` | `voice-show <path> <start> [end]`: show code in the nvim pane (reopens it if closed) |
| `bin/voice-say` | `voice-say [--wait] <text>`: spoken "come look" callout or walkthrough line |
| `bin/voice-session` | `voice-session clear\|close`: confirm by voice, then clear the context or close the session after the turn |
| `config/voice-prompt.md` | Voice-friendly system prompt addition |
| `config/settings.json` | Template for `~/.claude-voice/settings.json` (hooks, auto mode) |
| `src/claude_voice/daemon.py` | Mic/VAD/STT/TTS daemon, Unix socket at `$XDG_RUNTIME_DIR/claude-voice/daemon.sock` |
| `src/claude_voice/hooks.py` | Hook entrypoint: `claude-voice-hook ask\|permission\|stop\|display` |

## Debugging

```sh
tail -f $XDG_RUNTIME_DIR/claude-voice/daemon.log     # what it heard, what it sent
.venv/bin/claude-voice-ctl status                     # target pane, speaking, listening
.venv/bin/claude-voice-ctl say "hello"                # TTS check
.venv/bin/claude-voice-ctl ask "what's up?"           # speak, listen, print the answer
.venv/bin/claude-voice-ctl hear "Claude, run tests"   # simulate a heard phrase
.venv/bin/claude-voice-ctl speech < reply.md          # preview markdown-to-speech cleanup
.venv/bin/claude-voice-ctl quit                       # stop the daemon (mic off)
```

Tunables (STT model, voice, VAD, wake words, `stt_hotwords`, `reply_window_s`, `auto_quit_s`) go in `~/.claude-voice/voice.toml` under `[voice]`. See `src/claude_voice/config.py`. A daemon started by hand with no voice pane registered also auto-quits after `auto_quit_s`. Set it to 0 while debugging. To run a second, isolated daemon, set `CLAUDE_VOICE_RUN_DIR` to another dir.
