"""Voice module — async CRUD helpers (Conversation / Message / Document only)."""

from __future__ import annotations
from datetime import datetime
from typing import Optional, List

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from voice.models import Conversation, Message, Document, Language


async def get_conversation(db: AsyncSession, session_id: str) -> Optional[Conversation]:
    result = await db.execute(
        select(Conversation)
        .where(Conversation.session_id == session_id)
        .options(selectinload(Conversation.messages))
    )
    return result.scalar_one_or_none()


async def get_or_create_conversation(db: AsyncSession, session_id: str) -> Conversation:
    conv = await get_conversation(db, session_id)
    if conv:
        return conv
    conv = Conversation(session_id=session_id)
    db.add(conv)
    await db.flush()
    return conv


async def add_message(
    db: AsyncSession,
    conversation: Conversation,
    speaker: str,
    content: str,
    language: str = "en",
    emotion: Optional[str] = None,
    emotion_scores: Optional[dict] = None,
    rag_sources: Optional[list] = None,
) -> Message:
    msg = Message(
        conversation_id=conversation.id,
        speaker=speaker,
        content=content,
        language=Language(language) if language in {e.value for e in Language} else Language.ENGLISH,
        emotion=emotion,
        emotion_scores=emotion_scores,
        rag_sources=rag_sources,
    )
    db.add(msg)
    conversation.total_messages = (conversation.total_messages or 0) + 1
    if emotion:
        conversation.dominant_emotion = emotion
    await db.flush()
    return msg


async def end_conversation(db: AsyncSession, session_id: str) -> Optional[Conversation]:
    conv = await get_conversation(db, session_id)
    if not conv:
        return None
    conv.ended_at = datetime.utcnow()
    await db.flush()
    return conv


async def list_conversations(db: AsyncSession, limit: int = 50, offset: int = 0) -> List[Conversation]:
    result = await db.execute(
        select(Conversation).order_by(desc(Conversation.started_at)).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


async def get_conversation_messages(db: AsyncSession, conversation_id) -> List[Message]:
    result = await db.execute(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.timestamp)
    )
    return list(result.scalars().all())


async def create_document_record(
    db: AsyncSession,
    filename: str,
    file_path: str,
    file_size: int,
    content_type: str,
    total_chunks: int,
) -> Document:
    doc = Document(
        filename=filename,
        file_path=file_path,
        file_size_bytes=file_size,
        content_type=content_type,
        total_chunks=total_chunks,
    )
    db.add(doc)
    await db.flush()
    return doc
