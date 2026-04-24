# Cloud Architecture Designer

Natural-language → **rendered architecture diagram + valid Terraform + cost estimate**. A Northeastern SEM4 Prompt course final project exercising three generative-AI components: **prompt engineering** (structured extraction + self-consistency voting + agentic validation loop), **RAG** (hybrid BM25 + dense + cross-encoder rerank over official AWS docs), and **multimodal** (diagram image output).

> See [TECHNICAL_SPEC.md](TECHNICAL_SPEC.md) for the full design document and [docs/RAG_REPORT.md](docs/RAG_REPORT.md) for the RAG evaluation report.

---

## What it does

```
"HIPAA telemedicine API, ~10k users/day, multi-AZ"
    │
    ├─► RAG retrieves service + compliance docs
    │
    ▼
┌──────────────────────────────────────────────────────┐
│  1. Requirements extraction (Gemini × 3 + voting,   │
│     few-shot examples + service-allowlist guardrail, │
│     SQLite-cached for repeat prompts)                │
│  2. Defaults + assumption surfacing                  │
│  3. Template selection + patch composition           │
│  4. Terraform emit (deterministic HCL emitter)       │
│  5. terraform validate + tfsec (RAG-augmented retry) │
│  6. Diagram render + cost estimate                   │
│  7. Cited rationale with CoT (<thinking> stripped,   │
│     <rationale> shown to user, trace kept for eval)  │
└──────────────────────────────────────────────────────┘
    │
    ▼
  Diagram (PNG) + main.tf + $/mo + explanation + .zip bundle
```

Four built-in templates: `web_api`, `data_pipeline`, `ml_training`, `static_site`.  
Three compliance/availability toggles: `HIPAA`, `HA`, `multi_region`.

**Live UI:** stage-by-stage streaming progress, a dedicated **Security tab**
listing every tfsec finding (rule, severity, resource, remediation), a
**Cost tab** with data-provenance caption, and a one-click **"Download
bundle (.zip)"** that packages `main.tf`, `variables.tf`, a project
`README.md`, the rendered diagram, and a per-resource `cost_breakdown.csv`.

---

## Setup

Requires Python 3.11+.

```bash
pip install -r requirements.txt
cp .env.example .env   # put your GEMINI_API_KEY in .env
```

> **Migrating from a pre-April-2026 checkout?** The Gemini client now uses `google-genai` (the old `google-generativeai` package was deprecated upstream). Run `pip uninstall -y google-generativeai && pip install -r requirements.txt` to switch.

Optional but recommended for full fidelity:
- **Terraform CLI** — `validator.py` uses `terraform validate`; skips gracefully if absent. Without it, `tf_valid` in the stability report is always 1.0 (skip counts as pass).
- **tfsec** — static security scan; skips gracefully if absent.
- **Graphviz** — `diagrams` lib needs it for PNG output; falls back to Mermaid text if absent. On Windows: `winget install Graphviz.Graphviz`.

> **`torchvision` note:** `requirements.txt` includes `torchvision>=0.17.0` (CPU build). This is an indirect dependency — the `transformers` package lazy-loads `ZoeDepthImageProcessor` when `sentence-transformers` initialises, and that module requires `torchvision`. The CPU build (`pip install torchvision --index-url https://download.pytorch.org/whl/cpu`) is sufficient; no GPU needed.

### Populate the knowledge base

Fetch official AWS documentation (clones `awsdocs/*` GitHub repos + AWS compliance / service product pages into `rag/knowledge_base/aws_docs/`, gitignored):

```bash
python -m rag.fetch_kb
```

Build the hybrid FAISS + BM25 index (rerun whenever you edit `rag/knowledge_base/`):

```bash
python -m rag.ingest
```

`meta.json` in `.index/` records chunk count, services tagged, and chunking parameters for reproducibility.

---

## Run

```bash
streamlit run app.py
```

Enter a prompt, pick a template (or leave on `auto`), toggle HIPAA / HA / multi-region, click **Generate**. Use the preset gallery to load example prompts.

---

## Evaluate

### Pipeline eval (component recall, TF validity, cost, latency, tokens)
```bash
python -m eval.run_eval
```
Produces `eval/results/summary.json`, `eval/results/per_case.json`, `eval/results/results.md`, and `eval/results/latency_histogram.json`.

The summary now reports:
- **Component recall / precision** and **TF validity rate** (base correctness).
- **Per-stage latency** — p50 / p95 / mean / max for each of the 9 pipeline
  stages, plus end-to-end `p50_wall_seconds` / `p95_wall_seconds`.
