"""Hybrid RAG retrieval: BM25 + dense (FAISS) -> reciprocal-rank fusion -> cross-encoder rerank.

Design:
- Two candidate generators (dense MiniLM embeddings + BM25) each return top-N.
- Their rankings are merged by Reciprocal Rank Fusion (RRF) — the standard
  ensemble trick that needs no score calibration.
- The fused top-N is then reranked by a cross-encoder
  (`cross-encoder/ms-marco-MiniLM-L-6-v2`) which actually scores query-passage
  pairs rather than cosine-distance of separately embedded texts. This is the
  step that separates toy RAG from production RAG.
- `retrieve()` is backwards-compatible with the old API (single `query` + `k`).
- `retrieve(..., filters=...)` adds service/compliance/doc_type filtering at
  query time — chunks are tagged at ingest, filters are applied before scoring.
- Every optional dep (faiss, sentence_transformers, rank_bm25, CrossEncoder) is
  guarded: if missing, the retriever silently falls back to whatever is
  available, or returns []. This matches the project's fail-silent contract.
"""
from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parent
INDEX_DIR = ROOT / "knowledge_base" / ".index"

# How many candidates each retriever produces before fusion/rerank.
CANDIDATES_PER_RETRIEVER = 20
# Target final K before rerank trims it further.
FUSED_POOL = 20
# Cross-encoder sees at most this many candidates (bounded for latency).
RERANK_POOL = 20
# RRF constant — 60 is the value from the original RRF paper, widely used.
RRF_K = 60

_cache: Dict[str, Any] = {
    "attempted": False,
    "index": None,
    "chunks": None,
    "model": None,
    "bm25": None,
    "cross_encoder": None,
    "cross_encoder_attempted": False,
}


def _load() -> bool:
    if _cache["attempted"]:
        return _cache["chunks"] is not None
    _cache["attempted"] = True

    chunks_path = INDEX_DIR / "chunks.pkl"
    if not chunks_path.exists():
        return False

    try:
        with open(chunks_path, "rb") as f:
            _cache["chunks"] = pickle.load(f)
    except Exception:
        return False

    # Dense index — optional. If missing, we still do BM25-only.
    try:
        import faiss  # type: ignore
        from sentence_transformers import SentenceTransformer  # type: ignore

        faiss_path = INDEX_DIR / "faiss.bin"
        if faiss_path.exists():
            _cache["index"] = faiss.read_index(str(faiss_path))
            _cache["model"] = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        _cache["index"] = None
        _cache["model"] = None

    # BM25 — optional. If missing, we still do dense-only.
    try:
        from rank_bm25 import BM25Okapi  # type: ignore

        tokens_path = INDEX_DIR / "bm25_tokens.pkl"
        if tokens_path.exists():
            with open(tokens_path, "rb") as f:
                tokenized = pickle.load(f)
            _cache["bm25"] = BM25Okapi(tokenized)
    except Exception:
        _cache["bm25"] = None

    return True


def _load_cross_encoder():
    if _cache["cross_encoder_attempted"]:
        return _cache["cross_encoder"]
    _cache["cross_encoder_attempted"] = True
    try:
        from sentence_transformers import CrossEncoder  # type: ignore

        _cache["cross_encoder"] = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    except Exception:
        _cache["cross_encoder"] = None
    return _cache["cross_encoder"]


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
def _matches_filters(chunk: dict, filters: Optional[Dict[str, Any]]) -> bool:
    if not filters:
        return True
    for key, want in filters.items():
        have = chunk.get(key)
        if want is None:
            continue
        if isinstance(want, (list, tuple, set)):
            wants = set(want)
            if isinstance(have, list):
                if not wants & set(have):
                    return False
            else:
                if have not in wants:
                    return False
        else:
            if isinstance(have, list):
                if want not in have:
                    return False
            elif have != want:
                return False
    return True


# ---------------------------------------------------------------------------
# Tokenization (must match ingest)
# ---------------------------------------------------------------------------
import re

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


