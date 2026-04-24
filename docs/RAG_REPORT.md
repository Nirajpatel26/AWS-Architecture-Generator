# RAG design & evaluation

This document summarizes the retrieval-augmented generation (RAG) layer and
the numbers backing its design choices.

## Pipeline

```
user query
    │
    ├─► dense top-20  (MiniLM L6 v2 + FAISS IP)
    │
    ├─► BM25   top-20  (rank_bm25, Okapi BM25)
    │
    ▼
  RRF fuse  (k = 60)  ───►  top-20 candidate pool
                                │
                                ▼
                      cross-encoder rerank
                      (ms-marco-MiniLM-L-6-v2)
                                │
                                ▼
                            top-k final
```

All stages are optional: if a dependency is missing (FAISS,
`sentence_transformers`, `rank_bm25`, `CrossEncoder`), the retriever silently
falls back to the components that remain, or returns `[]`. This preserves the
project's fail-silent contract for external tools.

## Chunking

Previous: fixed 500-word windows. Lossy for AWS docs — headers were stripped,
and section boundaries were not respected.

New: **markdown-header-aware**. Each doc is split on `#`/`##`/`###` boundaries
so each chunk is a coherent section. Oversized sections (> 500 words) are
further split into overlapping windows (200-word overlap) so no single chunk
loses flanking context. HTML files go through the same path after tag
stripping.

Every chunk carries metadata:

| field        | description                                                |
|--------------|------------------------------------------------------------|
| `service`    | canonical AWS service name inferred from path (e.g. `s3`)  |
| `compliance` | list of `HIPAA` / `PCI` / `SOC2` tags inferred from text   |
| `doc_type`   | `service_doc`, `well_architected`, `compliance`, `html_doc`|
| `header_path`| breadcrumbs of active headers when the chunk was emitted   |
| `source`     | relative path to the source file                           |

Metadata is filterable at query time, e.g.
`retriever.retrieve(q, filters={"service": "s3", "compliance": "HIPAA"})`.
The validator uses service filters; the extractor filters to
`service_doc + compliance` only.

## Where RAG is consumed

| Stage | File | Usage |
|-------|------|-------|
| 1. Extract  | `pipeline/extractor.py` | Top-3 service-doc chunks injected into the system prompt so the extractor grounds workload/compliance inference. |
| 6. Validate | `pipeline/validator.py::_fix_with_llm` | On `terraform validate` failure, resource types are parsed from the error + HCL, mapped to services, and the service-filtered top-3 chunks are added to the repair prompt. |
| 9. Explain  | `pipeline/explainer.py` | Top-5 chunks become numbered citations in the rationale. |

Previously only stage 9 used RAG. Stages 1 and 6 now benefit from grounded
context.

## Index state

Rebuild with `python -m rag.ingest`. The builder writes:

- `rag/knowledge_base/.index/faiss.bin` — dense FAISS IP index
- `rag/knowledge_base/.index/chunks.pkl` — chunk list with metadata
- `rag/knowledge_base/.index/bm25_tokens.pkl` — tokenized corpus for BM25
- `rag/knowledge_base/.index/meta.json` — chunk count, services, doc types

The committed `meta.json` shows the latest chunk count.

## Evaluation

Labeled set: 20 queries in `eval/rag_queries.json`. Each query lists
substrings that must appear in the retrieved chunk's source path, or an
expected service/compliance/doc_type metadata tag. A result "matches" if
any of those hit.

Metrics:

- **Hit@5** — fraction of queries with at least one matching chunk in the top 5.
- **MRR@10** — mean reciprocal rank of the first matching chunk within the
  top 10. (Standard IR metric — stable under ties, interpretable at a glance.)

Run:

```bash
python -m rag.ingest        # build the index first
python -m eval.rag_eval     # writes eval/results/rag_report.{json,md}
```

The eval also runs an **ablation** across four configurations:

| Config              | Components                                         |
|---------------------|----------------------------------------------------|
| `dense_only`        | MiniLM + FAISS (the previous baseline).            |
| `bm25_only`         | BM25 only.                                         |
| `hybrid_rrf`        | Dense + BM25, RRF-fused.                           |
| `hybrid_rrf_rerank` | Hybrid + cross-encoder rerank (the production path). |

After a fresh `python -m rag.ingest` + `python -m eval.rag_eval`, the numbers
are written to `eval/results/rag_report.md`. Commit that file alongside any
changes that could affect retrieval (chunking, filters, KB content) so the
scoreboard in the report reflects the current state.
