"""Arabic-aware comparison and display normalisation."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

TASHKEEL_RE = re.compile(r"[\u064B-\u065F\u0670]")
ALEF_RE = re.compile(r"[أإآٱ]")
# Witness-specific marks are transcription content, not punctuation: ⦿ ✢ ✣ :
PUNCT_RE = re.compile(r'''[.،؛؟!?()«»"'\-–—_/\\]+''')
WHITESPACE_RE = re.compile(r"\s+")
ARABIC_LETTER_RE = re.compile(r"[\u0621-\u064A\u0671-\u06D3]")
DIGIT_RE = re.compile(r"[0-9٠-٩]")


def normalize_for_match(text: str) -> str:
    """Apply the legacy scoring normalisation without changing stored text."""

    text = unicodedata.normalize("NFC", text or "")
    text = TASHKEEL_RE.sub("", text)
    text = text.replace("\u0640", "")
    text = ALEF_RE.sub("ا", text)
    text = text.replace("ى", "ي").replace("ئ", "ي").replace("ؤ", "و")
    text = text.replace("ة", "ه")
    text = PUNCT_RE.sub("", text)
    return WHITESPACE_RE.sub("", text)


def normalize_for_display(text: str) -> str:
    return WHITESPACE_RE.sub(" ", (text or "").strip())


def similarity(before: str, after: str) -> float:
    left, right = normalize_for_match(before), normalize_for_match(after)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return SequenceMatcher(a=left, b=right, autojunk=False).ratio()


def arabic_letter_ratio(text: str) -> float:
    if not text:
        return 0.0
    letters = len(ARABIC_LETTER_RE.findall(text))
    return letters / max(len(text.replace(" ", "")), 1)


def digit_ratio(text: str) -> float:
    compact = (text or "").replace(" ", "")
    if not compact:
        return 0.0
    return len(DIGIT_RE.findall(compact)) / len(compact)
