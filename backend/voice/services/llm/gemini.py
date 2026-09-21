"""
LLM Service — Gemini 3.1 Flash-Lite
================================
• Streaming token-by-token output
• Emotion-aware system prompts
• Multilingual responses (English / Hindi / Telugu)
• Lead extraction from conversation
• Intent detection
• Keeps history context
"""

from __future__ import annotations
import os
import re
import asyncio
import json
from typing import List, Dict, Any, AsyncGenerator, Optional
from concurrent.futures import ThreadPoolExecutor

from google import genai

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="llm")

# ── Client ────────────────────────────────────────────────────────────────────
_api_key = os.getenv("GEMINI_API_KEY", "")
_client  = genai.Client(api_key=_api_key) if _api_key else None
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
LLM_TIMEOUT_SEC = float(os.getenv("LLM_TIMEOUT_SEC", "20"))
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "128"))

AGENT_NAME        = os.getenv("AGENT_NAME", "Priya")
AGENT_INSTITUTION = os.getenv("AGENT_INSTITUTION", "ICFAI University Hyderabad")

# ── System prompt ─────────────────────────────────────────────────────────────
_BASE_SYSTEM = f"""You are {AGENT_NAME}, an admission counselor at {AGENT_INSTITUTION}.

VOICE RULES: Reply in 1-2 short spoken sentences only. Keep each sentence under 12 words. No bullet points, dashes, asterisks or markdown. End with one short follow-up question when useful. Stay on topic: admissions, programmes, fees, campus, placements, eligibility. Use knowledge-base context as truth. Never invent fees, dates or criteria. Be warm and encouraging. Never open with a greeting like Namaste or Hello — the conversation is already in progress. When student says no or declines, acknowledge briefly and offer one alternative topic only.

LANGUAGE: Reply in the same language the student uses (English/Hindi/Telugu). Never switch unless they do.

EMOTION: frustrated→acknowledge warmly first. confused→simplify and ask if clear. angry→stay calm, be brief. happy→match energy. sad→be gentle."""

_EMOTION_OVERLAYS = {
    "frustrated": "The student sounds frustrated. Be extra empathetic and patient. Acknowledge their frustration first.",
    "angry":      "The student sounds angry. Stay very calm, be brief, and offer concrete solutions.",
    "confused":   "The student is confused. Break down your explanation into simple steps. Ask confirming questions.",
    "happy":      "The student is happy. Match their energy. Be warm and engaging.",
    "sad":        "The student sounds sad or disappointed. Be very gentle and reassuring.",
    "hesitant":   "The student sounds hesitant or unsure. Be encouraging and supportive.",
    "neutral":    "",
}

# ── Prompt builder ────────────────────────────────────────────────────────────
def build_prompt(
    history: List[Dict],
    emotion: str,
    language: str,
    context_text: str,
    query: str,
) -> str:
    system = _BASE_SYSTEM
    overlay = _EMOTION_OVERLAYS.get(emotion, "")
    if overlay:
        system += f"\n\nCURRENT STUDENT EMOTION: {overlay}"

    lang_instruction = {
        "hi": "\n\nIMPORTANT: The student is speaking Hindi. Reply entirely in Hindi (Roman Hindi is fine).",
        "te": "\n\nIMPORTANT: The student is speaking Telugu. Reply in Telugu or Roman Telugu.",
        "en": "",
    }.get(language, "")
    system += lang_instruction

    ctx_block = (
        f"RELEVANT INFORMATION FROM KNOWLEDGE BASE:\n{context_text}"
        if context_text
        else "No specific document context found — answer from general knowledge about the institution."
    )

    hist_block = "\n".join(
        f"{'Priya' if h['role'] == 'assistant' else 'Student'}: {h['content']}"
        for h in history[-6:]
    )

    return f"""{system}

---
{ctx_block}

---
CONVERSATION HISTORY:
{hist_block}

---
Student: {query}

{AGENT_NAME} (1-2 brief spoken sentences, no markdown):"""


