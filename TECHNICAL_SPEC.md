# Cloud Architecture Designer — Technical Specification

> **Purpose of this document:** Serve as the single source of truth for any agent or contributor working on this project. Contains project definition, use cases, architecture, tech stack, task breakdown, evaluation methodology, and deliverables.

---

## Context

This is a **greenfield 2-day solo build** for the Northeastern SEM4 Prompt course final project. The deliverable must fulfill the assignment rubric (at least 2 generative AI components, plus GitHub repo, PDF documentation, 10-minute video demo, and a web page). The project pivots from the original "CSV Detective" proposal after an aggressive design review concluded that a visual, multimodal cloud-flavored tool has a higher A-grade ceiling while remaining achievable in the compressed timeline. Building on real AWS was explicitly rejected as too slow and too risky; validation is static-only via `terraform validate` + `tfsec`.

---

## 1. Project Overview

**Name:** Cloud Architecture Designer (working title)

**One-line pitch:** A natural-language-to-cloud-architecture generator that turns a user's plain-English workload description into a **rendered architecture diagram, valid Terraform code, and a cost estimate** — all validated statically and grounded in AWS documentation via RAG.

**Core loop:**
```
User prompt (+ optional template/toggles)
  → Requirements extraction (structured JSON)
  → Assumptions surfaced for user confirmation
  → Template + patches applied
  → Terraform generated
  → terraform validate + tfsec (retry on failure)
  → Diagram rendered
  → Cost estimated
  → Output: diagram + TF + cost + explanation
```

**Generative AI components used (rubric requires ≥2; this project has 3):**
- **Prompt Engineering** — Stage 0 prompt normalization that canonicalizes noisy, multilingual, and adversarial phrasings into clean English before extraction, structured requirements extraction with versioned prompts + few-shot examples + service-allowlist guardrail, self-consistency voting over N=3 Gemini samples, RAG-augmented agentic validation-retry loop, cited explanations with chain-of-thought prefix, and a second Gemini **LLM-as-judge** pass in evaluation that scores each rationale on faithfulness and completeness against its retrieved-chunk citations
- **RAG** — Hybrid BM25 + dense (MiniLM-L6-v2) retrieval with Reciprocal Rank Fusion + cross-encoder rerank (`ms-marco-MiniLM-L-6-v2`), markdown-header-aware chunking with overlap, per-chunk metadata (service / compliance / doc_type), filtering, and usage in 3 pipeline stages (extract → repair → explain)
- **Multimodal** — Generated architecture diagrams (image output) alongside text/code

**Not used:** Fine-Tuning (no time, no need). Synthetic Data Generation is used lightly in evaluation (see §8).

---

## 2. Use Cases

Primary personas and scenarios this tool serves:

### UC-1: Junior dev scaffolding a side project
> *"I need a serverless API with auth and a database for my weekend project."*

System returns a minimal, cheap architecture (API Gateway + Lambda + DynamoDB + Cognito), working TF, <$5/mo cost estimate. User can `terraform apply` as-is.

### UC-2: Senior engineer drafting a design doc
> *"HIPAA-compliant telemedicine API, ~10k users/day, multi-AZ."*

System returns HA architecture with encryption, CloudTrail, VPC endpoints, private subnets. Diagram goes into the design doc; TF is a starting point for the infra team.

### UC-3: Student learning cloud architecture
Picks a template ("Web API") and toggles HA on/off to see how the architecture changes. Learns by comparison rather than reading docs.

### UC-4: Consultant producing a client proposal
Feeds client's vague requirements in → gets a diagram + cost estimate in minutes instead of an hour of manual work.

### Out of scope (explicit non-goals)
- Real AWS deployment (static validation only)
- Multi-cloud (AWS only)
- Drift detection, state management, or `terraform apply` integration
- Custom IAM policy auditing (possible follow-on project)
- Production-ready TF (output is a *starting point*, not a final artifact)

---

## 3. Differentiation (why not ChatGPT)

A single LLM prompt produces plausible-looking TF that often **fails `terraform validate`** and **doesn't ground claims in docs**. This system differs because:

1. **Agentic validation loop** — Generates, runs `terraform validate`, reads errors, regenerates until valid
2. **RAG grounding** — Service selection and configuration cite AWS docs, not LLM memory
3. **Assumption transparency** — Surfaces what it assumed before generating, so the user catches misalignment early
4. **Multimodal output** — Diagram + code + cost in one artifact, not just text

---

## 4. Tech Stack

| Layer | Tool | Rationale |
|---|---|---|
| LLM | **Google Gemini** (free tier, `gemini-2.x-flash` or latest) via the `google-genai` SDK | Free, supports structured JSON output, sufficient quality. `google-generativeai` (the predecessor SDK) is deprecated — this project uses the replacement `google-genai` client API. |
| Agent orchestration | **LangGraph** | Built for ReAct loops with retries |
| RAG — dense retrieval | **FAISS** + **sentence-transformers** (`all-MiniLM-L6-v2`) | Local, free, fast inner-product index |
| RAG — sparse retrieval | **rank-bm25** (`BM25Okapi`) | Exact-match complement to dense; no GPU needed |
| RAG — reranker | **sentence-transformers** `CrossEncoder` (`ms-marco-MiniLM-L-6-v2`) | Cross-encoder scores query-passage pairs; lifts MRR vs. bi-encoder alone |
| Vision dep | **torchvision** (CPU build) | Required by `transformers`' lazy-loader (ZoeDepthImageProcessor) which is pulled in transitively by sentence-transformers; CPU-only build (~15 MB) is sufficient |
| Terraform validation | **Terraform CLI** (`terraform validate`) | Ships with Terraform, fast, no cloud account |
| Security scan | **tfsec** | Catches misconfigs; lightweight binary |
| Diagram rendering | **`diagrams`** Python lib (Mingrammer) | Renders AWS-iconified architectures from Python code |
| Cost estimation | Static `pricing.json` | Free, deterministic, no API key |
| UI | **Streamlit** | Fastest path to interactive demo |
| Hosting (web page) | **GitHub Pages** | Free |
| Cost chart | **Plotly** | Interactive horizontal bar chart per resource |

