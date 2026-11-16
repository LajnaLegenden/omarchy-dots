"""Paths and tunables. Override tunables in ~/.claude-voice/voice.toml under a [voice] table."""

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude-voice"))
RUN_DIR = Path(
    os.environ.get("CLAUDE_VOICE_RUN_DIR") or Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "claude-voice"
)
SOCKET_PATH = RUN_DIR / "daemon.sock"
MODELS_DIR = Path(
    os.environ.get("CLAUDE_VOICE_MODELS", Path.home() / ".local/share/claude-voice/models")
)


@dataclass
class Settings:
    stt_model: str = "small.en"
    tts_voice: str = "af_heart"
    tts_speed: float = 1.0
    # First word of a phrase that counts as the wake word: the persona name "Ada" or "Claude",
    # plus common mis-hearings of both.
    wake_words: list[str] = field(
        default_factory=lambda: [
            "ada", "adah", "aida", "ayda", "ader",
            "claude", "claud", "cloud", "clod", "clawed", "clause", "klaud", "klod",
        ]
    )
    # Words Whisper is nudged towards hearing.
    stt_hotwords: str = "Ada Claude"
    vad_threshold: float = 0.5
    end_silence_ms: int = 700
    min_speech_ms: int = 250
    max_phrase_s: float = 30.0
    # After a bare "Claude" with nothing else, the next phrase within this window is the prompt.
    wake_follow_s: float = 8.0
    # Mic stays muted this long after TTS ends, so the speaker tail isn't picked up.
    tts_tail_mute_s: float = 0.35
    # After Claude's end-of-turn reply is spoken, phrases starting within this window need no wake word.
    reply_window_s: float = 10.0
    # Quit (mic off) once no registered voice pane has existed for this long. 0 disables.
    auto_quit_s: float = 60.0


def load_settings() -> Settings:
    path = CONFIG_DIR / "voice.toml"
    settings = Settings()
    if not path.exists():
        return settings
    data = tomllib.loads(path.read_text()).get("voice", {})
    known = {f.name for f in fields(Settings)}
    for key, value in data.items():
        if key in known:
            setattr(settings, key, value)
    return settings