# ── Streaming generator adapter ───────────────────────────────────────────────
async def _stream_gemini(prompt: str) -> AsyncGenerator[str, None]:
    """Convert Gemini sync streaming to async generator."""
    if not _client:
        yield "I'm sorry, the AI service is not configured. Please check the API key."
        return

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

    def _run():
        try:
            stream = _client.models.generate_content_stream(
                model=MODEL_NAME,
                contents=prompt,
                config={
                    "thinking_config": {"thinking_budget": 0},
                    "max_output_tokens": LLM_MAX_OUTPUT_TOKENS,
                    "temperature": 0.3,
                },
            )
            for chunk in stream:
                if chunk.text:
                    asyncio.run_coroutine_threadsafe(queue.put(chunk.text), loop)
        except Exception as e:
            print(f"[gemini stream] {e}")
            asyncio.run_coroutine_threadsafe(
                queue.put(
                    "I'm sorry, I could not reach the AI service just now. "
                    "Please try that question once more."
                ),
                loop,
            )
        asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    loop.run_in_executor(_executor, _run)

    while True:
        try:
            token = await asyncio.wait_for(queue.get(), timeout=LLM_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            yield (
                "I'm sorry, the response is taking longer than expected. "
                "Please try again in a moment."
            )
            break
        if token is None:
            break
        yield token


async def stream_response(
    history: List[Dict],
    query: str,
    emotion: str = "neutral",
    language: str = "en",
    context_text: str = "",
) -> AsyncGenerator[str, None]:
    """
    Main LLM streaming entry point.
    Yields tokens as they arrive from Gemini.
    """
    prompt = build_prompt(history, emotion, language, context_text, query)
    async for token in _stream_gemini(prompt):
        yield token


async def get_full_response(
    history: List[Dict],
    query: str,
    emotion: str = "neutral",
    language: str = "en",
    context_text: str = "",
) -> str:
    """Non-streaming — collects full response. Used for text-only /chat endpoint."""
    if not _client:
        return "I'm sorry, the AI service is not configured."

    prompt = build_prompt(history, emotion, language, context_text, query)
    loop   = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _executor,
        lambda: _client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config={
                "thinking_config": {"thinking_budget": 0},
                "max_output_tokens": LLM_MAX_OUTPUT_TOKENS,
                "temperature": 0.3,
            },
        ),
    )
    return result.text.strip()


# ── Lead extraction ───────────────────────────────────────────────────────────
_LEAD_PROMPT = """Extract structured information from this conversation transcript. 
Return ONLY a valid JSON object (no markdown, no explanation) with these fields:
{
  "name": null or "string",
  "phone": null or "string",
  "email": null or "string",
  "city": null or "string",
  "programs": null or ["list of programs mentioned"],
  "stream": null or "Science/Commerce/Arts/Engineering",
  "graduation_year": null or integer,
  "interests": null or ["list of interests/topics discussed"]
}

Conversation:
"""


async def extract_lead_info(transcript: str) -> Dict[str, Any]:
    """Extract lead information from a conversation transcript."""
    if not _client or len(transcript) < 50:
        return {}
    try:
        loop   = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _executor,
            lambda: _client.models.generate_content(
                model=MODEL_NAME,
                contents=_LEAD_PROMPT + transcript[:3000],
            ),
        )
        raw = result.text.strip()
        # Strip possible markdown fences
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        return json.loads(raw)
    except Exception as e:
        print(f"[lead extraction] error: {e}")
        return {}


# ── Intent detection ──────────────────────────────────────────────────────────
_INTENT_KEYWORDS = {
    "fee_inquiry":      ["fee", "fees", "cost", "price", "charges", "tuition", "scholarship"],
    "program_inquiry":  ["course", "program", "degree", "bba", "mba", "btech", "mtech", "bsc", "msc"],
    "admission_process": ["apply", "application", "admission", "entrance", "exam", "eligibility", "criteria"],
    "campus_info":      ["campus", "hostel", "facilities", "library", "lab", "sports", "canteen"],
    "placement_info":   ["placement", "job", "salary", "package", "company", "recruit", "career"],
    "contact_info":     ["contact", "phone", "email", "address", "location", "reach"],
    "date_inquiry":     ["deadline", "last date", "when", "date", "schedule", "timing"],
    "general_query":    [],
}


def detect_intent(text: str) -> str:
    lower = text.lower()
    for intent, keywords in _INTENT_KEYWORDS.items():
        if intent == "general_query":
            continue
        if any(kw in lower for kw in keywords):
            return intent
    return "general_query"