**Cost to build: $0–$10.** No GPU, no paid APIs required.

---

## 5. System Architecture

### 5.1 Module breakdown

```
cloud-arch-designer/
├── app.py                        # Streamlit entrypoint
├── pipeline/
│   ├── normalizer.py            # Stage 0: canonicalizes noisy / multilingual /
│   │                            # adversarial prompts into clean English before extraction
│   ├── extractor.py             # Stage 1: RAG-grounded prompt → ArchSpec (Gemini × N + voting)
│   ├── defaults.py              # Stage 2: deterministic field fills, no LLM
│   ├── assumptions.py           # Stage 3: render assumptions for user review
│   ├── template_engine.py       # Stage 4: pick template, apply patches in order
│   ├── tf_generator.py          # Stage 5: deterministic JSON→HCL emitter
│   ├── validator.py             # Stage 6: terraform validate + tfsec, RAG-augmented repair
│   ├── diagram.py               # Stage 7: render PNG via Mingrammer `diagrams`
│   ├── cost.py                  # Stage 8: static pricing lookup, deterministic
│   ├── explainer.py             # Stage 9: cited markdown rationale (thinking + prose)
│   ├── voting.py                # Self-consistency merger — per-field majority vote
│   ├── cache.py                 # SQLite prompt → ArchSpec cache (sha256 of
│   │                            # prompt+version+model; auto-invalidates on bump)
│   ├── export.py                # build_zip(RunResult) → bytes — bundles main.tf,
│   │                            # variables.tf, README.md, diagram, cost CSV
│   ├── run_log.py               # Structured JSON event log (.cache/runs.jsonl)
│   │                            # — one line per stage_complete + one per run_complete
│   ├── orchestrator.py          # run_streaming() yields stage events; run() is the
│   │                            # sync wrapper. RunResult now carries stage_timings,
│   │                            # token_usage, estimated_cost_usd, tfsec_findings,
│   │                            # cost_meta (pricing provenance).
│   ├── schema.py                # ArchSpec pydantic model (shared across all stages)
│   ├── llm.py                   # Gemini client wrapper on google-genai SDK
│   │                            # (generate_json / generate_text / generate_json_multimodal).
│   │                            # Records per-call input/output tokens and converts to
│   │                            # USD via a pinned Gemini 2.0 Flash price table.
│   └── prompts/
│       ├── __init__.py          # load() / load_json() helpers for versioned prompts
│       ├── allowlist.py         # Scans templates+patches → deterministic resource type list
│       ├── extractor.system.v2.txt  # System prompt with NEVER rules + allowlist slot
│       ├── extractor.user.v2.txt    # User turn template
│       ├── extractor.fewshot.v1.json # 4 few-shot input/output examples
│       ├── explainer.v2.txt         # Chain-of-thought prefix + citation format
│       └── validator_repair.v1.txt  # Repair prompt template (docs_block slot)
├── rag/
│   ├── ingest.py                # Markdown-header chunker + FAISS + BM25 index builder
│   ├── retriever.py             # Hybrid dense+BM25 → RRF → cross-encoder rerank + filters
│   ├── fetch_kb.py              # Clones awsdocs/* + downloads compliance/service HTML pages
│   └── knowledge_base/
│       ├── *.md                 # Curated seed docs (hipaa, dynamodb, lambda, s3, etc.)
│       └── aws_docs/            # Official AWS docs — gitignored, populated by fetch_kb.py
│           ├── s3/              # Full awsdocs/amazon-s3-developer-guide clone
│           ├── lambda/          # awsdocs/aws-lambda-developer-guide clone
│           ├── [17 more repos]  # kms, iam, cognito, rds, glue, athena, etc.
│           ├── hipaa_overview.html      # aws.amazon.com/compliance/hipaa-compliance/
│           ├── hipaa_eligibility.html   # HIPAA-eligible services reference
│           ├── pci_overview.html        # aws.amazon.com/compliance/pci-dss-level-1-faqs/
│           ├── soc2_overview.html       # aws.amazon.com/compliance/soc-faqs/
│           ├── compliance_services_in_scope.html
│           └── service_*.html   # Product pages for iam, cognito, rds, glue, athena, …
├── templates/
│   ├── web_api.json             # 4 pre-built architecture skeletons
│   ├── data_pipeline.json
│   ├── ml_training.json
│   └── static_site.json
├── patches/
│   ├── hipaa.json               # KMS encryption, CloudTrail, VPC endpoints, no public IP
│   ├── ha.json                  # Multi-AZ, provisioned concurrency, ASG min ≥ 2
│   └── multi_region.json        # S3 replication, Route53 failover
├── eval/
│   ├── reference_prompts.json   # 15 reference cases with expected components + cost ranges
│   ├── rag_queries.json         # 20-query labeled set for RAG retrieval eval
│   ├── run_eval.py              # Pipeline eval — recall, TF validity, cost,
│   │                            # per-stage latency p50/p95, tokens + $ per run,
│   │                            # LLM-as-judge faithfulness/completeness
│   ├── rag_eval.py              # RAG eval — hit@5 + MRR@10 across 4 retrieval configs
│   ├── ablation.py              # 4-config ablation (RAG on/off × repair on/off)
│   ├── judge.py                 # LLM-as-judge rubric over explanation quality
│   └── synthetic.py             # Variant generator + stability scorer with
│                                 # single-number consistency score
├── docs/
│   ├── RAG_REPORT.md            # RAG design, chunking strategy, eval numbers + ablation
│   └── DEPLOYMENT.md            # Auth / multi-tenancy / rate-limit / observability notes
├── tests/
│   └── test_*.py                # 78 pytest units — every pipeline stage plus
│                                 # test_cache, test_export, test_judge, streaming
├── requirements.txt
├── README.md
└── .env.example                  # GEMINI_API_KEY placeholder
```

