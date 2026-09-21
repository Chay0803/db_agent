"""
Speech-to-Text Service — faster-whisper
=========================================
• faster-whisper (CTranslate2 backend) — 4× faster than openai-whisper
• Returns text + language + confidence + segments
• Async-safe via thread pool
• Keeps model warm (loaded once at startup)
"""

from __future__ import annotations
import os
import io
import wave
import uuid
import asyncio
import tempfile
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="stt")

# ── Model (lazy, loaded on first call or explicit warm-up) ────────────────────
_model      = None
_model_size = os.getenv("WHISPER_MODEL_SIZE", "base")
_device     = os.getenv("WHISPER_DEVICE", "cpu")
_compute    = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
_beam_size  = int(os.getenv("WHISPER_BEAM_SIZE", "1"))


def _load_model():
    global _model
    if _model is not None:
        return _model
    try:
        from faster_whisper import WhisperModel
        print(f"Loading faster-whisper ({_model_size}, {_device}, {_compute})...")
        _model = WhisperModel(_model_size, device=_device, compute_type=_compute)
        print("faster-whisper ready.")
    except ImportError:
        # Fallback to openai-whisper
        print("faster-whisper not found - falling back to openai-whisper")
        import whisper
        _model = whisper.load_model(_model_size)
    return _model


def _transcribe_file(file_path: str, hint_language: Optional[str] = None) -> Dict[str, Any]:
    """Blocking transcription — run in thread pool."""
    model = _load_model()

    try:
        # faster-whisper API
        segments, info = model.transcribe(
            file_path,
            language=hint_language,
            task="transcribe",
            beam_size=_beam_size,
            vad_filter=True,               # built-in VAD to skip silence
            vad_parameters=dict(
                min_silence_duration_ms=300,
                speech_pad_ms=200,
            ),
            condition_on_previous_text=False,
        )
        text  = " ".join(s.text for s in segments).strip()
        lang  = info.language
        conf  = info.language_probability
    except (TypeError, AttributeError):
        # openai-whisper fallback
        result = model.transcribe(file_path, language=hint_language)
        text   = result["text"].strip()
        lang   = result.get("language", "en")
        conf   = 1.0

    return {"text": text, "language": lang, "confidence": conf}


def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
    """Wrap Int16 PCM bytes in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


async def transcribe_audio(
    audio_bytes: bytes,
    is_pcm: bool = True,
    sample_rate: int = 16000,
    hint_language: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Async transcription entry point.

    Args:
        audio_bytes:   Raw PCM (Int16) bytes or any audio format (WAV/WebM/etc.)
        is_pcm:        If True, wraps bytes in WAV container first
        sample_rate:   PCM sample rate (only used when is_pcm=True)
        hint_language: ISO language code hint ('en'/'hi'/'te')

    Returns:
        {"text": str, "language": str, "confidence": float}
    """
    if is_pcm:
        wav_bytes = pcm_to_wav(audio_bytes, sample_rate)
    else:
        wav_bytes = audio_bytes

    # Write to temp file — whisper expects a file path
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.write(wav_bytes)
    tmp.close()

    try:
        loop   = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _executor,
            lambda: _transcribe_file(tmp.name, hint_language),
        )
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    return result


async def warmup():
    """Pre-load the model at startup so first call is instant."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_executor, _load_model)
