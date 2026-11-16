"""Mic capture and playback through PipeWire's pw-record / pw-play (raw s16 mono over pipes)."""

import subprocess

import numpy as np

MIC_RATE = 16000
CHUNK_SAMPLES = 512  # Silero VAD window at 16 kHz = 32 ms
CHUNK_BYTES = CHUNK_SAMPLES * 2


class Mic:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.proc = subprocess.Popen(
            ["pw-record", "--raw", "--rate", str(MIC_RATE), "--channels", "1", "--format", "s16", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def read_chunk(self) -> bytes | None:
        """Block until one VAD-sized chunk is available. None means the recorder died."""
        assert self.proc and self.proc.stdout
        buf = b""
        while len(buf) < CHUNK_BYTES:
            data = self.proc.stdout.read(CHUNK_BYTES - len(buf))
            if not data:
                return None
            buf += data
        return buf

    def stop(self) -> None:
        if self.proc:
            self.proc.kill()
            self.proc.wait()
            self.proc = None


class Player:
    """Streams float32 audio to one pw-play process; exiting the context waits for playback to drain."""

    def __init__(self, rate: int) -> None:
        self.rate = rate
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> "Player":
        self.proc = subprocess.Popen(
            ["pw-play", "--raw", "--rate", str(self.rate), "--channels", "1", "--format", "s16", "-"],
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        return self

    def write(self, audio: np.ndarray) -> None:
        assert self.proc and self.proc.stdin
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        try:
            self.proc.stdin.write(pcm)
        except BrokenPipeError:
            pass

    def silence(self, seconds: float) -> None:
        self.write(np.zeros(int(self.rate * seconds), dtype=np.float32))

    def __exit__(self, *exc) -> None:
        assert self.proc and self.proc.stdin
        try:
            self.proc.stdin.close()
        except BrokenPipeError:
            pass
        self.proc.wait()


def chime(rate: int) -> np.ndarray:
    """Short rising two-note blip meaning 'I'm listening'."""
    out = []
    for freq, dur in ((660.0, 0.07), (990.0, 0.09)):
        t = np.arange(int(rate * dur)) / rate
        tone = 0.25 * np.sin(2 * np.pi * freq * t)
        fade = min(len(t) // 4, int(rate * 0.01))
        env = np.ones_like(t)
        env[:fade] = np.linspace(0, 1, fade)
        env[-fade:] = np.linspace(1, 0, fade)
        out.append(tone * env)
    return np.concatenate(out).astype(np.float32)
