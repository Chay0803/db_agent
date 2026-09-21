"""
RAG Service — FAISS + SentenceTransformers
============================================
Improvements over original:
• Persistent FAISS index (same as original)
• Embedding cache (avoid re-computing for identical queries)
• Async search
• Better chunking (semantic-aware)
• Metadata per chunk (source doc, page)
• Top-k with score filtering
• Support for multilingual queries
"""

from __future__ import annotations
import io
import os
import pickle
import asyncio
import hashlib
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

# ── Config ────────────────────────────────────────────────────────────────────
FAISS_PATH    = Path(os.getenv("FAISS_PATH", "data/faiss_store.pkl"))
CHUNKS_PATH   = Path(os.getenv("CHUNKS_PATH", "data/doc_chunks.pkl"))
CHUNK_META_PATH = Path(os.getenv("CHUNK_META_PATH", "data/chunk_meta.pkl"))
EMBED_MODEL   = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
CHUNK_SIZE    = int(os.getenv("CHUNK_SIZE", "300"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "60"))
TOP_K         = int(os.getenv("RAG_TOP_K", "4"))
SCORE_THRESH  = float(os.getenv("RAG_SCORE_THRESHOLD", "1.5"))  # L2 distance — lower is better

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rag")

# ── Embedding model (global, loaded once) ────────────────────────────────────
_embed_model: Optional[SentenceTransformer] = None


def _get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        print(f"Loading embedding model ({EMBED_MODEL})...")
        _embed_model = SentenceTransformer(EMBED_MODEL)
        print("Embedding model ready.")
    return _embed_model


# ── Chunk metadata ─────────────────────────────────────────────────────────────
# chunk_meta[i] = {"source": filename, "page": n, "chunk_idx": m}
doc_chunks:  List[str]            = []
chunk_meta:  List[Dict[str, Any]] = []
faiss_index: Optional[faiss.Index] = None

# ── Embedding cache ────────────────────────────────────────────────────────────
_embed_cache: Dict[str, np.ndarray] = {}