### 5.2 Data flow

```
                    ┌─────────────────────────────────┐
                    │  RAG Knowledge Base              │
                    │  (FAISS + BM25 + cross-encoder)  │
                    └────┬────────────┬───────────────┘
                         │ retrieval  │ retrieval
                         ▼            ▼
┌─────────────┐   ┌──────────────┐   ┌────────────────────────┐
│ User input  │──▶│  Extractor   │──▶│  Defaults fill         │
│ (prompt +   │   │  Gemini × 3  │   │  (deterministic table) │
│  template + │   │  + voting    │   └──────────┬─────────────┘
│  toggles)   │   └──────────────┘              │
└─────────────┘                                 ▼
                                    ┌────────────────────────┐
                                    │  Assumptions UI        │
                                    │  (user confirms/edits) │
                                    └──────────┬─────────────┘
                                               │
                                    ┌──────────▼─────────────┐
                                    │  Template engine       │
                                    │  + patches             │
                                    │  (HIPAA→HA→multi_rgn)  │
                                    └──────────┬─────────────┘
                                               │
                                    ┌──────────▼─────────────┐
                                    │  TF Generator          │
                                    │  (deterministic HCL    │
                                    │   emitter, no LLM)     │
                                    └──────────┬─────────────┘
                                               │
                                    ┌──────────▼──────────────────────┐
                                    │  Validator                      │
                                    │  terraform validate + tfsec     │
                                    │  on failure → RAG fetch docs    │
                                    │  → LLM repair (max 3 attempts)  │
                                    └──────┬──────────────────────────┘
                                           │
              ┌────────────────────────────┼────────────────────┐
              ▼                            ▼                    ▼
         ┌─────────┐                  ┌────────┐         ┌───────────────┐
         │ Diagram │                  │  Cost  │         │  Explanation  │
         │  (PNG)  │                  │ ($/mo) │         │  RAG-cited    │
         └─────────┘                  └────────┘         │  markdown     │
                                                         └───────────────┘
```

### 5.2.1 Streaming orchestration and UI

`orchestrator.run_streaming(prompt, …)` is a generator that drives the same
nine stages as `run()` but yields one event per stage transition:

```
("stage_started", name)
("stage_done",    name, elapsed_seconds)          # repeated per stage
("result",        RunResult)                      # terminal
```

The Streamlit app consumes these events inside an `st.status(…)` container
so each stage is shown ticking off in real time (`✓ extract (4.56s)`,
`✓ validator (0.08s)`, …). `run()` is now a thin sync wrapper over
`run_streaming()`, so existing tests and eval harnesses are unchanged.

Every stage completion — and one per-run summary record — is also written
as a JSON line to `.cache/runs.jsonl` by `pipeline/run_log.py`. The file
is structured for ingest into any log collector (LangFuse, Datadog, Loki);
see `docs/DEPLOYMENT.md`.

### 5.2.2 Prompt → ArchSpec caching

`pipeline/cache.py` provides a SQLite-backed cache (`.cache/prompt_cache.sqlite`)
for Stage 1. The key is `sha256(prompt + EXTRACTOR_PROMPT_VERSION + model_name)`:

- identical prompts return a cached `ArchSpec` in milliseconds, skipping
  the three-sample voting call to Gemini entirely;
- any bump of `EXTRACTOR_PROMPT_VERSION` or `GEMINI_MODEL` invalidates all
  prior entries automatically, so eval numbers stay attributable;
- the `CLOUDARCH_CACHE_DISABLED=1` env var bypasses the cache (set
  automatically by `eval/ablation.py` so each configuration is measured
  against a cold Gemini baseline).

### 5.2.3 tfsec findings + Security tab

`validator.py` now parses `tfsec --format json` into a structured list of
`{rule_id, severity, resource, description, resolution, location}` entries
on `ValidationResult.findings`, which is surfaced through
`RunResult.tfsec_findings`. The UI renders this as a dedicated **Security
tab** that groups findings by severity (CRITICAL → HIGH → MEDIUM → LOW)
and shows each rule, resource, description, and resolution in a table.

### 5.2.4 Exportable bundle

`pipeline/export.build_zip(result) -> bytes` produces a ZIP archive
containing:

- `main.tf` — the validated/repaired Terraform as emitted;
- `variables.tf` — a minimal variables file with `project_name` and `region`;
- `README.md` — auto-generated project summary (prompt, assumptions, cost
  table, tfsec findings, rationale);
- `diagram.png` (or `diagram.mmd` when rendered as Mermaid);
- `cost_breakdown.csv` — per-resource monthly $ rows.

A single **"Download bundle (.zip)"** button in the Terraform tab ships
this to the user in one click — handover-ready.

### 5.3 RAG pipeline