- **Token usage + $ cost per run** — `total_input_tokens`,
  `total_output_tokens`, `total_cost_usd`, `mean_cost_per_run_usd`
  (priced against the Gemini 2.0 Flash table in `pipeline/llm.py`).
- **LLM-as-judge** — when Gemini is available, each explanation is graded
  on `faithfulness` and `completeness` by a second Gemini call with a
  rubric prompt (`eval/judge.py`). Means appear as
  `mean_judge_faithfulness` / `mean_judge_completeness`.

### Ablation table (RAG on/off × repair loop on/off)
```bash
python -m eval.ablation
```
The headline eval artifact. Runs the reference suite under all four
combinations of `(rag, repair)` and reports pass_rate / tf_validity /
mean_recall / mean_latency / $ / tokens for each, plus uplift deltas.
Writes `eval/results/ablation.{json,md}`. This quantifies the contribution
of each design decision — RAG context injection and the LLM repair loop —
in one table.

### RAG eval (hit@5 and MRR@10 ablation)
```bash
python -m eval.rag_eval
```
Runs four configs (`dense_only`, `bm25_only`, `hybrid_rrf`, `hybrid_rrf_rerank`) over a 20-query labeled set and writes `eval/results/rag_report.{json,md}`. See [docs/RAG_REPORT.md](docs/RAG_REPORT.md) for methodology and numbers.

### Stability stress test
```bash
# Generate variants (4 modes × N per case) then evaluate
python -m eval.synthetic --n 5 --throttle 4.5

# With Gemini 429 protection + full tracebacks on crash
EXTRACTOR_VOTING_SAMPLES=1 python -m eval.synthetic --n 5 --throttle 4.5 --debug

# Run pipeline eval to get workload_stability_rate in summary.json
python -m eval.run_eval
```

Generates variants across four modes per reference case: **paraphrase**,
**adversarial**, **multilingual**, and **noisy**. When the synthetic file
is present, `run_eval` adds a `workload_stability_rate` metric. The
synthetic report also now reports a single-number **consistency score**
(0–1) combining workload stability, component-set Jaccard overlap, and
crash rate, for easy comparison across prompt-engineering changes.

**Reference results (160 variants, 8 base cases):**

| Mode | workload_flip ↓ | comp_jaccard ↑ | compliance_drift ↓ | crash ↓ |
|---|---|---|---|---|
| paraphrase | **0.00** | 0.962 | 0.10 | 0.10 |
| adversarial | **0.00** | 0.856 | 0.05 | 0.125 |
| multilingual | **0.00** | 0.962 | 0.10 | 0.10 |
| noisy | **0.00** | 0.971 | 0.075 | 0.075 |

Flags: `--throttle <sec>` sleeps between pipeline calls (use ~4.5 to stay under Gemini 15 RPM); `--debug` prints full tracebacks for any pipeline exception; `--n <int>` controls variants per mode (default 5).

---

## Project layout

```
pipeline/
  extractor.py          Stage 1 — RAG-grounded extraction with self-consistency voting
  defaults.py           Stage 2 — deterministic field fills
  assumptions.py        Stage 3 — surface + apply user overrides
  template_engine.py    Stage 4 — load template, apply patches (HIPAA→HA→multi_region)
  tf_generator.py       Stage 5 — deterministic JSON→HCL emitter
  validator.py          Stage 6 — terraform validate + tfsec with structured findings,
                                  RAG-augmented LLM repair
  diagram.py            Stage 7 — Mingrammer diagrams PNG
  cost.py               Stage 8 — static pricing lookup with data-provenance metadata
  explainer.py          Stage 9 — cited markdown rationale
  voting.py             Self-consistency merger (N=3 samples → per-field majority vote)
  cache.py              SQLite prompt → ArchSpec cache (versioned keys)
  export.py             One-call ZIP bundle builder (main.tf + README + CSV + diagram)
  run_log.py            Structured JSON event log (.cache/runs.jsonl)
  llm.py                Gemini client with per-call token-usage tracking + $ pricing
  prompts/              Versioned prompt files (*.v2.txt) + few-shot JSON + allowlist
  orchestrator.py       Streaming generator (run_streaming) + sync wrapper (run);
                        returns RunResult with timings, tokens, cost, tfsec findings
  schema.py             ArchSpec pydantic model shared across all stages

rag/
  ingest.py             Markdown-header-aware chunker + FAISS + BM25 index builder
  retriever.py          Hybrid dense+BM25 → RRF → cross-encoder rerank
  fetch_kb.py           Clones awsdocs/* repos + downloads compliance/service HTML pages
  knowledge_base/       Seed .md files + aws_docs/ (gitignored after fetch)

templates/              4 architecture skeletons (JSON)
patches/                3 patch transforms — hipaa.json, ha.json, multi_region.json
eval/
  reference_prompts.json  15 reference cases with expected components + cost ranges
  rag_queries.json        20-query labeled set for RAG eval
  run_eval.py             Pipeline eval harness (recall, TF validity, cost,
                          latency p50/p95, tokens, LLM-as-judge)
  rag_eval.py             RAG retrieval eval (hit@5, MRR@10, 4-config ablation)
  ablation.py             End-to-end ablation: RAG on/off × repair on/off × 15 cases
  judge.py                LLM-as-judge rubric for explanation faithfulness/completeness
  synthetic.py            Variant generator + stability scorer
docs/
  RAG_REPORT.md           RAG design, chunking strategy, eval numbers
  DEPLOYMENT.md           Auth / multi-tenancy / rate-limit / observability upgrade path
tests/                  pytest units covering every stage + cache + export + judge
                        (78 tests)
app.py                  Streamlit UI — streaming pipeline status, Security tab,
                        ZIP bundle download, cost-provenance caption
```

