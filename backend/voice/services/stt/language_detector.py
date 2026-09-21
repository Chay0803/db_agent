"""
Language Detection Service
===========================
Detects English / Hindi / Telugu from text.
Uses langdetect + custom Telugu/Hindi script detection as fallback.
"""

from __future__ import annotations
import re
import asyncio
from concurrent.futures import ThreadPoolExecutor

_EXECUTOR = ThreadPoolExecutor(max_workers=1)

# Unicode ranges
_DEVANAGARI = re.compile(r'[\u0900-\u097F]')   # Hindi script
_TELUGU_SC  = re.compile(r'[\u0C00-\u0C7F]')   # Telugu script

# Common Telugu romanized words
_TELUGU_WORDS = {
    "meeru", "nenu", "memu", "mee", "naa", "ikkade", "akkade",
    "cheppandi", "cheppu", "telugu", "anduke", "kaadu", "avunu",
    "ledu", "ela", "enti", "evaru", "ekkade", "emiti", "enduku",
}

# Common Hindi romanized words
_HINDI_WORDS = {
    "kya", "hai", "hain", "mujhe", "mera", "meri", "aap", "tum",
    "hum", "yeh", "woh", "kaise", "kyun", "kahan", "kab", "nahin",
    "nahi", "bahut", "accha", "theek", "samajh", "bata", "batao",
    "chahiye", "chahte", "fees", "paisa", "rupee",
}


def _detect_lang(text: str) -> str:
    if not text or len(text.strip()) < 3:
        return "en"

    # Script-based detection (most reliable)
    if _TELUGU_SC.search(text):
        return "te"
    if _DEVANAGARI.search(text):
        return "hi"

    # Romanized detection
    lower_words = set(text.lower().split())
    if lower_words & _TELUGU_WORDS:
        return "te"
    if lower_words & _HINDI_WORDS:
        return "hi"

    # Library-based
    try:
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 42
        lang = detect(text)
        if lang in ("hi", "te", "en"):
            return lang
        if lang in ("mr", "sa", "kok"):   # often confused with Hindi
            return "hi"
    except Exception:
        pass

    return "en"


async def detect_language(text: str) -> str:
    """Returns 'en', 'hi', or 'te'."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_EXECUTOR, _detect_lang, text)


def detect_language_sync(text: str) -> str:
    return _detect_lang(text)


# ── Voice mapping: language → edge-tts voice name ────────────────────────────
VOICE_MAP = {
    "en": "en-IN-NeerjaNeural",    # Indian English, female, natural
    "hi": "hi-IN-SwaraNeural",     # Hindi, female, natural
    "te": "te-IN-ShrutiNeural",    # Telugu, female
}

# Whisper language codes
WHISPER_LANG_MAP = {
    "en": "en",
    "hi": "hi",
    "te": "te",
}


def get_tts_voice(lang: str) -> str:
    return VOICE_MAP.get(lang, VOICE_MAP["en"])


def get_whisper_lang(lang: str) -> str:
    return WHISPER_LANG_MAP.get(lang, "en")
