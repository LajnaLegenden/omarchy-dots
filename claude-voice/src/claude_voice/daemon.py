"""Voice daemon: owns the mic and speaker.

- Mic loop: pw-record -> Silero VAD -> phrases.
- Phrase loop: STT each phrase. If a hook is waiting for an answer, hand it over.
  Otherwise require the wake word and type the rest into the Claude tmux pane.
- Socket server: hooks and ctl ask it to speak, ask (speak + listen), retarget, etc.
- Session commands (voice-session): confirmed by voice, then run once the turn's reply is spoken.
Half-duplex: mic audio is dropped while TTS is playing.
"""

import json
import os
import queue
import signal
import socketserver
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass

from .audio import CHUNK_SAMPLES, MIC_RATE, Mic, Player, chime
from .config import RUN_DIR, SOCKET_PATH, Settings, load_settings
from .speech_text import split_sentences, to_speech
from .wake import classify_yes_no, is_stop, match_wake

CHUNK_MS = CHUNK_SAMPLES * 1000 // MIC_RATE
SESSION_CONFIRM = {
    "clear": "Just to check, want me to clear the context?",
    "close": "Just to check, want me to close this session?",
}
SESSION_CONFIRM_LISTEN_S = 20.0
AFTER_TURN_MAX_AGE_S = 600.0  # a scheduled clear/close older than this is dropped, never fired


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


@dataclass
class PendingAnswer:
    since: float
    answers: queue.Queue