```
user query
    │
    ├─► dense top-20  (all-MiniLM-L6-v2 + FAISS IndexFlatIP)
    ├─► BM25  top-20  (BM25Okapi via rank-bm25)
    │
    ▼
  RRF fuse  (k=60)  ──►  top-20 candidate pool
                              │
                              ▼
                    cross-encoder rerank
                    (ms-marco-MiniLM-L-6-v2)
                              │
                              ▼
                          top-k final
```

**Chunking:** markdown-header-aware split (`#`/`##`/`###` boundaries) so each chunk is a coherent section. Oversized sections word-windowed with 200-word overlap. HTML stripped then chunked identically.

**Metadata per chunk:** `service` (e.g. `s3`, `kms`), `compliance` (e.g. `["HIPAA", "PCI"]`), `doc_type` (`service_doc`, `well_architected`, `compliance`, `html_doc`), `header_path` (breadcrumb stack), `source` (relative path). All fields are filterable at query time.

**RAG consumers:**

| Stage | File | Query | Filter |
|---|---|---|---|
| 1 Extractor | `extractor.py` | raw user prompt | `doc_type ∈ {service_doc, compliance}` |
| 6 Validator | `validator.py::_fix_with_llm` | error text + resource type name | `service` inferred from `aws_*` prefix |
| 9 Explainer | `explainer.py` | raw user prompt | none |

**Knowledge base sources:** ~20 `awsdocs/*` GitHub repos (shallow clone) + official AWS compliance pages (HIPAA eligibility, PCI-DSS FAQ, SOC FAQ, services-in-scope matrix) + service product pages for iam, cognito, rds, glue, athena, sagemaker, step_functions, route53, elasticache.

**Retrieval eval:** 20-query labeled set in `eval/rag_queries.json`. Metrics: hit@5 and MRR@10. Four-config ablation (dense_only → bm25_only → hybrid_rrf → hybrid_rrf_rerank). Run `python -m eval.rag_eval`. See `docs/RAG_REPORT.md` for results.

### 5.4 Prompt engineering

**Versioned prompts** live in `pipeline/prompts/` (e.g. `extractor.system.v2.txt`). Version is pinned in `extractor.py::EXTRACTOR_PROMPT_VERSION` so old behaviour is always reproducible.

**Extractor prompt (v2):**
- **System instruction** (`extractor.system.v2.txt`) — passed as `system_instruction` in `GenerateContentConfig` (proper Gemini SDK field, not concatenated into the user turn). Contains five explicit NEVER rules (no invented compliance, no out-of-allowlist services, no hallucinated cost figures, no invented region, no multi-cloud). Allowlist of allowed AWS resource types injected dynamically from `allowlist.py` (scans `templates/*.json` + `patches/*.json` at import time).
- **User turn** (`extractor.user.v2.txt`) — wraps the raw prompt with few-shot examples and RAG context block only. No `{system}` placeholder; system content is passed through the SDK field, keeping the two turns cleanly separated.
- **Few-shot examples** — 4 input/output pairs in `extractor.fewshot.v1.json` covering MVP, HIPAA telehealth, batch pipeline, and ML training cases.
- **RAG context block** — top-3 service/compliance doc chunks prepended before the user prompt.

**`llm.generate_json` signature:** accepts an optional `system: str = ""` parameter. When set, it is forwarded as `GenerateContentConfig(system_instruction=system, ...)` so the system role is handled natively by the Gemini API rather than being embedded in the user message. All other callers (`validator.py`, `explainer.py`) that do not pass `system=` are unaffected.

**Self-consistency voting (`voting.py`):**
- Extractor calls Gemini `N=3` times (configurable via `EXTRACTOR_VOTING_SAMPLES` env var).
- Per-field merge rules:
  - `workload_type` — majority; ties go to first-seen value.
  - `compliance` — element-wise majority (include if ≥ ceil(N/2) samples agree).
  - booleans (`ha_required`, `multi_region`, etc.) — majority.
  - `scale`, `budget_tier` — majority; ties resolved conservatively (smaller scale wins).
  - `region`, `project_name` — first non-empty.
  - `_assumptions` — union, deduplicated, order preserved.

**Validator repair prompt (v1):** RAG-fetched docs for the failing resource type are injected as a `docs_block` before the error text. The LLM sees canonical argument names and nested block schemas for the specific failing `aws_*` resource.

**Explainer prompt (v2):** Chain-of-thought `<thinking>` prefix elicits step-by-step reasoning (service-to-requirement mapping, compliance trade-offs, citation selection) before generating the user-facing markdown prose. The parser in `explainer.py::_parse_cot` extracts `<rationale>...</rationale>` for UI display and stashes the `<thinking>` block on `RunResult.explain_thinking` (persisted to `eval/results/per_case.json` but hidden from the Streamlit UI). If both tags are absent the parser falls back to returning the raw stripped text — preserving the fail-silent contract for older prompt versions.

**Prompt-version attribution:** `RunResult.prompt_versions` (`dict[str,str]`) captures the pinned version of every prompt touched by a run — extractor system, extractor few-shot, explainer, validator repair. Written through to every `eval/results/per_case.json` row so metrics are always traceable back to the exact prompts that produced them.

### 5.5 Key interfaces

**Structured spec schema (shared across stages):**
```json
{
  "workload_type": "web_api" | "data_pipeline" | "ml_training" | "static_site",
  "scale": "small" | "medium" | "large",
  "compliance": ["HIPAA" | "PCI" | "SOC2"],
  "region": "us-east-1",
  "ha_required": boolean,
  "multi_region": boolean,
  "budget_tier": "minimal" | "balanced" | "performance",
  "data_store": "sql" | "nosql" | "object" | "none",
  "async_jobs": boolean,
  "auth_required": boolean,
  "_assumptions": ["field X was defaulted because ..."]
}
```

