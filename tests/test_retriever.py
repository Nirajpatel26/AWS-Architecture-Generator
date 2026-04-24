"""Retriever tests — we never depend on a real FAISS index being built."""
import importlib
import sys

from rag import retriever


def _fresh():
    """Re-import to reset the module-level _cache singleton between tests."""
    importlib.reload(retriever)
    return retriever


def test_missing_index_returns_empty_list(tmp_path, monkeypatch):
    r = _fresh()
    monkeypatch.setattr(r, "INDEX_DIR", tmp_path / "nope")
    assert r.retrieve("anything") == []


def test_load_failure_is_sticky(tmp_path, monkeypatch):
    """After a failed load, subsequent calls must not retry (and must not crash)."""
    r = _fresh()
    monkeypatch.setattr(r, "INDEX_DIR", tmp_path / "nope")
    assert r.retrieve("foo") == []
    assert r.retrieve("bar") == []
    assert r._cache["attempted"] is True


class _FakeIndex:
    def __init__(self, order):
        self._order = order

    def search(self, vec, k):
        import numpy as np
        scores = [0.95 - 0.01 * i for i in range(len(self._order))][:k]
        idxs = self._order[:k]
        return np.array([scores]), np.array([idxs])


class _FakeModel:
    def encode(self, xs, convert_to_numpy=True):
        import numpy as np
        return np.array([[1.0, 0.0, 0.0]], dtype="float32")


class _FakeBM25:
    def __init__(self, scores):
        self._scores = scores

    def get_scores(self, tokens):
        import numpy as np
        return np.array(self._scores, dtype="float32")


class _FakeFaiss:
    @staticmethod
    def normalize_L2(v):
        pass


def _install_fakes(r, *, dense_order, bm25_scores, chunks):
    r._cache["index"] = _FakeIndex(dense_order)
    r._cache["model"] = _FakeModel()
    r._cache["bm25"] = _FakeBM25(bm25_scores)
    r._cache["chunks"] = chunks
    r._cache["attempted"] = True
    # Skip cross-encoder load entirely — rerank=False in tests.
    r._cache["cross_encoder"] = None
    r._cache["cross_encoder_attempted"] = True
    sys.modules["faiss"] = _FakeFaiss  # type: ignore


def test_retrieve_returns_hits_when_index_available():
    """Happy path — hybrid retrieval returns results ordered by RRF."""
    r = _fresh()
    chunks = [
        {"source": "a.md", "text": "alpha content", "service": "s3",
         "compliance": [], "doc_type": "service_doc", "header_path": []},
        {"source": "b.md", "text": "beta content", "service": "lambda",
         "compliance": [], "doc_type": "service_doc", "header_path": []},
    ]
    _install_fakes(r, dense_order=[0, 1], bm25_scores=[0.8, 0.5], chunks=chunks)

    out = r.retrieve("query", k=2, rerank=False)
    assert len(out) == 2
    assert {h["source"] for h in out} == {"a.md", "b.md"}
    assert out[0]["rank"] == 0
    assert out[0]["score"] > 0


def test_metadata_filter_excludes_non_matching():
    """Filter on service=s3 — only s3-tagged chunks survive."""
    r = _fresh()
    chunks = [
        {"source": "a.md", "text": "alpha", "service": "s3",
         "compliance": [], "doc_type": "service_doc", "header_path": []},
        {"source": "b.md", "text": "beta",  "service": "lambda",
         "compliance": [], "doc_type": "service_doc", "header_path": []},
    ]
    _install_fakes(r, dense_order=[1, 0], bm25_scores=[0.1, 0.9], chunks=chunks)

    out = r.retrieve("anything", k=5, filters={"service": "s3"}, rerank=False)
    assert len(out) == 1
    assert out[0]["source"] == "a.md"


def test_compliance_filter_matches_list_values():
    """Compliance is stored as a list — filter should do set-membership."""
    r = _fresh()
    chunks = [
        {"source": "h.md", "text": "phi rules", "service": None,
         "compliance": ["HIPAA"], "doc_type": "compliance", "header_path": []},
        {"source": "s.md", "text": "generic",   "service": None,
         "compliance": [], "doc_type": "service_doc", "header_path": []},
    ]
    _install_fakes(r, dense_order=[0, 1], bm25_scores=[0.2, 0.4], chunks=chunks)

    out = r.retrieve("q", k=5, filters={"compliance": "HIPAA"}, rerank=False)
    assert [h["source"] for h in out] == ["h.md"]


def test_bm25_only_fallback_when_dense_unavailable():
    """Missing FAISS index must not block retrieval — BM25 still answers."""
    r = _fresh()
    chunks = [
        {"source": "a.md", "text": "alpha", "service": None,
         "compliance": [], "doc_type": "service_doc", "header_path": []},
        {"source": "b.md", "text": "beta", "service": None,
         "compliance": [], "doc_type": "service_doc", "header_path": []},
    ]
    _install_fakes(r, dense_order=[], bm25_scores=[0.9, 0.1], chunks=chunks)
    r._cache["index"] = None
    r._cache["model"] = None

    out = r.retrieve("alpha", k=2, rerank=False)
    assert out and out[0]["source"] == "a.md"
