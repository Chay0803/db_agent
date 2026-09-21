"""
Voice module — database models.

Trimmed from the original AI-Phone-Agent schema: this integration is
browser voice chat only, so CallAnalytics, Lead, and the Twilio-only
columns on Conversation were dropped. Conversation/Message/Document
are enough to keep chat history and a RAG document log.
"""

from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean, ForeignKey, JSON, Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.dialects.postgresql import UUID


class Base(DeclarativeBase):
    pass


class Language(str, enum.Enum):
    ENGLISH = "en"
    HINDI = "hi"
    TELUGU = "te"
    UNKNOWN = "unknown"


class Conversation(Base):
    __tablename__ = "voice_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(255), unique=True, nullable=False, index=True)
    language = Column(SAEnum(Language), default=Language.ENGLISH)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    total_messages = Column(Integer, default=0)
    dominant_emotion = Column(String(50), nullable=True)

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Conversation {self.session_id}>"


class Message(Base):
    __tablename__ = "voice_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("voice_conversations.id"), nullable=False, index=True)
    speaker = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    language = Column(SAEnum(Language), default=Language.ENGLISH)
    timestamp = Column(DateTime, default=datetime.utcnow)
    emotion = Column(String(50), nullable=True)
    emotion_scores = Column(JSON, nullable=True)
    rag_sources = Column(JSON, nullable=True)  # list of source filenames used for this answer

    conversation = relationship("Conversation", back_populates="messages")

    def __repr__(self):
        return f"<Message {self.speaker}: {self.content[:50]}>"


class Document(Base):
    __tablename__ = "voice_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    content_type = Column(String(50), nullable=True)
    total_chunks = Column(Integer, default=0)
    indexed_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    def __repr__(self):
        return f"<Document {self.filename}>"