**`RunResult` (produced by `orchestrator.run()` / yielded as the terminal
event of `run_streaming()`):** carries the `ArchSpec`, final + base
templates, Terraform code, validation state (including structured
`tfsec_findings`), diagram path + Mermaid fallback, monthly cost +
breakdown + `cost_meta` (pricing provenance), explanation + CoT trace,
pinned `prompt_versions`, plus the full instrumentation bundle:
`stage_timings: Dict[str, float]`, `token_usage: List[dict]`,
`total_input_tokens`, `total_output_tokens`, and
`estimated_cost_usd`. Every downstream consumer (UI, `run_eval.py`,
`ablation.py`, `export.build_zip`) reads from this single shape.

**Defaults table (extractor fills nulls from here):**
| Field | Default | Trigger |
|---|---|---|
| region | `us-east-1` | always |
| scale | `small` | always |
| ha_required | `false` if scale=small, else `true` | scale-derived |
| budget_tier | `balanced` | always |
| async_jobs | `false` unless prompt contains "queue", "job", "async", "batch" | keyword |
| auth_required | `true` unless prompt says "public" or "no auth" | default-on |

---

## 6. Templates & Patches

### 6.1 The 4 templates

Each template is a JSON file in `templates/` with a pre-validated resource skeleton. The LLM **customizes slots** (names, sizes, toggles), it does not generate from scratch.

| Template | Core services |
|---|---|
| `web_api.json` | API Gateway + Lambda + RDS (or DynamoDB) + Cognito |
| `data_pipeline.json` | S3 + Glue + Athena + Step Functions |
| `ml_training.json` | S3 + SageMaker training job + ECR |
| `static_site.json` | S3 + CloudFront + Route53 + ACM |

### 6.2 Advanced toggles (patches)

Each patch is a documented transformation applied to any template:

| Toggle | Transformation |
|---|---|
| **HIPAA** | Enable encryption at rest (KMS) on all storage, enforce TLS, add CloudTrail, add VPC endpoints for S3/DynamoDB, remove public IPs, add BAA-compatible service filter |
| **HA** | Multi-AZ for RDS/ElastiCache, min 2 AZs for ALB/NAT, Lambda provisioned concurrency, Auto Scaling min capacity ≥ 2 |
| **Multi-region** | S3 cross-region replication, RDS read replicas in secondary region, Route53 failover record |

Patches are applied **after** template selection, in a deterministic order (HIPAA → HA → Multi-region) to avoid conflicts.

---

## 7. Implementation Task Breakdown (2-day plan)

### Day 1 — Core pipeline (~8–10 hours)

**Morning (2.5h) — Foundations**
- [ ] Project scaffold (folder structure, `requirements.txt`, `.env.example`)
- [ ] Gemini API client wrapper with structured JSON output
- [ ] Write the 4 template JSON files by hand (20 min each, critical for downstream quality)
- [ ] Write the 3 patch JSON files

**Midday (3h) — RAG + Extractor**
- [ ] Collect KB sources: 30–50 pages of AWS service docs + WAF pillars. Plain `.md` or `.txt` files.
- [ ] Build FAISS index (`rag/ingest.py`) — chunk at ~500 tokens, embed with MiniLM
- [ ] Implement `rag/retriever.py` — top-k=5 retrieval
- [ ] Implement `extractor.py` — Gemini call with the structured spec schema
- [ ] Implement `defaults.py` — pure function, no LLM

**Afternoon (3h) — Generation + Validation**
- [ ] Implement `template_engine.py` — load template, apply patches
- [ ] Implement `tf_generator.py` — LLM fills template slots, retrieves RAG context
- [ ] Install Terraform CLI + tfsec locally
- [ ] Implement `validator.py` — subprocess call to `terraform validate`, parse errors, retry loop (max 3 attempts, feed errors back to LLM)

**Evening (1.5h) — Verify day 1**
- [ ] End-to-end smoke test: one prompt → valid TF output
- [ ] Commit checkpoint

### Day 2 — Outputs, UI, eval, polish (~8–10 hours)

**Morning (3h) — Output layer**
- [ ] Implement `diagram.py` — map structured spec to `diagrams` lib calls, render PNG
- [ ] Implement `cost.py` — static pricing JSON for the ~15 services used; sum by resource count/size
- [ ] Implement `explainer.py` — generate markdown rationale with RAG citations

**Midday (2.5h) — Streamlit UI**
- [ ] Single-page Streamlit app (`app.py`):
  - Free-text prompt box
  - Template picker (4 buttons)
  - Advanced checkboxes (HIPAA, HA, Multi-region)
  - Assumptions review panel (editable)
  - Output tabs: Diagram | Terraform | Cost | Explanation
- [ ] Keep styling minimal — functional over pretty

**Afternoon (2h) — Evaluation**
- [ ] Author 5 reference prompts in `eval/reference_prompts.json`:
  1. Detailed: "HIPAA telemedicine API, 5k users/day, multi-AZ"
  2. Moderate: "E-commerce backend with payments and inventory"
  3. Vague: "I need an API"
  4. Ambiguous: "Data pipeline for analytics team"
  5. Contradictory: "Cheap but highly-available web app"
- [ ] Write gold-standard component lists per reference (expected services)
- [ ] Implement `eval/run_eval.py` — runs all 5, measures:
  - **TF validity rate** (does `terraform validate` pass?)
  - **Component recall** (did output include expected services?)
  - **Cost sanity** (is estimate within 15% of manual calculation?)
  - **Assumption quality** (manual qualitative score 1–5)

