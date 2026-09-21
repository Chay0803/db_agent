"""
Text-to-Speech Service — edge-tts (free, Microsoft Neural TTS)
================================================================
• Indian English (en-IN-NeerjaNeural)
• Hindi (hi-IN-SwaraNeural)
• Telugu (te-IN-ShrutiNeural)
• Streaming sentence-by-sentence for low latency
• SSML support for more natural pauses / prosody
"""

from __future__ import annotations
import asyncio
import io
import os
import re
from typing import AsyncGenerator, Optional

import edge_tts

try:
    from backend.voice.services.stt.language_detector import get_tts_voice
except ImportError:
    from voice.services.stt.language_detector import get_tts_voice

TTS_RATE = os.getenv("TTS_RATE", "+12%")

# ── Sentence splitter ─────────────────────────────────────────────────────────
_SENT_SPLIT = re.compile(r'(?<=[.!?।])\s+')


def split_into_sentences(text: str) -> list[str]:
    """Split text into TTS-ready chunks (sentences or short phrases)."""
    sentences = _SENT_SPLIT.split(text.strip())
    result = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        # If a sentence is very long, split at commas too
        if len(s) > 200:
            parts = re.split(r',\s+', s)
            result.extend(p.strip() for p in parts if p.strip())
        else:
            result.append(s)
    return result


# ── Core streaming TTS ────────────────────────────────────────────────────────
async def stream_tts(
    text: str,
    language: str = "en",
    voice: Optional[str] = None,
) -> AsyncGenerator[bytes, None]:
    """
    Async generator that yields raw MP3 audio bytes for the given text.
    Uses edge-tts streaming — first bytes arrive within ~200ms.
    """
    v = voice or get_tts_voice(language)
    communicate = edge_tts.Communicate(text, v, rate=TTS_RATE)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            yield chunk["data"]


async def stream_tts_sentences(
    text: str,
    language: str = "en",
    voice: Optional[str] = None,
) -> AsyncGenerator[tuple[str, bytes], None]:
    """
    Yields (sentence, audio_bytes) pairs.
    Allows the consumer to update UI with current sentence being spoken.
    """
    sentences = split_into_sentences(text)
    v = voice or get_tts_voice(language)

    for sentence in sentences:
        if not sentence.strip():
            continue
        audio_buf = io.BytesIO()
        communicate = edge_tts.Communicate(sentence, v, rate=TTS_RATE)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buf.write(chunk["data"])
        audio_buf.seek(0)
        audio_data = audio_buf.read()
        if audio_data:
            yield sentence, audio_data


async def synthesize_full(text: str, language: str = "en") -> bytes:
    """Synthesize full text and return complete MP3 bytes."""
    buf = io.BytesIO()
    async for chunk in stream_tts(text, language):
        buf.write(chunk)
    buf.seek(0)
    return buf.read()


# ── Pipelined producer: Gemini tokens → sentence queue → TTS ─────────────────
async def piped_llm_to_tts(
    token_stream,                        # async iterator or sync list of token strings
    language: str = "en",
    voice: Optional[str] = None,
    on_sentence: Optional[callable] = None,   # callback(sentence: str)
    on_audio: Optional[callable] = None,      # callback(audio: bytes)
    interrupt_flag: Optional[list] = None,    # [False] — set [True] to abort
) -> str:
    """
    Pipelines LLM token streaming into TTS.

    Gemini produces tokens → we detect sentence boundaries → start TTS
    immediately for each sentence → caller gets audio chunks ASAP.

    Returns the full assembled text response.
    """
    sentence_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
    full_parts: list[str] = []

    def _interrupted():
        return interrupt_flag is not None and interrupt_flag[0]

    async def _producer():
        token_buf = ""
        try:
            async for token in token_stream:
                if _interrupted():
                    break
                token_buf += token
                full_parts.append(token)
                # Check for sentence-ending punctuation
                sents = _SENT_SPLIT.split(token_buf)
                for sent in sents[:-1]:
                    sent = sent.strip()
                    if sent and not _interrupted():
                        await sentence_queue.put(sent)
                token_buf = sents[-1]
        except Exception as e:
            print(f"[TTS producer] error: {e}")
        # Flush remainder
        if token_buf.strip() and not _interrupted():
            await sentence_queue.put(token_buf.strip())
        await sentence_queue.put(None)   # sentinel

    async def _consumer():
        v = voice or get_tts_voice(language)
        while True:
            sent = await sentence_queue.get()
            if sent is None:
                break
            if _interrupted():
                continue
            if on_sentence:
                on_sentence(sent)
            try:
                communicate = edge_tts.Communicate(sent, v, rate=TTS_RATE)
                async for chunk in communicate.stream():
                    if _interrupted():
                        break
                    if chunk["type"] == "audio" and on_audio:
                        on_audio(chunk["data"])
            except Exception as e:
                print(f"[TTS consumer] TTS error for '{sent[:30]}...': {e}")

    await asyncio.gather(_producer(), _consumer())
    return "".join(full_parts).strip()
