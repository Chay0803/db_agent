"""
Voice module — API routes.

Browser voice chat only (no Twilio/phone). Mounted under /api/voice
and /ws is not used here — everything is plain request/response so it
works from a vanilla-JS panel with no audio-worklet/VAD plumbing.

Typical frontend flow (see frontend/static/js/app.js, "Voice Assistant"
panel):
  1. record a short clip with MediaRecorder
  2. POST it to /api/voice/converse  →  { transcript, response, audio_b64, ... }
  3. play audio_b64 back to the student

/api/voice/chat, /api/voice/stt and /api/voice/tts remain available
individually for a type-instead-of-speak fallback and for reuse.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from backend.voice import crud
    from backend.voice.database import get_db
    from backend.voice.security import rate_limit, require_admin
    from backend.voice.session import registry
    from backend.voice.services.emotion.detector import detect_emotion_sync
    from backend.voice.services.llm.gemini import get_full_response
    from backend.voice.services.rag.retriever import add_document, get_context_text, search, status as rag_status
    from backend.voice.services.stt.language_detector import detect_language_sync
    from backend.voice.services.stt.transcriber import transcribe_audio
    from backend.voice.services.tts.synthesizer import synthesize_full
except ImportError:
    from voice import crud
    from voice.database import get_db
    from voice.security import rate_limit, require_admin
    from voice.session import registry
    from voice.services.emotion.detector import detect_emotion_sync
    from voice.services.llm.gemini import get_full_response
    from voice.services.rag.retriever import add_document, get_context_text, search, status as rag_status
    from voice.services.stt.language_detector import detect_language_sync
    from voice.services.stt.transcriber import transcribe_audio
    from voice.services.tts.synthesizer import synthesize_full

router = APIRouter(prefix="/api/voice", tags=["voice"])

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


# ── Shared chat step (RAG + emotion + Gemini + persistence) ────────────────────
async def _run_chat_turn(db: AsyncSession, session_id: str, query: str):
    query = query.strip()
    if not query or len(query) > 2000:
        raise HTTPException(status_code=400, detail="Query must contain 1-2000 characters")

    session = await registry.get_or_create(session_id)
    language = detect_language_sync(query)
    rag_results = await search(query)
    context_text = get_context_text(rag_results)
    emotion_data = detect_emotion_sync(query)
    emotion = emotion_data["emotion"]

    answer = await get_full_response(
        history=session.get_history_slice(8),
        query=query,
        emotion=emotion,
        language=language,
        context_text=context_text,
    )
    session.add_user_message(query, emotion=emotion, language=language)
    session.add_assistant_message(answer)

    conv = await crud.get_or_create_conversation(db, session_id)
    await crud.add_message(db, conv, "user", query, language=language, emotion=emotion,
                            emotion_scores=emotion_data.get("scores"))
    await crud.add_message(db, conv, "assistant", answer, language=language,
                            rag_sources=[r["source"] for r in rag_results] or None)

    return {
        "response": answer,
        "session_id": session_id,
        "language": language,
        "emotion": emotion,
        "sources": [r["source"] for r in rag_results],
    }


# ── Text chat (typed fallback) ──────────────────────────────────────────────────
@router.post("/chat", dependencies=[Depends(rate_limit("voice-chat", 30))])
async def voice_chat(query: str, session_id: str = "default", db: AsyncSession = Depends(get_db)):
    return await _run_chat_turn(db, session_id[:255], query)


# ── STT ──────────────────────────────────────────────────────────────────────
@router.post("/stt", dependencies=[Depends(rate_limit("voice-stt", 20))])
async def speech_to_text(audio: UploadFile = File(...)):
    content = await audio.read()
    if not content or len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio payload is empty or too large")
    return await transcribe_audio(content, is_pcm=False)


# ── TTS ──────────────────────────────────────────────────────────────────────
@router.post("/tts", dependencies=[Depends(rate_limit("voice-tts", 30))])
async def text_to_speech(text: str, language: str = "en"):
    if not text.strip() or len(text) > 2000:
        raise HTTPException(status_code=400, detail="Text must contain 1-2000 characters")
    if language not in {"en", "hi", "te"}:
        raise HTTPException(status_code=400, detail="Unsupported language")
    audio = await synthesize_full(text, language)
    return StreamingResponse(io.BytesIO(audio), media_type="audio/mpeg")


# ── Combined: record → transcript → answer → speech, in one round trip ────────
@router.post("/converse", dependencies=[Depends(rate_limit("voice-converse", 20))])
async def converse(
    audio: UploadFile = File(...),
    session_id: str = "default",
    db: AsyncSession = Depends(get_db),
):
    content = await audio.read()
    if not content or len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio payload is empty or too large")

    stt_result = await transcribe_audio(content, is_pcm=False)
    transcript = (stt_result.get("text") or "").strip()
    if not transcript:
        raise HTTPException(status_code=422, detail="Could not transcribe any speech from that clip")

    turn = await _run_chat_turn(db, session_id[:255], transcript)
    audio_bytes = await synthesize_full(turn["response"], turn["language"])

    return {
        "transcript": transcript,
        **turn,
        "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
    }


# ── RAG knowledge base management ───────────────────────────────────────────
@router.post("/upload-doc", dependencies=[Depends(require_admin)])
async def upload_document(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    content = await file.read()
    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, f"Document exceeds the {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB limit")
    safe_filename = Path(file.filename or "upload.txt").name
    name = safe_filename.lower()
    if not any(name.endswith(ext) for ext in (".pdf", ".docx", ".txt")):
        raise HTTPException(400, "Supported: PDF, DOCX, TXT")

    text = ""
    if name.endswith(".pdf"):
        import pdfplumber
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
    elif name.endswith(".docx"):
        from docx import Document as DocxDoc
        doc = DocxDoc(io.BytesIO(content))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    else:
        text = content.decode("utf-8", errors="ignore")

    if not text.strip():
        raise HTTPException(422, "Could not extract text")

    save_dir = Path("data")
    save_dir.mkdir(exist_ok=True)
    save_path = save_dir / safe_filename
    save_path.write_bytes(content)

    n_chunks = add_document(text, safe_filename)
    await crud.create_document_record(
        db, filename=safe_filename, file_path=str(save_path),
        file_size=len(content), content_type=name.split(".")[-1], total_chunks=n_chunks,
    )
    return {"file": safe_filename, "chunks_added": n_chunks, **rag_status()}


@router.get("/docs-status")
def docs_status():
    return rag_status()


# ── Conversation history ────────────────────────────────────────────────────
@router.get("/conversations", dependencies=[Depends(require_admin)])
async def list_conversations(limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)):
    convs = await crud.list_conversations(db, limit=limit, offset=offset)
    return {"conversations": [
        {
            "id": str(c.id), "session_id": c.session_id,
            "language": str(c.language), "total_messages": c.total_messages,
            "dominant_emotion": c.dominant_emotion,
            "started_at": c.started_at.isoformat() if c.started_at else None,
            "ended_at": c.ended_at.isoformat() if c.ended_at else None,
        }
        for c in convs
    ]}


@router.get("/conversations/{session_id}", dependencies=[Depends(require_admin)])
async def get_conversation_detail(session_id: str, db: AsyncSession = Depends(get_db)):
    live = registry.get(session_id)
    conv = await crud.get_conversation(db, session_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    messages = await crud.get_conversation_messages(db, conv.id)
    return {
        "session_id": session_id,
        "live": live.get_analytics_snapshot() if live else None,
        "messages": [
            {"speaker": m.speaker, "content": m.content, "timestamp": m.timestamp.isoformat(),
             "emotion": m.emotion, "language": str(m.language)}
            for m in messages
        ],
    }


@router.delete("/sessions/{session_id}", dependencies=[Depends(require_admin)])
async def clear_session(session_id: str, db: AsyncSession = Depends(get_db)):
    await registry.remove(session_id)
    await crud.end_conversation(db, session_id)
    return {"message": f"Session {session_id} cleared."}