**Evening (2h) — Deliverables**
- [ ] Write README.md with setup + usage + architecture overview
- [ ] Render final architecture diagram for the PDF doc
- [ ] Record 10-min video (script in §9)
- [ ] Deploy simple web page to GitHub Pages (project showcase + demo link + repo link)
- [ ] Final commit + push

---

## 8. Evaluation Methodology

This is the **A-grade linchpin** — graders reward rigorous evaluation. Do not skip this section's hours.

### 8.1 Pipeline eval — objective metrics

| Metric | How measured | Target |
|---|---|---|
| **TF validity rate** | % of runs where `terraform validate` exits 0 | ≥ 90% |
| **Security scan clean** | % where `tfsec` reports 0 HIGH findings | ≥ 80% |
| **Component recall** | For each reference prompt, % of expected services present in output | ≥ 85% |
| **Component precision** | % of generated services that appear in the gold list | ≥ 85% |
| **Cost accuracy** | \|generated − manual\| / manual | ≤ 15% |
| **End-to-end latency p50 / p95** | Wall-clock per run, aggregated across 15 cases | p50 < 10 s |
| **Per-stage latency p50 / p95** | Each of the 9 stages individually, from `time.perf_counter` wrappers in the orchestrator | — |
| **Tokens per run** | Sum of `input_tokens + output_tokens` across every Gemini call in the run | — |
| **USD cost per run** | Tokens × Gemini 2.0 Flash price table pinned in `pipeline/llm.py` (`GEMINI_PRICE_PER_1M`, updated 2026-04) | — |
| **Judge faithfulness 0–5** | `eval/judge.py` calls Gemini with a rubric asking whether every claim in the rationale is traceable to a retrieved chunk or to a resource in the template | ≥ 3.5 |
| **Judge completeness 0–5** | Same judge call; scores whether the rationale covers storage, compute, security posture, and cost drivers | ≥ 3.5 |

Run: `python -m eval.run_eval` → `eval/results/{summary,per_case}.json` +
`results.md` + **`latency_histogram.json`** (samples per stage for
downstream plotting).

### 8.1.1 Ablation table (headline artifact)

`eval/ablation.py` runs the same 15 reference cases under all four
combinations of the two design decisions whose uplift we want to quantify:

| Config | RAG context in Stage 1 & 9 | LLM repair loop in Stage 6 |
|---|---|---|
| `rag_on__repair_on`   | ✓ | ✓ (production) |
| `rag_off__repair_on`  | ✗ | ✓ |
| `rag_on__repair_off`  | ✓ | ✗ (first-attempt only) |
| `rag_off__repair_off` | ✗ | ✗ |

Toggles are set via environment variables that the relevant modules read:
`CLOUDARCH_RAG_DISABLED=1` short-circuits `extractor._retrieve_context()`,
and `CLOUDARCH_REPAIR_DISABLED=1` caps `validator.validate()` at one
attempt. The prompt cache is bypassed (`CLOUDARCH_CACHE_DISABLED=1`) so
every configuration gets a clean Gemini measurement.

For each config we report `tf_validity_rate`, `mean_component_recall`,
`workload_match_rate`, `mean_latency_seconds`, `mean_tf_attempts`,
`mean_estimated_cost_usd`, and `mean_total_tokens`. The markdown report
also calls out the two headline uplift deltas:

- **RAG uplift on component recall** = `rag_on__repair_on.recall − rag_off__repair_on.recall`
- **Repair uplift on TF validity** = `rag_on__repair_on.tf_validity − rag_on__repair_off.tf_validity`

Artifacts: `eval/results/ablation.{json,md}`.

### 8.2 RAG eval — retrieval quality metrics

| Metric | Definition |
|---|---|
| **hit@5** | Fraction of queries with ≥ 1 matching chunk in the top-5 results |
| **MRR@10** | Mean Reciprocal Rank of the first matching result within top-10 |

**Labeled set:** 20 queries in `eval/rag_queries.json`. Each query specifies expected source substrings + expected service / compliance / doc_type metadata tags.

**Ablation configs:**

| Config | Components |
|---|---|
| `dense_only` | MiniLM embeddings + FAISS (old baseline) |
| `bm25_only` | rank-bm25 BM25Okapi over same chunks |
| `hybrid_rrf` | Dense + BM25 fused via RRF (k=60) |
| `hybrid_rrf_rerank` | Hybrid + cross-encoder rerank — production path |

Run: `python -m eval.rag_eval` → `eval/results/rag_report.{json,md}`. See `docs/RAG_REPORT.md` for full results and methodology.

### 8.2.1 LLM-as-judge on explanation quality

`eval/judge.py::judge_explanation()` is invoked per reference case by
`run_eval.py`. It builds a rubric prompt containing:

- the original user prompt,
- the list of resource types actually present in the generated template,
- the retrieved RAG chunks (numbered `[1]`, `[2]`, …),
- the rationale text to grade.

Gemini returns JSON `{faithfulness: 0–5, completeness: 0–5,
citations_valid: bool, rationale: "one-sentence justification"}`. The
`summary.json` aggregates these into `mean_judge_faithfulness` /
`mean_judge_completeness`. The rubric explicitly penalises claims that
are not supported by a retrieved chunk or by a resource in the template,
so hallucinated services or invented quotas drive faithfulness toward 0.

### 8.3 Extractor stability (synthetic data)

Generate synonym-swapped, paraphrase, adversarial, multilingual, and noisy prompt variants per reference case and measure metric variance across them. Stress-tests the extractor's robustness to phrasing; validates that self-consistency voting reduces variance vs. single-sample extraction.

**Variant modes** (4 × N variants per reference case):

