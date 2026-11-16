"""Wake word, stop phrase, and yes/no matching on transcripts."""

import re

_LEAD_FILLERS = {"hey", "hi", "ok", "okay", "yo", "so", "um", "uh", "oh", "well"}
_STOP = {
    "stop", "stop it", "stop that", "cancel", "wait", "hold on", "never mind",
    "nevermind", "abort", "interrupt", "shut up", "halt",
}
_YES = {
    "yes", "yeah", "yep", "yup", "ya", "sure", "ok", "okay", "go ahead", "do it", "allow",
    "approve", "approved", "fine", "go", "proceed", "alright", "all right", "affirmative",
    "sounds good", "go for it", "yes go ahead", "yeah go ahead", "yes do it", "yeah do it",
    "ok go ahead", "okay go ahead", "sure go ahead",
    # Answers to "okay if I…?" / "want me to…?"
    "yeah sure", "sure thing", "of course", "please do", "go on", "absolutely", "definitely",
    "yes please", "yeah please", "yep go ahead", "yeah go for it", "that's fine", "yeah that's fine",
    "yeah fine", "yes yes", "yeah yeah", "do that", "yeah do that", "let's do it", "yeah let's do it",
}
_NO = {
    "no", "nope", "nah", "don't", "dont", "do not", "deny", "denied", "negative",
    "no thanks", "no thank you", "don't do it", "dont do it", "not now", "cancel", "stop",
    "no don't", "nah don't", "not yet", "no not yet", "hold off", "please don't", "no wait",
    "better not", "no leave it", "leave it",
}
_TRAIL_FILLERS = ("please", "thanks", "thank you", "claude", "cloud", "ada")


def _norm_word(w: str) -> str:
    return re.sub(r"[^a-z']", "", w.lower()).removesuffix("'s")


def _norm_phrase(text: str) -> str:
    return " ".join(re.sub(r"[^a-z' ]+", " ", text.lower()).split())


def match_wake(transcript: str, wake_words: list[str]) -> str | None:
    """Return what follows the wake word ('' for a bare wake word), or None if there is none."""
    toks = transcript.strip().split()
    i = 0
    while i < len(toks) and i < 2 and _norm_word(toks[i]) in _LEAD_FILLERS:
        i += 1
    if i < len(toks) and _norm_word(toks[i]) in wake_words:
        return " ".join(toks[i + 1 :]).lstrip(" ,.:;!?-")
    return None


def is_stop(text: str) -> bool:
    return _norm_phrase(text) in _STOP


def classify_yes_no(text: str) -> bool | None:
    """True for a plain yes, False for a plain no, None for anything else (feedback)."""
    phrase = _norm_phrase(text)
    words = phrase.split()
    while words and words[0] in _LEAD_FILLERS - {"ok", "okay"}:
        words.pop(0)
    phrase = " ".join(words)
    for filler in _TRAIL_FILLERS:
        phrase = phrase.removesuffix(" " + filler)
    if phrase in _YES:
        return True
    if phrase in _NO:
        return False
    return None
