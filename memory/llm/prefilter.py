"""Stage 1 of the compressor: cheap relevance pre-filter.

Extracts text, chunks it, and keeps only the chunks most relevant to the task
objective so that fewer tokens are sent to the frontier model. Relevance uses
Voyage embeddings when a key is present, with a dependency-free lexical fallback.
"""

from __future__ import annotations

import os
import re

from memory.llm.tokens import count_tokens

# Decoupled from memory.core to avoid pulling in the Redis import chain here.
EMBED_MODEL = os.getenv("VOYAGE_EMBED_MODEL", "voyage-3.5-lite")

_PDF_TEXT_MAX_CHARS = 400_000
_WORD_RE = re.compile(r"[a-z0-9]+")


def extract_pdf_text(pdf_path: str, max_chars: int = _PDF_TEXT_MAX_CHARS) -> str:
    """Extract text from a local PDF using pypdf (best-effort, never raises)."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        parts = [page.extract_text() or "" for page in reader.pages]
        full = "\n".join(parts).strip()
    except Exception:
        return ""
    if len(full) > max_chars:
        full = full[:max_chars]
    return full


def chunk_text(text: str, target_tokens: int = 512) -> list[str]:
    """Pack paragraphs greedily into chunks of roughly target_tokens each."""
    text = (text or "").strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for para in paragraphs:
        para_tokens = count_tokens(para)
        if buf and buf_tokens + para_tokens > target_tokens:
            chunks.append("\n\n".join(buf))
            buf, buf_tokens = [], 0
        buf.append(para)
        buf_tokens += para_tokens
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


def _embed(texts: list[str], input_type: str) -> list[list[float]]:
    """Embed via Voyage. Raises if unavailable so callers can fall back."""
    import voyageai

    client = voyageai.Client()
    return client.embed(texts, model=EMBED_MODEL, input_type=input_type).embeddings


def _cosine_scores(query_vec, chunk_vecs) -> list[float]:
    import numpy as np

    q = np.asarray(query_vec, dtype=np.float32)
    m = np.asarray(chunk_vecs, dtype=np.float32)
    qn = q / (np.linalg.norm(q) + 1e-9)
    mn = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
    return (mn @ qn).tolist()


def _lexical_scores(chunks: list[str], objective: str) -> list[float]:
    keywords = set(_WORD_RE.findall(objective.lower()))
    if not keywords:
        return [0.0] * len(chunks)
    scores = []
    for chunk in chunks:
        words = _WORD_RE.findall(chunk.lower())
        if not words:
            scores.append(0.0)
            continue
        hits = sum(1 for w in words if w in keywords)
        scores.append(hits / (len(words) ** 0.5))
    return scores


def score_chunks(chunks: list[str], objective: str) -> tuple[list[float], str]:
    """Return (scores, method) where method is 'embedding' or 'lexical'."""
    if not chunks:
        return [], "none"
    try:
        qv = _embed([objective], input_type="query")[0]
        cvs = _embed(chunks, input_type="document")
        return _cosine_scores(qv, cvs), "embedding"
    except Exception:
        return _lexical_scores(chunks, objective), "lexical"


def select_relevant(
    chunks: list[str],
    objective: str,
    token_budget: int,
) -> dict:
    """Greedily keep the highest-scoring chunks under token_budget.

    Returns a dict with the joined selected text, the indices kept (in original
    order), the scoring method used, and counts for the manifest.
    """
    if not chunks:
        return {
            "text": "",
            "kept_indices": [],
            "method": "none",
            "chunks_total": 0,
            "chunks_kept": 0,
        }

    scores, method = score_chunks(chunks, objective)
    order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)

    kept: list[int] = []
    used = 0
    for i in order:
        cost = count_tokens(chunks[i])
        if kept and used + cost > token_budget:
            continue
        kept.append(i)
        used += cost
        if used >= token_budget:
            break

    kept.sort()
    selected_text = "\n\n".join(chunks[i] for i in kept)
    return {
        "text": selected_text,
        "kept_indices": kept,
        "method": method,
        "chunks_total": len(chunks),
        "chunks_kept": len(kept),
    }