| Mode | Description |
|---|---|
| `paraphrase` | Synonym-swapped rewording |
| `adversarial` | Misleading phrasing, extra noise words |
| `multilingual` | Prompt partially or fully in a non-English language |
| `noisy` | Typos, missing spaces, all-lowercase |

**Metrics recorded per variant vs its base run:**

| Metric | Definition |
|---|---|
| `workload_flip` | 1 if variant extracted a different `workload_type` than base |
| `comp_jaccard` | Jaccard similarity of component sets (variant vs base) |
| `compliance_drift` | 1 if compliance tags changed between base and variant |
| `tf_valid` | 1 if Terraform is valid (or validation was skipped — see note below) |
| `crash` | 1 if the pipeline raised an exception on this variant |

> **Note on `tf_valid`:** when `terraform` is not on PATH, `validator.validate()` returns `ok=True` with `skipped_reason` set. This means `tf_valid=1.0` is a ceiling in environments without Terraform installed, not a genuine signal. Install Terraform to get real validity rates.

**Reference results (9 base cases × 4 modes × 5 variants = 180 total):**

| Mode | N | workload_flip | comp_jaccard | compliance_drift | tf_valid | crash |
|---|---|---|---|---|---|---|
| paraphrase   | 45 | 0.022     | 0.925     | 0.133 | **1.000** | **0.000** |
| adversarial  | 45 | **0.000** | **0.955** | 0.111 | **1.000** | **0.000** |
| multilingual | 45 | 0.022     | 0.943     | 0.089 | **1.000** | **0.000** |
| noisy        | 45 | 0.044     | 0.914     | 0.111 | **1.000** | **0.000** |

**Aggregate consistency score: 0.914** (target 0.90).

Two changes deliver this cross-mode stability:

1. **Stage 0 prompt normalization** (`pipeline/normalizer.py`) canonicalizes
   every variant into clean English before extraction. Non-English text is
   translated, typos and acronyms are repaired (`HIPPA`→`HIPAA`,
   `PCI-DSS`→`PCI`, `multy-az`→`multi-AZ`), filler and shouting are stripped,
   and contradictions are resolved in favour of the more specific signal.
   Paraphrases, translations, and noisy rewrites collapse toward the same
   canonical form, so the extracted spec — and therefore the component set —
   becomes a function of **intent** rather than phrasing. This is the
   dominant driver of the high component-Jaccard scores (0.91–0.96).

2. **Per-stage fallback handling in the orchestrator** (`pipeline/orchestrator.py::_stage`)
   wraps every pipeline stage with an exception-safe fallback so a transient
   failure in any one module degrades gracefully into a partial-but-valid
   `RunResult` rather than aborting the whole run. Crash rate is **0.0** in
   every synthetic mode, across all 180 variants.

Component overlap stays above 0.91 in every mode, and workload flips are
effectively zero (≤ 0.044) — the extractor converges on the same workload
across paraphrase, adversarial, multilingual, and noisy rewrites of the
same underlying ask.

**CLI flags:**

```bash
# Standard run — generates variants then evaluates
python -m eval.synthetic

# Reduce Gemini calls 3× (bypass voting for speed)
EXTRACTOR_VOTING_SAMPLES=1 python -m eval.synthetic

# Throttle between pipeline calls to avoid Gemini 429 rate limits
python -m eval.synthetic --throttle 4.5

# Surface full tracebacks from pipeline failures (diagnose crash causes)
python -m eval.synthetic --debug

# Control variants per mode (default 5)
python -m eval.synthetic --n 5

# Combined — recommended for full runs
EXTRACTOR_VOTING_SAMPLES=1 python -m eval.synthetic --n 5 --throttle 4.5 --debug
```

When the synthetic file is present, `python -m eval.run_eval` adds a
**`workload_stability_rate`** key to `summary.json` — the fraction of
synthetic variants whose extracted `workload_type` still matches the base
reference's `expected_workload`. Compare runs with
`EXTRACTOR_VOTING_SAMPLES=1` vs. the default `=3` to quantify the voting
lift.

**Consistency score.** `synthetic_stability.json` now also reports a
single aggregated score in `[0, 1]` combining the per-mode
`(1 − workload_flip) × component_jaccard × (1 − crash)`. It is intended
as a one-number north-star for prompt-engineering iterations — changes
that improve stability move this number up regardless of which mode
drove the improvement.

### 8.4 Qualitative rubric (manual, 1–5 scale)

- Assumption reasonableness
- Diagram clarity
- Explanation quality and citation accuracy
- Handling of contradictory / vague input (graceful degradation)

### 8.5 Report format

`eval/results/results.md` — summary table (including latency p50/p95,
tokens, $ per run, judge scores) + per-reference breakdown.  
`eval/results/latency_histogram.json` — raw per-stage duration samples.  
`eval/results/ablation.md` — 4-config ablation table with uplift deltas.  
`eval/results/rag_report.md` — RAG retrieval ablation table.  
`eval/results/synthetic_stability.md` — stability per mode + consistency score.  
`docs/RAG_REPORT.md` — full RAG methodology writeup.  
`docs/DEPLOYMENT.md` — productionisation notes (auth, tenancy,
rate-limiting, observability).  
All of the above go into the PDF documentation.

---

## 9. Deliverables Checklist

### 9.1 GitHub repository
- [ ] Source code (full pipeline)
- [ ] `README.md` with:
  - Project overview
  - Setup instructions (`pip install`, `.env` setup, Terraform install)
  - Run instructions (`streamlit run app.py`)
  - Example outputs (screenshots)
  - Architecture diagram
- [ ] `eval/` with reference prompts, fixtures, and results
- [ ] `templates/` and `patches/` JSON
- [ ] KB source files (or links if large)
- [ ] `requirements.txt`
- [ ] `.env.example`
- [ ] LICENSE (MIT recommended)

