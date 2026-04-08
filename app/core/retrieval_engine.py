"""
retrieval_engine.py — Local keyword + TF-IDF cosine search over memory JSON files.
No external vector DB. Pure Python math with collections.Counter.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Optional

from app.core.memory_store import list_memory, VALID_CATEGORIES


# ── text utilities ────────────────────────────────────────────────────────────


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split into tokens."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s_]", " ", text)
    return [t for t in text.split() if len(t) > 1]


def _term_freq(tokens: list[str]) -> Counter:
    """Return term frequency Counter from token list."""
    return Counter(tokens)


def _extract_text(record: dict) -> str:
    """
    Extract searchable text from a memory record.
    Prefers 'summary' or 'description', falls back to concatenating string values.
    """
    for key in ("summary", "description", "content", "notes", "reason"):
        val = record.get(key)
        if isinstance(val, str) and val.strip():
            return val

    # Fallback: join all string values
    parts = []
    for v in record.values():
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts.extend(str(x) for x in v if isinstance(x, str))
    return " ".join(parts)


# ── TF-IDF engine ─────────────────────────────────────────────────────────────


class TFIDFIndex:
    """
    Lightweight in-memory TF-IDF index over a list of documents.
    Built on demand; not persisted.
    """

    def __init__(self, documents: list[dict]):
        self.documents = documents
        self._doc_texts: list[str] = [_extract_text(d) for d in documents]
        self._doc_tokens: list[list[str]] = [_tokenize(t) for t in self._doc_texts]
        self._doc_tfs: list[Counter] = [_term_freq(toks) for toks in self._doc_tokens]
        self._idf: dict[str, float] = self._build_idf()

    def _build_idf(self) -> dict[str, float]:
        """Compute IDF for every term across all documents."""
        n = len(self.documents)
        if n == 0:
            return {}

        doc_freq: Counter = Counter()
        for tokens in self._doc_tokens:
            doc_freq.update(set(tokens))

        idf: dict[str, float] = {}
        for term, df in doc_freq.items():
            # Smoothed IDF
            idf[term] = math.log((n + 1) / (df + 1)) + 1.0
        return idf

    def _tfidf_vector(self, tf: Counter) -> dict[str, float]:
        """Build TF-IDF vector for a term frequency counter."""
        vec: dict[str, float] = {}
        for term, count in tf.items():
            idf = self._idf.get(term, 0.0)
            vec[term] = count * idf
        return vec

    def _cosine_similarity(self, vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
        """Compute cosine similarity between two sparse TF-IDF vectors."""
        if not vec_a or not vec_b:
            return 0.0

        dot = sum(vec_a.get(t, 0.0) * vec_b.get(t, 0.0) for t in vec_b)

        mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
        mag_b = math.sqrt(sum(v * v for v in vec_b.values()))

        if mag_a == 0.0 or mag_b == 0.0:
            return 0.0
        return dot / (mag_a * mag_b)

    def _keyword_overlap(self, query_tokens: list[str], doc_tokens: list[str]) -> float:
        """
        Simple keyword overlap score:
        count of query tokens present in doc / len(query_tokens).
        """
        if not query_tokens:
            return 0.0
        doc_set = set(doc_tokens)
        hits = sum(1 for t in query_tokens if t in doc_set)
        return hits / len(query_tokens)

    def search(self, query: str, top_k: int = 3) -> list[tuple[dict, float]]:
        """
        Search documents by query.
        Combined score = 0.5 * keyword_overlap + 0.5 * tfidf_cosine.
        Returns list of (document, score) tuples, descending by score.
        """
        if not self.documents:
            return []

        query_tokens = _tokenize(query)
        query_tf = _term_freq(query_tokens)
        query_vec = self._tfidf_vector(query_tf)

        scored: list[tuple[int, float]] = []
        for i, doc_tf in enumerate(self._doc_tfs):
            doc_vec = self._tfidf_vector(doc_tf)
            cosine = self._cosine_similarity(query_vec, doc_vec)
            keyword = self._keyword_overlap(query_tokens, self._doc_tokens[i])
            combined = 0.5 * keyword + 0.5 * cosine
            scored.append((i, combined))

        # Sort descending, take top_k
        scored.sort(key=lambda x: x[1], reverse=True)
        results = []
        for idx, score in scored[:top_k]:
            if score > 0.0:
                results.append((self.documents[idx], score))

        return results


# ── public API ────────────────────────────────────────────────────────────────


def retrieve(query: str, category: str, top_k: int = 3) -> list[dict]:
    """
    Retrieve top_k most relevant memory records for a query in a category.
    Returns list of record dicts (highest relevance first).
    Score must be > 0 to be included.
    """
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Unknown category: {category!r}")

    documents = list_memory(category)
    if not documents:
        return []

    index = TFIDFIndex(documents)
    results = index.search(query, top_k=top_k)

    # Return only the document dicts, not scores
    return [doc for doc, score in results]


def retrieve_multi(query: str, categories: list[str], top_k: int = 3) -> dict[str, list[dict]]:
    """
    Retrieve from multiple categories. Returns dict of category → results.
    """
    output: dict[str, list[dict]] = {}
    for cat in categories:
        try:
            output[cat] = retrieve(query, cat, top_k=top_k)
        except ValueError:
            output[cat] = []
    return output
