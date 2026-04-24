"""Retrieval quality eval on a 20-query labeled set.

Metrics:
- Hit@5: fraction of queries where at least one of the top-5 results matches
  an expected source substring.
- MRR@10: mean reciprocal rank — 1/rank of the first matching result, 0 if
  none in the top 10. Standard IR metric; stable and interpretable.

Also reports an ablation: hybrid+rerank vs. dense-only (the old baseline).
Run:
    python -m eval.rag_eval
Writes eval/results/rag_report.json and rag_report.md.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List

from rag import retriever

ROOT = Path(__file__).resolve().parent
QUERIES_PATH = ROOT / "rag_queries.json"
OUT_DIR = ROOT / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TOP_K_DISPLAY = 5
MRR_DEPTH = 10


def _is_match(hit: dict, case: dict) -> bool:
    """A hit matches if any expected_sources substring appears in its path,
    OR if its tagged service/compliance/doc_type matches the expectation."""
    src = (hit.get("source") or "").lower()
    for patt in case.get("expected_sources", []):
        if patt.lower() in src:
            return True
    svc_expected = case.get("expected_service")
    if svc_expected and hit.get("service") == svc_expected:
        return True
    comp_expected = case.get("expected_compliance")
    if comp_expected:
        comps = [c.upper() for c in (hit.get("compliance") or [])]
        if comp_expected.upper() in comps:
            return True
    dt_expected = case.get("expected_doc_type")
    if dt_expected and hit.get("doc_type") == dt_expected:
        return True
    return False


def _run_config(queries: List[dict], *, rerank: bool, bm25_off: bool = False,
                 dense_off: bool = False) -> Dict[str, Any]:
    """Evaluate a retrieval configuration. Toggles are implemented by
    temporarily disabling components on the cached retriever."""
    # Warm the cache before touching internals.
    retriever._load()
    saved_bm25 = retriever._cache.get("bm25")
    saved_index = retriever._cache.get("index")
    saved_model = retriever._cache.get("model")

    try:
        if bm25_off:
            retriever._cache["bm25"] = None
        if dense_off:
            retriever._cache["index"] = None
            retriever._cache["model"] = None

        per_query = []
        hit_flags = []
        rrs = []
        for case in queries:
            hits = retriever.retrieve(case["query"], k=MRR_DEPTH, rerank=rerank)
            ranks_of_matches = [i + 1 for i, h in enumerate(hits) if _is_match(h, case)]
            first = ranks_of_matches[0] if ranks_of_matches else None
            hit_at_5 = bool(first and first <= TOP_K_DISPLAY)
            rr = (1.0 / first) if first else 0.0
            hit_flags.append(hit_at_5)
            rrs.append(rr)
            per_query.append({
                "id": case["id"],
                "query": case["query"],
                "hit@5": hit_at_5,
                "first_match_rank": first,
                "rr": rr,
                "top5": [
                    {"rank": h["rank"], "source": h["source"], "score": round(h["score"], 4)}
                    for h in hits[:TOP_K_DISPLAY]
                ],
            })

        return {
            "hit_at_5": mean([1.0 if f else 0.0 for f in hit_flags]) if hit_flags else 0.0,
            "mrr_at_10": mean(rrs) if rrs else 0.0,
            "n_queries": len(queries),
            "per_query": per_query,
        }
    finally:
        retriever._cache["bm25"] = saved_bm25
        retriever._cache["index"] = saved_index
        retriever._cache["model"] = saved_model


def main() -> None:
    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))

    # Configurations for the ablation.
    configs = [
        ("dense_only",         dict(rerank=False, bm25_off=True,  dense_off=False)),
        ("bm25_only",          dict(rerank=False, bm25_off=False, dense_off=True)),
        ("hybrid_rrf",         dict(rerank=False, bm25_off=False, dense_off=False)),
        ("hybrid_rrf_rerank",  dict(rerank=True,  bm25_off=False, dense_off=False)),
    ]

    results: Dict[str, Any] = {}
    for name, kwargs in configs:
        print(f"Running config: {name}")
        try:
            results[name] = _run_config(queries, **kwargs)
        except Exception as e:
            results[name] = {"error": str(e)}
            print(f"  error: {e}")

    out_json = OUT_DIR / "rag_report.json"
    out_json.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # Markdown summary — numbers for the write-up.
    lines = [
        "# RAG retrieval evaluation",
        "",
        f"Labeled queries: **{len(queries)}** (see `eval/rag_queries.json`).",
        "",
        "| config | hit@5 | MRR@10 |",
        "| --- | --- | --- |",
    ]
    for name, _ in configs:
        r = results.get(name) or {}
        if "error" in r:
            lines.append(f"| {name} | _error_ | _error_ |")
        else:
            lines.append(f"| {name} | {r['hit_at_5']:.3f} | {r['mrr_at_10']:.3f} |")
    lines += [
        "",
        "## Notes",
        "- `dense_only` — MiniLM embeddings + FAISS IP (the previous baseline).",
        "- `bm25_only` — rank_bm25 over the same chunks.",
        "- `hybrid_rrf` — RRF fusion of dense + BM25 top-20 candidates each.",
        "- `hybrid_rrf_rerank` — cross-encoder `ms-marco-MiniLM-L-6-v2` rerank "
        "over the fused pool.",
    ]
    (OUT_DIR / "rag_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\nWrote:")
    print(f"  {out_json}")
    print(f"  {OUT_DIR / 'rag_report.md'}")


if __name__ == "__main__":
    main()