---

## Tests

```bash
pytest tests/            # 78 tests, all stages + cache + export + judge covered
```

---

## Key design decisions

| Decision | Rationale |
|---|---|
| **LLM never writes TF from scratch** | Templates are the resource skeleton; the HCL emitter is pure Python; LLM only *repairs* HCL when `terraform validate` fails. |
| **Self-consistency voting (N=3)** | Extraction is stochastic — compliance tags and workload type can swing across runs. Three samples merged by per-field majority vote stabilises results without fine-tuning. Override via `EXTRACTOR_VOTING_SAMPLES`. |
| **Deterministic service allowlist** | The extractor system prompt is injected at runtime with the exact list of `aws_*` resource types the downstream pipeline can emit, derived by scanning `templates/*.json` + `patches/*.json`. Prompts and templates stay in lockstep automatically. |
| **System/user prompt separation** | `llm.generate_json` accepts a `system=` parameter and passes it as `GenerateContentConfig(system_instruction=...)` — the proper Gemini SDK field. The extractor system prompt (`extractor.system.v2.txt`) is passed this way; the user turn (`extractor.user.v2.txt`) contains only few-shot examples + RAG context + the user's prompt, no embedded system text. |
| **Versioned prompts** | All LLM prompts live in `pipeline/prompts/*.vN.*` and are loaded through a cached loader; `RunResult.prompt_versions` records the exact versions used for every eval row so metrics are attributable. |
| **Structured CoT with hidden thinking** | The explainer prompt asks Gemini for `<thinking>` + `<rationale>` blocks. The UI renders only the rationale; the thinking trace is persisted to `eval/results/per_case.json` for inspection. |
| **Hybrid RAG (BM25 + dense + rerank)** | Dense alone misses exact-match service names ("ElastiCache Redis"). BM25 alone misses semantic intent. RRF fusion + cross-encoder rerank combines both signals. |
| **RAG in 3 stages, not 1** | Extractor gets grounded context before calling Gemini. Validator repair prompt gets the failing resource's docs. Explainer cites chunks. |
| **Prompt → ArchSpec caching** | Extraction is the heaviest stage (3× Gemini calls for voting). A SQLite cache keyed on `sha256(prompt + prompt_version + model)` returns identical prompts in milliseconds while still invalidating automatically on any prompt-version bump. |
| **Streaming pipeline with structured event log** | `orchestrator.run_streaming()` yields per-stage `started`/`done`/`result` events so the UI can render progress live. Every stage completion is also appended to `.cache/runs.jsonl` as structured JSON for observability pipelines. |
| **Downloadable bundle** | One call to `pipeline/export.build_zip()` produces `main.tf`, `variables.tf`, a project-specific `README.md`, the rendered diagram, and a per-resource `cost_breakdown.csv` — a handover-ready artifact. |
| **Priced LLM usage** | Every Gemini call records input/output tokens and converts to USD against a pinned Gemini 2.0 Flash price table, so eval reports a real $-per-run number instead of a vague "it's cheap". |
| **Ablation-first evaluation** | `eval/ablation.py` runs the reference suite in all four `(RAG on/off × repair on/off)` configurations in one command, producing a markdown table that directly quantifies each design decision's uplift. |

---

## Out of scope

- Real AWS deployment
- Multi-cloud (AWS only)
- Drift detection / state management
- Production-ready TF (output is a starting point)

## License
MIT
