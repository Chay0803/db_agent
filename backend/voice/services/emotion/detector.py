"""
Emotion & Sentiment Detection Service
======================================
Dual-mode:
  1. Keyword heuristic  — always fast, zero-cost, works offline
  2. HuggingFace model  — loaded lazily for richer detection when available

Detected emotions:  happy | frustrated | confused | angry | neutral | sad | hesitant
"""

from __future__ import annotations
import os
import re
from typing import Dict, Tuple, Optional
import asyncio
from concurrent.futures import ThreadPoolExecutor

# ── Keyword maps ──────────────────────────────────────────────────────────────
_EMOTION_KEYWORDS: Dict[str, set] = {
    "frustrated": {
        "frustrated", "annoyed", "irritated", "fed up", "tired of", "sick of",
        "waste", "ridiculous", "terrible", "horrible", "awful", "pathetic",
        "useless", "worst", "rubbish", "nonsense", "stupid",
        # Hindi/Telugu transliterations
        "pareshan", "chidchida", "gussa", "takleef",
    },
    "angry": {
        "angry", "furious", "rage", "enraged", "outraged", "livid",
        "maddenning", "hell", "damn", "hate", "screw", "unacceptable",
        "never", "worst ever", "lawsuit", "complain",
    },
    "confused": {
        "confused", "don't understand", "doesn't make sense", "unclear", "what do you mean",
        "what?", "huh?", "repeat", "come again", "not clear", "lost", "confusing",
        "how does", "can you explain", "explain again", "don't get it",
        "samajh nahi", "samajh mein nahi",
    },
    "happy": {
        "great", "excellent", "wonderful", "amazing", "fantastic", "love it",
        "perfect", "awesome", "thank you", "thanks", "helpful", "appreciate",
        "good", "nice", "pleased", "glad", "excited", "wow", "bahut acha",
        "shukriya", "dhanyawad",
    },
    "sad": {
        "sad", "disappointed", "unfortunate", "unlucky", "failed", "rejected",
        "bad luck", "heartbroken", "sorry to hear", "difficult situation",
        "struggling", "dukh", "dard",
    },
    "hesitant": {
        "maybe", "i think", "not sure", "perhaps", "possibly", "probably",
        "hmm", "um", "uh", "i guess", "kind of", "sort of", "shayad", "lagta hai",
    },
}

_NEGATIVE_WORDS = {
    "not", "no", "never", "bad", "confused", "worried", "expensive", "reject",
    "rejected", "fail", "failed", "difficult", "hard", "problem", "issue",
    "sad", "disappointed", "angry", "upset", "wrong", "poor", "terrible",
}

_EXECUTOR = ThreadPoolExecutor(max_workers=1)

# ── Lazy HuggingFace model ────────────────────────────────────────────────────
_hf_pipeline = None
_hf_tried    = False


def _try_load_hf():
    global _hf_pipeline, _hf_tried
    if _hf_tried:
        return
    _hf_tried = True
    try:
        from transformers import pipeline
        _hf_pipeline = pipeline(
            "text-classification",
            model="j-hartmann/emotion-english-distilroberta-base",
            top_k=None,
            device=-1,      # CPU
        )
        print("HuggingFace emotion model loaded.")
    except Exception as e:
        print(f"HuggingFace emotion model unavailable ({e}). Using keyword fallback.")
        _hf_pipeline = None


# ── Keyword-based detection ───────────────────────────────────────────────────
def _keyword_emotion(text: str) -> Tuple[str, float, Dict[str, float]]:
    lower = text.lower()
    scores: Dict[str, float] = {}

    for emotion, keywords in _EMOTION_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in lower)
        scores[emotion] = min(count / max(len(keywords) * 0.1, 1), 1.0)

    if not any(scores.values()):
        scores["neutral"] = 1.0
        return "neutral", 0.0, scores

    top = max(scores, key=scores.get)
    # Map to sentiment score
    sentiment_map = {
        "happy": 0.8, "neutral": 0.0, "hesitant": -0.1,
        "confused": -0.3, "sad": -0.5, "frustrated": -0.7, "angry": -0.9,
    }
    return top, sentiment_map.get(top, 0.0), scores


# ── HuggingFace-based detection ───────────────────────────────────────────────
def _hf_emotion(text: str) -> Tuple[str, float, Dict[str, float]]:
    if _hf_pipeline is None:
        return _keyword_emotion(text)
    try:
        results = _hf_pipeline(text[:512])
        # results is list of list of {label, score}
        scores_raw = results[0] if isinstance(results[0], list) else results
        scores = {r["label"].lower(): round(r["score"], 3) for r in scores_raw}

        # Map HuggingFace labels → our labels
        label_map = {
            "joy": "happy", "anger": "angry", "sadness": "sad",
            "fear": "hesitant", "disgust": "frustrated", "surprise": "confused",
            "neutral": "neutral",
        }
        mapped: Dict[str, float] = {}
        for k, v in scores.items():
            mapped[label_map.get(k, k)] = v

        top = max(mapped, key=mapped.get)
        sentiment_map = {
            "happy": 0.8, "neutral": 0.0, "hesitant": -0.1,
            "confused": -0.3, "sad": -0.5, "frustrated": -0.7, "angry": -0.9,
        }
        return top, sentiment_map.get(top, 0.0), mapped
    except Exception:
        return _keyword_emotion(text)


# ── Public async API ──────────────────────────────────────────────────────────
async def detect_emotion_async(text: str) -> Dict:
    """
    Returns:
        {
          "emotion":         "frustrated",
          "sentiment_score": -0.7,       # -1.0 (very negative) to +1.0 (very positive)
          "sentiment_label": "negative", # positive / negative / neutral
          "scores":          { "frustrated": 0.6, "angry": 0.2, ... }
        }
    """
    if os.getenv("ENABLE_TRANSFORMER_EMOTION", "false").lower() == "true":
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(_EXECUTOR, _try_load_hf)

    loop = asyncio.get_running_loop()
    emotion, score, all_scores = await loop.run_in_executor(
        _EXECUTOR,
        lambda: _hf_emotion(text),
    )

    if score >= 0.2:
        label = "positive"
    elif score <= -0.2:
        label = "negative"
    else:
        label = "neutral"

    return {
        "emotion":         emotion,
        "sentiment_score": round(score, 3),
        "sentiment_label": label,
        "scores":          all_scores,
    }


def detect_emotion_sync(text: str) -> Dict:
    """Synchronous version — use in non-async contexts."""
    if os.getenv("ENABLE_TRANSFORMER_EMOTION", "false").lower() == "true":
        _try_load_hf()
    emotion, score, all_scores = _hf_emotion(text)
    if score >= 0.2:
        label = "positive"
    elif score <= -0.2:
        label = "negative"
    else:
        label = "neutral"
    return {
        "emotion": emotion,
        "sentiment_score": round(score, 3),
        "sentiment_label": label,
        "scores": all_scores,
    }


# The optional HuggingFace model is loaded lazily on first use. Loading it in a
# background thread during app import can race with sentence-transformers while
# both import torch, which can deadlock backend startup on Windows.