def _cache_key(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _encode(texts: List[str]) -> np.ndarray:
    model = _get_embed_model()
    uncached = []
    indices  = []
    result   = np.zeros((len(texts), 384), dtype="float32")

    for i, t in enumerate(texts):
        key = _cache_key(t)
        if key in _embed_cache:
            result[i] = _embed_cache[key]
        else:
            uncached.append((i, t, key))

    if uncached:
        batch_texts   = [x[1] for x in uncached]
        batch_embeds  = model.encode(batch_texts, show_progress_bar=False, batch_size=32)
        for j, (i, t, key) in enumerate(uncached):
            _embed_cache[key] = batch_embeds[j]
            result[i] = batch_embeds[j]

    return result


# ── Persistence ────────────────────────────────────────────────────────────────
def _load_store():
    global doc_chunks, chunk_meta, faiss_index

    FAISS_PATH.parent.mkdir(parents=True, exist_ok=True)

    if CHUNKS_PATH.exists() and FAISS_PATH.exists():
        with open(CHUNKS_PATH, "rb") as f:
            doc_chunks = pickle.load(f)
        with open(FAISS_PATH, "rb") as f:
            faiss_index = pickle.load(f)
        if CHUNK_META_PATH.exists():
            with open(CHUNK_META_PATH, "rb") as f:
                chunk_meta[:] = pickle.load(f)
        else:
            chunk_meta[:] = [{"source": "unknown", "page": 0}] * len(doc_chunks)
        print(f"RAG: loaded {len(doc_chunks)} chunks from disk.")
    else:
        print("RAG: no existing index found - will build on first document upload.")


def _save_store():
    with open(CHUNKS_PATH, "wb") as f:
        pickle.dump(doc_chunks, f)
    with open(FAISS_PATH, "wb") as f:
        pickle.dump(faiss_index, f)
    with open(CHUNK_META_PATH, "wb") as f:
        pickle.dump(chunk_meta, f)


def _rebuild_faiss():
    global faiss_index
    if not doc_chunks:
        faiss_index = None
        return
    embeddings = _encode(doc_chunks)
    dim = embeddings.shape[1]
    idx = faiss.IndexFlatL2(dim)
    idx.add(embeddings)
    faiss_index = idx


# ── Text chunking (improved) ──────────────────────────────────────────────────
def chunk_text(text: str, source: str = "unknown", page: int = 0) -> Tuple[List[str], List[Dict]]:
    """
    Returns (chunks, metadata_list).
    Splits on paragraph boundaries first, then word windows.
    """
    # Split on double newlines (paragraphs) first
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    words_meta: List[Tuple[str, str, int]] = []  # (word, source, page)

    for para in paragraphs:
        words = para.split()
        words_meta.extend((w, source, page) for w in words)

    step   = max(1, CHUNK_SIZE - CHUNK_OVERLAP)
    chunks = []
    metas  = []

    for i in range(0, max(1, len(words_meta)), step):
        batch = words_meta[i : i + CHUNK_SIZE]
        if not batch:
            continue
        chunk_words = [w[0] for w in batch]
        chunks.append(" ".join(chunk_words))
        metas.append({"source": source, "page": page, "chunk_idx": i})

    return chunks, metas


# ── Public API ────────────────────────────────────────────────────────────────
def add_document(text: str, source: str = "unknown", page: int = 0):
    """Add text chunks to the in-memory store and rebuild FAISS."""
    global faiss_index
    chunks, metas = chunk_text(text, source, page)
    doc_chunks.extend(chunks)
    chunk_meta.extend(metas)
    _rebuild_faiss()
    _save_store()
    return len(chunks)


def search_sync(query: str, top_k: int = TOP_K) -> List[Dict[str, Any]]:
    """
    Synchronous RAG search.
    Returns list of {"text": str, "source": str, "score": float}
    """
    if faiss_index is None or not doc_chunks:
        return []

    q_vec = _encode([query])
    scores, indices = faiss_index.search(q_vec, min(top_k * 2, len(doc_chunks)))

    results = []
    seen    = set()
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0 or idx >= len(doc_chunks):
            continue
        if score > SCORE_THRESH:     # too distant
            continue
        text = doc_chunks[idx]
        if text in seen:
            continue
        seen.add(text)
        meta = chunk_meta[idx] if idx < len(chunk_meta) else {}
        results.append({
            "text":   text,
            "source": meta.get("source", "unknown"),
            "score":  float(score),
        })
        if len(results) >= top_k:
            break

    return results


async def search(query: str, top_k: int = TOP_K) -> List[Dict[str, Any]]:
    """Async RAG search."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, lambda: search_sync(query, top_k))


async def warmup():
    """Load the embedding model before the first customer turn."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, lambda: _encode(["admissions"]))


def get_context_text(results: List[Dict]) -> str:
    """Format RAG results into a context block for the LLM prompt."""
    if not results:
        return ""
    parts = []
    for r in results:
        source = r.get("source", "Document")
        parts.append(f"[From: {source}]\n{r['text']}")
    return "\n\n".join(parts)


def status() -> Dict[str, Any]:
    return {
        "total_chunks": len(doc_chunks),
        "faiss_ready":  faiss_index is not None,
        "embed_cache_size": len(_embed_cache),
    }


# ── Auto-ingest data/ folder at startup ──────────────────────────────────────
def ingest_folder(folder: str = "data"):
    """Scan folder for PDFs/DOCX/TXT and ingest any not already indexed."""
    import pdfplumber
    from docx import Document as DocxDocument

    ingested_path = Path(folder) / ".ingested.pkl"
    ingested: set = set()
    if ingested_path.exists():
        with open(ingested_path, "rb") as f:
            ingested = pickle.load(f)

    folder_path = Path(folder)
    folder_path.mkdir(exist_ok=True)
    files = (
        list(folder_path.glob("*.pdf"))
        + list(folder_path.glob("*.docx"))
        + list(folder_path.glob("*.txt"))
    )
    new_files = [f for f in files if str(f) not in ingested]

    if not new_files:
        print(f"{folder}: all {len(files)} file(s) already indexed.")
        return

    for fp in new_files:
        try:
            name = fp.name.lower()
            if name.endswith(".pdf"):
                text = ""
                with pdfplumber.open(str(fp)) as pdf:
                    for page in pdf.pages:
                        text += (page.extract_text() or "") + "\n"
            elif name.endswith(".docx"):
                doc = DocxDocument(str(fp))
                text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            else:
                text = fp.read_text(encoding="utf-8", errors="ignore")

            if not text.strip():
                continue

            n = add_document(text, source=fp.name)
            ingested.add(str(fp))
            print(f"  {fp.name} - {n} chunks added.")
        except Exception as e:
            print(f"  {fp.name}: {e}")

    with open(ingested_path, "wb") as f:
        pickle.dump(ingested, f)


# ── Load at import time ───────────────────────────────────────────────────────
_load_store()