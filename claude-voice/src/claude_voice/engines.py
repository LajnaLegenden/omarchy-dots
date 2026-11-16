"""Local speech engines: faster-whisper for STT, Kokoro (ONNX) for TTS."""

import re

import numpy as np

from .config import MODELS_DIR

# Whisper tends to "hear" these in noise or breathing.
_HALLUCINATIONS = {
    "", "you", "thank you", "thanks", "thank you for watching", "thanks for watching",
    "bye", "so", "uh", "um", "hmm", "okay", "i'm sorry",
}


class STT:
    def __init__(self, model: str, hotwords: str = "Claude") -> None:
        from faster_whisper import WhisperModel

        self.hotwords = hotwords
        self.model = WhisperModel(
            model, device="cpu", compute_type="int8", download_root=str(MODELS_DIR / "whisper")
        )

    def transcribe(self, pcm16: bytes) -> str:
        audio = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        segments, _ = self.model.transcribe(
            audio,
            language="en",
            beam_size=1,
            hotwords=self.hotwords,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        kept = [s.text for s in segments if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)]
        text = " ".join(kept).strip()
        if re.sub(r"[^a-z' ]", "", text.lower()).strip() in _HALLUCINATIONS:
            return ""
        return text


class TTS:
    RATE = 24000

    def __init__(self, voice: str, speed: float) -> None:
        from kokoro_onnx import Kokoro

        self.kokoro = Kokoro(str(MODELS_DIR / "kokoro-v1.0.int8.onnx"), str(MODELS_DIR / "voices-v1.0.bin"))
        self.voice = voice
        self.speed = speed

    def synth(self, text: str) -> np.ndarray:
        audio, rate = self.kokoro.create(text, voice=self.voice, speed=self.speed, lang="en-us")
        assert rate == self.RATE, rate
        return audio
