"""
Sanitize LLM response text for voice/TTS: remove filler openers and non-speakable content.
"""

import re

# Filler openers to strip (case-insensitive); allow optional trailing punctuation.
_FILLER_OPENERS = [
    r"^Okay\s*[!,.]?\s*",
    r"^Sure\s*[!,.]?\s*",
    r"^Alright\s*[!,.]?\s*",
    r"^Great\s*[!,.]?\s*",
    r"^Well\s*[!,.]?\s*",
    r"^So\s*[!,.]?\s*",
    r"^Oh\s*,\s*okay\s*[!,.]?\s*",
    r"^Oh\s+okay\s*[!,.]?\s*",
    r"^Right\s*[!,.]?\s*",
    r"^Yeah\s*[!,.]?\s*",
    r"^Yep\s*[!,.]?\s*",
]
_FILLER_PATTERN = re.compile(
    "|".join(f"(?:{p})" for p in _FILLER_OPENERS), re.IGNORECASE
)

# ASCII ellipsis (2+ dots) and Unicode ellipsis character (U+2026)
_ELLIPSIS_PATTERN = re.compile(r"\.{2,}|\u2026")


def sanitize_for_tts(text: str, strip_fillers: bool = True) -> str:
    """
    Make response text suitable for TTS / AI toy voice:
    - Replace ellipsis (... and Unicode …) with a space
    - Optionally strip leading filler words (Okay, Sure, Alright, etc.)

    Args:
        text: Raw LLM output text.
        strip_fillers: If True (default), strip leading filler openers.
                       Set False for mid-response sentences in streaming mode
                       where filler stripping would incorrectly eat valid words.
    """
    if not text or not text.strip():
        return text
    s = text.strip()
    if strip_fillers:
        for _ in range(5):
            prev = s
            s = _FILLER_PATTERN.sub("", s).strip()
            if not s or s == prev:
                break
    s = _ELLIPSIS_PATTERN.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if s else text.strip()
