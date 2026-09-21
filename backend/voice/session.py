"""
Conversation Session Manager
==============================
Manages per-session state for real-time voice conversations.
Handles:
  • Turn-taking logic
  • Emotion / language tracking
  • Barge-in / interruption
  • Silence detection
  • Context memory (sliding window)
  • Analytics accumulation
"""

from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


@dataclass
class ConversationSession:
    session_id: str
    direction:  str = "browser"       # browser / inbound / outbound
    language:   str = "en"            # current detected language
    emotion:    str = "neutral"

    # Turn state machine
    # idle → listening → processing → speaking → idle
    state: str = "idle"

    # Message history (for LLM context)
    history: List[Dict[str, str]] = field(default_factory=list)

    # Analytics accumulators
    interruption_count:  int   = 0
    barge_in_count:      int   = 0
    silence_count:       int   = 0
    language_switches:   int   = 0
    languages_used:      set   = field(default_factory=set)
    sentiment_timeline:  List  = field(default_factory=list)
    detected_intents:    List  = field(default_factory=list)
    emotion_counts:      Dict  = field(default_factory=dict)
    response_latencies_ms: List[int] = field(default_factory=list)
    first_audio_latencies_ms: List[int] = field(default_factory=list)

    # Timing
    created_at:         float = field(default_factory=time.time)
    last_activity_at:   float = field(default_factory=time.time)
    turn_start_time:    Optional[float] = None

    # Interrupt flag — list so it's mutable from closures
    interrupt_flag: List[bool] = field(default_factory=lambda: [False])

    # DB conversation ID (set after DB record created)
    db_conversation_id: Optional[str] = None

    def set_state(self, new_state: str):
        self.state = new_state
        self.last_activity_at = time.time()

    def interrupt(self):
        self.interrupt_flag[0] = True
        self.state = "idle"

    def clear_interrupt(self):
        self.interrupt_flag[0] = False

    def is_interrupted(self) -> bool:
        return self.interrupt_flag[0]

    def add_user_message(self, content: str, emotion: str = "neutral", language: str = "en"):
        self.history.append({"role": "user", "content": content})
        self._track_emotion(emotion)
        self._track_language(language)
        self.last_activity_at = time.time()

    def add_assistant_message(self, content: str):
        self.history.append({"role": "assistant", "content": content})
        self.last_activity_at = time.time()

    def _track_emotion(self, emotion: str):
        self.emotion = emotion
        self.emotion_counts[emotion] = self.emotion_counts.get(emotion, 0) + 1
        self.sentiment_timeline.append({
            "timestamp": time.time(),
            "emotion":   emotion,
        })

    def _track_language(self, lang: str):
        if lang not in self.languages_used:
            if self.languages_used:
                self.language_switches += 1
            self.languages_used.add(lang)
        if lang != self.language:
            self.language = lang

    def get_history_slice(self, n: int = 10) -> List[Dict]:
        """Last n messages for LLM context."""
        return self.history[-n:]

    def get_dominant_emotion(self) -> str:
        if not self.emotion_counts:
            return "neutral"
        return max(self.emotion_counts, key=self.emotion_counts.get)

    def record_response_latency(
        self,
        total_ms: Optional[int],
        first_audio_ms: Optional[int],
    ):
        if total_ms is not None:
            self.response_latencies_ms.append(total_ms)
        if first_audio_ms is not None:
            self.first_audio_latencies_ms.append(first_audio_ms)

    def get_analytics_snapshot(self) -> Dict[str, Any]:
        return {
            "session_id":          self.session_id,
            "state":               self.state,
            "language":            self.language,
            "dominant_emotion":    self.get_dominant_emotion(),
            "emotion_counts":      self.emotion_counts,
            "interruption_count":  self.interruption_count,
            "barge_in_count":      self.barge_in_count,
            "language_switches":   self.language_switches,
            "languages_used":      list(self.languages_used),
            "message_count":       len(self.history),
            "duration_sec":        round(time.time() - self.created_at, 1),
            "avg_response_ms":     self._average(self.response_latencies_ms),
            "avg_first_audio_ms":  self._average(self.first_audio_latencies_ms),
        }

    def get_db_analytics(self) -> Dict[str, Any]:
        user_messages = sum(1 for item in self.history if item["role"] == "user")
        agent_messages = sum(1 for item in self.history if item["role"] == "assistant")
        return {
            "total_duration_sec": round(time.time() - self.created_at, 1),
            "avg_response_ms": self._average(self.response_latencies_ms),
            "first_response_ms": (
                self.first_audio_latencies_ms[0]
                if self.first_audio_latencies_ms
                else None
            ),
            "sentiment_timeline": self.sentiment_timeline,
            "emotion_breakdown": self.emotion_counts,
            "language_switches": self.language_switches,
            "languages_used": list(self.languages_used),
            "detected_intents": self.detected_intents,
            "interruption_count": self.interruption_count,
            "barge_in_count": self.barge_in_count,
            "silence_count": self.silence_count,
            "user_message_count": user_messages,
            "agent_message_count": agent_messages,
        }

    @staticmethod
    def _average(values: List[int]) -> Optional[float]:
        if not values:
            return None
        return round(sum(values) / len(values), 1)

    def get_full_transcript(self) -> str:
        lines = []
        for msg in self.history:
            speaker = "Priya" if msg["role"] == "assistant" else "Student"
            lines.append(f"{speaker}: {msg['content']}")
        return "\n".join(lines)


# ── Session Registry ──────────────────────────────────────────────────────────
class SessionRegistry:
    def __init__(self):
        self._sessions: Dict[str, ConversationSession] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        session_id: str,
        direction: str = "browser",
    ) -> ConversationSession:
        async with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = ConversationSession(
                    session_id=session_id,
                    direction=direction,
                )
            return self._sessions[session_id]

    def get(self, session_id: str) -> Optional[ConversationSession]:
        return self._sessions.get(session_id)

    async def remove(self, session_id: str) -> Optional[ConversationSession]:
        async with self._lock:
            return self._sessions.pop(session_id, None)

    def list_active(self) -> List[Dict]:
        return [s.get_analytics_snapshot() for s in self._sessions.values()]

    def count(self) -> int:
        return len(self._sessions)


# Singleton
registry = SessionRegistry()