class Daemon:
    def __init__(self, settings: Settings) -> None:
        from pysilero_vad import SileroVoiceActivityDetector

        from .engines import STT, TTS

        self.s = settings
        t0 = time.monotonic()
        self.stt = STT(settings.stt_model, settings.stt_hotwords)
        self.tts = TTS(settings.tts_voice, settings.tts_speed)
        self.vad = SileroVoiceActivityDetector()
        log(f"models loaded in {time.monotonic() - t0:.1f}s (stt={settings.stt_model}, voice={settings.tts_voice})")

        self.phrases: queue.Queue[tuple[float, bytes]] = queue.Queue()
        self.speaking = threading.Event()
        self.mute_until = 0.0
        self.in_speech = False
        self.transcribing = False
        # Everything audible goes through one FIFO so progress, questions, and replies never overlap.
        self.speech_q: queue.Queue[tuple[object, threading.Event]] = queue.Queue()
        self.ask_lock = threading.Lock()
        self.pending: PendingAnswer | None = None
        self.follow_until = 0.0
        self.reply_until = 0.0
        self.target_pane: str | None = None
        self.panes: list[str] = []  # registered voice panes, most recent last
        self.after_turn: dict[str, tuple[str, float]] = {}  # pane -> (clear|close, scheduled at)
        self.last_heard = ""
        self.mic: Mic | None = None

    # ---- mic -> phrases -------------------------------------------------

    def mic_loop(self) -> None:
        s = self.s
        end_chunks = s.end_silence_ms // CHUNK_MS
        min_chunks = s.min_speech_ms // CHUNK_MS
        max_chunks = int(s.max_phrase_s * 1000) // CHUNK_MS
        mic = self.mic = Mic()
        mic.start()
        preroll: deque[bytes] = deque(maxlen=10)  # ~320 ms before speech onset
        buf = bytearray()
        speech_chunks = silence_chunks = total_chunks = 0
        started_at = 0.0
        muted = False
        while True:
            chunk = mic.read_chunk()
            if chunk is None:
                log("pw-record exited, restarting in 1s")
                time.sleep(1)
                mic.start()
                continue
            if self.speaking.is_set() or time.monotonic() < self.mute_until:
                if not muted:
                    muted = True
                    self.in_speech = False
                    buf.clear()
                    preroll.clear()
                continue
            if muted:
                muted = False
                self.vad.reset()

            prob = self.vad(chunk)
            if not self.in_speech:
                preroll.append(chunk)
                if prob >= s.vad_threshold:
                    self.in_speech = True
                    started_at = time.monotonic()
                    buf = bytearray(b"".join(preroll))
                    speech_chunks, silence_chunks, total_chunks = 1, 0, 1
                continue

            buf += chunk
            total_chunks += 1
            if prob >= s.vad_threshold - 0.15:
                speech_chunks += 1
                silence_chunks = 0
            else:
                silence_chunks += 1
            if silence_chunks >= end_chunks or total_chunks >= max_chunks:
                self.in_speech = False
                if speech_chunks >= min_chunks:
                    self.phrases.put((started_at, bytes(buf)))
                buf = bytearray()
                preroll.clear()

    # ---- phrases -> answers / prompts -------------------------------------

    def phrase_loop(self) -> None:
        while True:
            started_at, pcm = self.phrases.get()
            self.transcribing = True
            try:
                t0 = time.monotonic()
                text = self.stt.transcribe(pcm)
                secs = len(pcm) / 2 / MIC_RATE
                log(f"heard ({secs:.1f}s audio, stt {time.monotonic() - t0:.2f}s): {text!r}")
            except Exception as e:  # keep the daemon alive on a bad phrase
                log(f"stt failed: {e}")
                continue
            finally:
                self.transcribing = False
            if text:
                self.on_text(text, started_at)

    def on_text(self, text: str, started_at: float) -> None:
        self.last_heard = text
        pending = self.pending
        if pending and started_at >= pending.since:
            pending.answers.put(text)
            return
        rest = match_wake(text, self.s.wake_words)
        if rest is None:
            if started_at <= self.reply_until:
                rest = text
                log("  reply window: no wake word needed")
            elif time.monotonic() < self.follow_until:
                rest = text
            else:
                log("  ignored: no wake word")
                return
        self.follow_until = 0.0
        if rest == "":
            self.follow_until = time.monotonic() + self.s.wake_follow_s
            self.play_chime()
            return
        if is_stop(rest):
            self.cancel_after_turn(self.target_pane, "interrupted")
            self.tmux_keys("Escape")
            log("  sent Escape")
            return
        self.cancel_after_turn(self.target_pane, "new prompt")
        self.inject(rest)

    def inject(self, text: str) -> None:
        if not self.target_pane:
            log("  no Claude pane registered; dropping prompt")
            self.speak("I can't find the Claude pane. Start me with claude-voice.")
            return
        text = text.rstrip(";")  # a trailing ';' is a tmux command separator
        self.tmux_keys("-l", text)
        self.tmux_keys("Enter")
        log(f"  sent to {self.target_pane}: {text!r}")

    def tmux_keys(self, *keys: str, pane: str | None = None) -> None:
        if pane := pane or self.target_pane:
            subprocess.run(["tmux", "send-keys", "-t", pane, *keys], check=False)

    # ---- session commands: clear / close after the turn ---------------------

    def confirm_session(self, action: str, pane: str | None) -> dict:
        pane = pane or self.target_pane
        if action not in SESSION_CONFIRM:
            return {"ok": False, "error": f"unknown session action {action!r}"}
        if not pane:
            return {"ok": False, "error": "no Claude pane registered"}
        answer = self.ask(SESSION_CONFIRM[action], SESSION_CONFIRM_LISTEN_S)
        confirmed = answer is not None and classify_yes_no(answer) is True
        if confirmed:
            self.after_turn[pane] = (action, time.monotonic())
            log(f"  {action} confirmed for {pane}, runs after the turn")
        else:
            log(f"  {action} not confirmed ({answer!r})")
        return {"ok": True, "confirmed": confirmed, "answer": answer}

    def cancel_after_turn(self, pane: str | None, why: str) -> None:
        if pane and (entry := self.after_turn.pop(pane, None)):
            log(f"  dropped scheduled {entry[0]} for {pane} ({why})")

    def run_after_turn(self, pane: str | None) -> str | None:
        """Run the clear/close scheduled for this pane, if any. Returns the action run."""
        entry = self.after_turn.pop(pane, None) if pane else None
        if not entry:
            return None
        action, scheduled_at = entry
        if time.monotonic() - scheduled_at > AFTER_TURN_MAX_AGE_S:
            log(f"  dropped stale {action} for {pane}")
            return None
        if action == "clear":
            # Ctrl+U first: leftover typed text would turn "/clear" into a normal prompt.
            self.tmux_keys("C-u", pane=pane)
            self.tmux_keys("-l", "/clear", pane=pane)
            time.sleep(0.4)  # let the slash-command menu settle before Enter
            self.tmux_keys("Enter", pane=pane)
            log(f"  cleared context in {pane}")
        elif action == "close":
            self.close_session(pane)
        return action

    def close_session(self, pane: str) -> None:
        """Kill the claude-voice tmux session owning this pane; else just /exit Claude."""
        def tmux(*args: str) -> str:
            return subprocess.run(["tmux", *args], capture_output=True, text=True).stdout.strip()

        name = tmux("display", "-p", "-t", pane, "#{session_name}")
        owner = tmux("show-options", "-t", f"={name}:", "-qv", "@claude_voice_pane") if name else ""
        if name and owner == pane:
            tmux("kill-session", "-t", f"={name}")
            log(f"  closed tmux session {name}")
        else:
            self.tmux_keys("C-u", pane=pane)
            self.tmux_keys("-l", "/exit", pane=pane)
            time.sleep(0.4)
            self.tmux_keys("Enter", pane=pane)
            log(f"  {pane} is not a claude-voice session, sent /exit")

    # ---- speaking ---------------------------------------------------------

    def speech_loop(self) -> None:
        while True:
            job, done = self.speech_q.get()
            try:
                job()
            except Exception as e:
                log(f"speech job failed: {e!r}")
            finally:
                done.set()

    def _enqueue(self, job) -> threading.Event:
        done = threading.Event()
        self.speech_q.put((job, done))
        return done

    def speak(
        self, text: str, markdown: bool = True, wait: bool = False, turn_end: bool = False, pane: str | None = None
    ) -> None:
        def job() -> None:
            self._speak_now(text, markdown)
            if not turn_end:
                return
            # The reply has been heard: now run a confirmed clear/close for this pane.
            if self.run_after_turn(pane or self.target_pane) == "close" or not text.strip():
                return
            # Opens once playback (and the muted tail) is over.
            self.reply_until = max(self.mute_until, time.monotonic()) + self.s.reply_window_s

        done = self._enqueue(job)
        if wait:
            done.wait()

    def play_chime(self, wait: bool = False) -> None:
        done = self._enqueue(lambda: self._play(lambda p: (p.write(chime(self.tts.RATE)), p.silence(0.05))))
        if wait:
            done.wait()

    def _play(self, fill) -> None:
        self.speaking.set()
        try:
            with Player(self.tts.RATE) as player:
                fill(player)
        finally:
            self.mute_until = time.monotonic() + self.s.tts_tail_mute_s
            self.speaking.clear()

    def _speak_now(self, text: str, markdown: bool) -> None:
        text = to_speech(text) if markdown else text
        chunks = split_sentences(text)
        if not chunks:
            return
        log(f"speaking: {text[:120]!r}{'...' if len(text) > 120 else ''}")
        audio_q: queue.Queue = queue.Queue(maxsize=3)

        def produce() -> None:
            for chunk in chunks:
                try:
                    audio_q.put(self.tts.synth(chunk))
                except Exception as e:
                    log(f"tts failed on {chunk!r}: {e}")
            audio_q.put(None)

        threading.Thread(target=produce, daemon=True).start()

        def fill(player: Player) -> None:
            while (audio := audio_q.get()) is not None:
                player.write(audio)
                player.silence(0.12)

        self._play(fill)

    def ask(self, text: str, timeout: float) -> str | None:
        """Speak, chime, then return the next phrase heard (no wake word needed), or None."""
        with self.ask_lock:
            self.speak(text)
            self.play_chime(wait=True)
            pending = PendingAnswer(since=time.monotonic(), answers=queue.Queue())
            self.pending = pending
            deadline = pending.since + timeout
            try:
                while True:
                    try:
                        return pending.answers.get(timeout=0.25)
                    except queue.Empty:
                        pass
                    now = time.monotonic()
                    busy = self.in_speech or self.transcribing or not self.phrases.empty()
                    # Don't cut the user off mid-sentence at the deadline.
                    if now >= deadline and not (busy and now < deadline + 20):
                        return None
            finally:
                self.pending = None

    # ---- voice panes + auto-quit ------------------------------------------

    def register_pane(self, pane: str) -> None:
        if pane in self.panes:
            self.panes.remove(pane)
        self.panes.append(pane)
        self.target_pane = pane

    def watchdog_loop(self) -> None:
        """Drop panes that no longer exist; quit once none have existed for auto_quit_s."""
        limit = self.s.auto_quit_s
        if limit <= 0:
            return
        interval = min(15.0, max(1.0, limit / 4))
        empty_since: float | None = time.monotonic()
        while True:
            time.sleep(interval)
            # `tmux display -t <dead pane>` still exits 0, so check membership in the live list.
            result = subprocess.run(["tmux", "list-panes", "-a", "-F", "#{pane_id}"], capture_output=True, text=True)
            live = set(result.stdout.split()) if result.returncode == 0 else set()
            for pane in list(self.panes):
                if pane not in live:
                    self.panes.remove(pane)
                    log(f"voice pane {pane} is gone")
            if self.target_pane not in self.panes:
                self.target_pane = self.panes[-1] if self.panes else None
            if self.panes:
                empty_since = None
                continue
            empty_since = empty_since or time.monotonic()
            if time.monotonic() - empty_since >= limit:
                log(f"no voice panes for {limit:.0f}s, quitting")
                os.kill(os.getpid(), signal.SIGTERM)
                return

    # ---- socket API -------------------------------------------------------

    def handle(self, req: dict) -> dict:
        cmd = req.get("cmd")
        if pane := req.get("pane"):
            self.register_pane(pane)
        if cmd == "ping":
            return {"ok": True}
        if cmd == "status":
            return {
                "ok": True,
                "target_pane": self.target_pane,
                "panes": self.panes,
                "speaking": self.speaking.is_set(),
                "listening_for_answer": self.pending is not None,
                "reply_window_s": round(max(0.0, self.reply_until - time.monotonic()), 1),
                "after_turn": {pane: action for pane, (action, _) in self.after_turn.items()},
                "in_speech": self.in_speech,
                "last_heard": self.last_heard,
                "pid": os.getpid(),
            }
        if cmd == "target":
            return {"ok": True, "target_pane": self.target_pane}
        if cmd == "speak":
            self.speak(
                req.get("text", ""),
                markdown=req.get("markdown", True),
                wait=bool(req.get("wait")),
                turn_end=bool(req.get("turn_end")),
                pane=req.get("pane"),
            )
            return {"ok": True}
        if cmd == "session":  # voice-session clear|close: confirm by voice, run after the turn
            return self.confirm_session(req.get("action", ""), req.get("pane"))
        if cmd == "ask":
            answer = self.ask(req.get("text", ""), float(req.get("listen_s", 45)))
            return {"ok": True, "answer": answer}
        if cmd == "hear":  # debug: pretend this was transcribed from the mic just now
            self.on_text(req.get("text", ""), time.monotonic())
            return {"ok": True}
        if cmd == "quit":
            threading.Timer(0.2, os.kill, (os.getpid(), signal.SIGTERM)).start()
            return {"ok": True}
        return {"ok": False, "error": f"unknown cmd {cmd!r}"}


def main() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    if SOCKET_PATH.exists():
        from .client import DaemonUnavailable, request

        try:
            request("ping", timeout=1)
            log("daemon already running")
            return
        except DaemonUnavailable:
            SOCKET_PATH.unlink()

    daemon = Daemon(load_settings())

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            line = self.rfile.readline()
            if not line:
                return
            try:
                reply = daemon.handle(json.loads(line))
            except Exception as e:
                log(f"request failed: {e!r}")
                reply = {"ok": False, "error": repr(e)}
            self.wfile.write((json.dumps(reply) + "\n").encode())

    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    server = Server(str(SOCKET_PATH), Handler)
    os.chmod(SOCKET_PATH, 0o600)

    def shutdown(*_) -> None:
        SOCKET_PATH.unlink(missing_ok=True)
        if daemon.mic:
            daemon.mic.stop()
        log("stopped")
        os._exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    threading.Thread(target=daemon.mic_loop, daemon=True).start()
    threading.Thread(target=daemon.phrase_loop, daemon=True).start()
    threading.Thread(target=daemon.speech_loop, daemon=True).start()
    threading.Thread(target=daemon.watchdog_loop, daemon=True).start()
    log(f"listening on {SOCKET_PATH}")
    server.serve_forever()
