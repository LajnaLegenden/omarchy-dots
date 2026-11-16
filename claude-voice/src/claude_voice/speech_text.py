"""Turn Claude's markdown replies into text that sounds right when spoken."""

import re

_FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
_TABLE_ROW = re.compile(r"^\s*\|.*\|?\s*$|^\s*[-:| ]{3,}\s*$")
_PATH = re.compile(r"(?<![\w/])(?:[\w.@~-]+/)+([\w.-]+\.\w{1,6})(?::(\d+)(?:-(\d+))?)?")
_FILE_LINE = re.compile(r"\b([\w.-]+\.\w{1,6}):(\d+)(?:-(\d+))?\b")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _inline_code(m: re.Match) -> str:
    code = m.group(1).strip()
    if _PATH.fullmatch(code) or _FILE_LINE.fullmatch(code):
        return code  # handled by the path pass below
    return code if len(code) <= 40 else "that snippet"


def to_speech(md: str) -> str:
    text = _FENCE.sub("\n(code on screen)\n", md)

    lines: list[str] = []
    in_table = False
    for raw in text.splitlines():
        line = raw.strip()
        if _TABLE_ROW.match(line) and "|" in line or (in_table and _TABLE_ROW.match(line)):
            if not in_table:
                lines.append("(table on screen)")
                in_table = True
            continue
        in_table = False
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s*)?", "", line)
        line = re.sub(r"^>\s?", "", line)
        if line:
            lines.append(line)

    # Each remaining line becomes its own sentence.
    text = " ".join(l if l[-1] in ".!?:;,)" else l + "." for l in lines)

    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"`([^`]+)`", _inline_code, text)
    # Paths and file:line refs are spoken as the bare file name; line numbers are visual noise in speech.
    text = _PATH.sub(lambda m: m.group(1), text)
    text = _FILE_LINE.sub(lambda m: m.group(1), text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\w)\*(\S.*?\S|\S)\*(?!\w)", r"\1", text)
    text = text.replace("→", " to ").replace("&", " and ")
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    text = re.sub(r"(\(code on screen\)\.?\s*){2,}", "(code on screen). ", text)
    text = text.replace("(code on screen)", "Code is on screen.").replace("(table on screen)", "Table is on screen.")
    text = re.sub(r"\.\.+", ".", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


def split_sentences(text: str, min_len: int = 25) -> list[str]:
    """Split into sentence-sized chunks so TTS can start playing the first one early."""
    parts = [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]
    chunks: list[str] = []
    for part in parts:
        if chunks and len(chunks[-1]) < min_len:
            chunks[-1] += " " + part
        else:
            chunks.append(part)
    return chunks