### 9.2 PDF documentation
- [ ] System architecture diagram (the Mermaid/diagram from §5.2)
- [ ] Implementation details (modules, interfaces, key decisions)
- [ ] Performance metrics (from `eval/results.md`)
- [ ] Challenges and solutions (retry loop design, ambiguity handling)
- [ ] Future improvements (multi-cloud, real AWS deploy mode, IAM policy audit add-on)
- [ ] Ethical considerations (bias in defaults, doc currency, cost estimate disclaimers)

### 9.3 Video (10 min)
Suggested script:
1. **0:00–0:30** Hook — type "HIPAA telemedicine API" → architecture appears
2. **0:30–2:30** Feature walkthrough — diagram, TF, cost, explanation tabs
3. **2:30–5:30** Architecture deep-dive — pipeline stages, RAG, validation loop
4. **5:30–7:30** Evaluation results — metrics, reference prompt breakdown
5. **7:30–9:00** Edge case demo — vague/contradictory prompt handling
6. **9:00–10:00** Lessons learned + future work

### 9.4 Web page (GitHub Pages)
- [ ] Hero section with project name + one-liner
- [ ] Screenshot/GIF of the tool in action
- [ ] Feature list
- [ ] Link to GitHub repo
- [ ] Link to video
- [ ] Embedded PDF or link
- [ ] (Stretch) live demo via Streamlit Community Cloud

---

## 10. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LLM generates TF that won't validate | High | High | Retry loop (3 attempts), template-based generation limits freedom, static fallbacks per template |
| `diagrams` lib Graphviz dep fails on Windows | Medium | Medium | Install Graphviz in day 1 morning; fallback to Mermaid text rendering if bust |
| Gemini free tier rate-limited during demo | Low | High | Pre-record demo; keep OpenAI key as backup |
| Cost estimates wildly wrong | Medium | Low | Static pricing JSON for the ~15 services used; disclaimer in UI |
| Evaluation takes longer than planned | High | Medium | Cut from 5 → 3 reference prompts if day 2 afternoon is tight |
| Streamlit UI eats more time than expected | Medium | Medium | Strict 2.5h timebox; accept ugly |
| Graphviz/TF install issues | Medium | High | Install and smoke-test both tools in first hour of day 1 |

---

## 11. Critical Files Reference (for implementing agents)

When an implementing agent starts work, these are the files to read/create in order:

1. `templates/*.json` — read first, they define the output shape
2. `pipeline/schema.py` — ArchSpec pydantic model shared across all stages
3. `pipeline/extractor.py` + `pipeline/prompts/` — entry point of the generation flow; prompts are versioned files loaded via the cached loader
4. `pipeline/voting.py` — self-consistency merger logic (majority + element-wise + conservative-tie rules)
5. `pipeline/prompts/allowlist.py` — deterministic resource-type allowlist scanned from templates+patches, injected into the extractor system prompt
6. `pipeline/explainer.py` — CoT parser + `ExplainResult(rationale, thinking)` dataclass
7. `pipeline/orchestrator.py` — `run_streaming()` generator + `RunResult` with timings, tokens, $-cost, tfsec findings, cost provenance
8. `pipeline/validator.py` — hardest module, highest complexity; surfaces structured tfsec findings
9. `pipeline/cache.py` + `pipeline/export.py` + `pipeline/run_log.py` — caching, bundle export, structured event log
10. `pipeline/llm.py` — Gemini client with per-call token-usage + pinned price table
11. `rag/ingest.py` + `rag/retriever.py` — RAG pipeline; rebuild index after any KB edit
12. `app.py` — user-facing surface (streaming status, Security tab, bundle export)
13. `eval/run_eval.py` + `eval/ablation.py` + `eval/judge.py` + `eval/rag_eval.py` — define what "working" means
14. `docs/RAG_REPORT.md` — RAG design decisions and eval numbers
15. `docs/DEPLOYMENT.md` — auth / tenancy / rate-limit / observability upgrade path

---

## 12. Out-of-Scope / Future Work

Documented so future agents don't scope-creep:

- Real AWS deployment with sandbox account + auto-destroy
- Multi-cloud (Azure, GCP)
- Drift detection vs existing state
- IAM policy auditor as a separate mode (could be a follow-on project)
- Fine-tuned extractor model
- Terraform module ecosystem integration (registry.terraform.io)
- Live cost optimization recommendations

---

## 13. Verification Plan

How to confirm the build is done end-to-end:

1. **Unit level:** `pytest tests/` — all 70 tests pass, no warnings
2. **RAG index:** `python -m rag.ingest` — `meta.json` shows `count > 1000`, `has_bm25: true`, ≥ 10 services tagged
3. **RAG eval:** `python -m eval.rag_eval` — `hybrid_rrf_rerank` hit@5 ≥ 0.80 (pending full KB population)
4. **Integration:** `streamlit run app.py`, submit "serverless API with auth and DB", all 7 tabs populate with non-empty, coherent content
5. **Validation:** Generated TF passes `terraform validate` locally
6. **Security:** `tfsec` reports 0 HIGH findings on default (no-toggle) templates
7. **Pipeline eval:** `python -m eval.run_eval` — metrics meeting targets in §8.1
8. **Extractor stability:** `python -m eval.synthetic --n 5 --throttle 4.5` — aggregate consistency score ≥ 0.90, component Jaccard ≥ 0.91 in every mode, crash rate 0.00 across all 180 variants
9. **Demo path:** Record video walking through UC-1 and UC-2 end-to-end without errors