# ---------------------------------------------------------------------------
# Candidate generators
# ---------------------------------------------------------------------------
def _dense_candidates(query: str, allowed_idxs: Optional[set], n: int) -> List[int]:
    model = _cache["model"]
    index = _cache["index"]
    chunks = _cache["chunks"]
    if model is None or index is None or chunks is None:
        return []
    try:
        import faiss  # type: ignore
    except Exception:
        return []
    vec = model.encode([query], convert_to_numpy=True)
    faiss.normalize_L2(vec)
    # Over-fetch so we still have n candidates after filtering.
    search_k = min(len(chunks), n * 5 if allowed_idxs else n)
    _, I = index.search(vec, search_k)
    out: List[int] = []
    for idx in I[0]:
        if idx < 0 or idx >= len(chunks):
            continue
        if allowed_idxs is not None and idx not in allowed_idxs:
            continue
        out.append(int(idx))
        if len(out) >= n:
            break
    return out


def _bm25_candidates(query: str, allowed_idxs: Optional[set], n: int) -> List[int]:
    bm25 = _cache["bm25"]
    chunks = _cache["chunks"]
    if bm25 is None or chunks is None:
        return []
    tokens = _tokenize(query)
    if not tokens:
        return []
    scores = bm25.get_scores(tokens)
    # Indices sorted by score desc; filter then truncate
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    out: List[int] = []
    for idx in ranked:
        if allowed_idxs is not None and idx not in allowed_idxs:
            continue
        if scores[idx] <= 0:
            break
        out.append(idx)
        if len(out) >= n:
            break
    return out


def _rrf(*rankings: List[int], k: int = RRF_K) -> List[int]:
    """Reciprocal Rank Fusion. Each ranking is a list of doc ids best-first."""
    scores: Dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.keys(), key=lambda i: scores[i], reverse=True)


def _rerank(query: str, candidate_idxs: List[int]) -> List[tuple]:
    """Cross-encoder rerank. Returns list of (idx, score) best-first.

    Falls back to identity ordering with neutral scores if the encoder is not
    available.
    """
    chunks = _cache["chunks"]
    if not candidate_idxs or chunks is None:
        return [(i, 0.0) for i in candidate_idxs]
    ce = _load_cross_encoder()
    if ce is None:
        return [(i, 1.0 / (rank + 1)) for rank, i in enumerate(candidate_idxs)]
    pairs = [(query, chunks[i]["text"]) for i in candidate_idxs]
    try:
        scores = ce.predict(pairs)
    except Exception:
        return [(i, 1.0 / (rank + 1)) for rank, i in enumerate(candidate_idxs)]
    pairs_with_scores = list(zip(candidate_idxs, [float(s) for s in scores]))
    pairs_with_scores.sort(key=lambda p: p[1], reverse=True)
    return pairs_with_scores


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def retrieve(
    query: str,
    k: int = 5,
    filters: Optional[Dict[str, Any]] = None,
    rerank: bool = True,
) -> List[dict]:
    """Hybrid retrieval with RRF fusion and optional cross-encoder rerank.

    Args:
        query: user query.
        k: final number of results to return.
        filters: optional metadata filter, e.g. {"service": "s3",
                 "compliance": "HIPAA"}. Values may be scalar or list.
        rerank: if True, cross-encoder reranks the RRF-fused top pool.

    Returns:
        List of dicts with keys: rank, score, source, snippet, service,
        compliance, doc_type, header_path.
    """
    if not _load():
        return []
    chunks = _cache["chunks"]
    if not chunks:
        return []

    allowed_idxs: Optional[set] = None
    if filters:
        allowed_idxs = {i for i, c in enumerate(chunks) if _matches_filters(c, filters)}
        if not allowed_idxs:
            return []

    dense = _dense_candidates(query, allowed_idxs, CANDIDATES_PER_RETRIEVER)
    bm25 = _bm25_candidates(query, allowed_idxs, CANDIDATES_PER_RETRIEVER)

    if not dense and not bm25:
        return []

    # Fuse — if only one retriever fired, RRF degenerates to that ordering.
    fused = _rrf(dense, bm25)[:FUSED_POOL]

    if rerank:
        ranked = _rerank(query, fused[:RERANK_POOL])
    else:
        ranked = [(idx, 1.0 / (r + 1)) for r, idx in enumerate(fused)]

    results: List[dict] = []
    for rank, (idx, score) in enumerate(ranked[:k]):
        c = chunks[idx]
        results.append({
            "rank": rank,
            "score": float(score),
            "source": c["source"],
            "snippet": c["text"][:400],
            "service": c.get("service"),
            "compliance": c.get("compliance") or [],
            "doc_type": c.get("doc_type"),
            "header_path": c.get("header_path") or [],
        })
    return results
