# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Natural-language → AWS architecture diagram + Terraform + cost estimate. Northeastern SEM4 Prompt course final project. See `TECHNICAL_SPEC.md` for the full design doc; it is the source of truth for scope (4 templates, 3 toggles, static validation only — no real AWS deploys, no multi-cloud).

## Common commands

```bash
# Setup
pip install -r requirements.txt
# Put GEMINI_API_KEY in .env (see .env.example)

# Build the RAG index — REQUIRED after editing rag/knowledge_base/*.md
python -m rag.ingest

# Run the app
streamlit run app.py

# Tests
pytest tests/
pytest tests/test_template_engine.py::test_hipaa_patch   # single test

# Evaluation suite (writes eval/results/*.json + results.md)
python -m eval.run_eval
python -m eval.synthetic   # stability under synonym-swapped prompts
```

Optional external binaries — the pipeline degrades gracefully if absent:
- `terraform` — if missing, `validator.validate()` returns `ok=True` with `skipped_reason` set. Override path via `TERRAFORM_BIN`.
- `tfsec` — if missing, tfsec scan is a no-op. Override via `TFSEC_BIN`.
- Graphviz (`dot`) — if missing, `diagram.render()` returns `(None, mermaid_str)` and the UI shows the Mermaid fallback. On Windows `diagram.py` auto-adds `C:\Program Files\Graphviz\bin` to PATH.

## Architecture

The system is a **9-stage linear pipeline** orchestrated by `pipeline/orchestrator.py::run()`. Each stage is a small pure-ish module that takes a spec/template dict and returns the next form. Stages are numbered in the docstrings (`Stage 1`..`Stage 9`):

1. `extractor.py` — Gemini call with `GEMINI_JSON_SCHEMA` → `ArchSpec`
2. `defaults.py` — deterministic keyword-driven fills (no LLM); every default appends to `spec.assumptions`
3. `assumptions.py` — render assumptions + apply user overrides from the UI
4. `template_engine.py` — load `templates/<workload>.json`, apply `patches/*.json` in `order` field (HIPAA → HA → multi_region), do `{{project_name}}` / `{{region}}` substitution
5. `tf_generator.py` — **deterministic** JSON→HCL emitter (not LLM). LLM only invoked on validation failure
6. `validator.py` — `terraform init -backend=false` then `validate`; on failure, `_fix_with_llm()` patches the HCL and retries (MAX_ATTEMPTS=3). Then tfsec for severity counts
7. `diagram.py` — maps `resource.type` → Mingrammer `diagrams` classes via `_NODE_MAP`, buckets into tiers (edge/compute/data/identity/observability), draws semantic flows per workload
8. `cost.py` — looks up `resource.type` in `pricing.json`, multiplies by scale multiplier + any per-resource modifier (e.g. multi-AZ)
9. `explainer.py` — Gemini generates cited markdown rationale using retrieved RAG chunks

**Critical invariant:** the LLM never writes Terraform from scratch. Templates are the resource skeleton; patches are deterministic JSON transformations; the HCL emitter is pure; the LLM only *repairs* HCL when `terraform validate` fails. This is what makes outputs reliably valid.

### Shared data shapes

- **`pipeline/schema.py::ArchSpec`** — pydantic model passed between stages 1–4. Note the `assumptions` field is aliased to `_assumptions` on the wire (`populate_by_name=True`).
- **Template dict** — produced by stage 4, consumed by 5/7/8. Shape: `{resources: [{type, name, args}], providers: [...], variables: {...}, applied_patches: [...], patch_assumptions: [...]}`. The `resources[].type` string is the AWS Terraform resource name and is what all downstream stages key on.

### Templates & patches

Templates (`templates/*.json`) are hand-authored skeletons — 4 workload types. Patches (`patches/*.json`) are transformations with three kinds of operations:
- `mutate_resources[].merge_args` — deep-merge into an existing resource's `args`
- `mutate_resources[].add_sibling` — add a resource next to a match (e.g. KMS key next to each S3 bucket), with `{{match.name}}` substitution
- `add_resources` — append new top-level resources

Patch order is controlled by the `order` field in each patch JSON, not application-call order. HIPAA runs first so HA's mutations see encrypted resources.

### RAG

- `rag/ingest.py` — chunks `knowledge_base/*.md` by word count (500), embeds with MiniLM-L6-v2, writes FAISS IP index + pickled chunks to `rag/knowledge_base/.index/`. **Rerun after any KB edit.**
- `rag/retriever.py` — lazy-loads the index; returns `[]` silently if the index or deps are missing. Only consumed by `app.py` and passed to `explainer.py`. Extractor/template-engine/cost currently ignore RAG.

### LLM boundary

All Gemini calls go through `pipeline/llm.py` (`generate_json`, `generate_text`). Both return empty on any failure (no API key, network, parse error). Every caller must degrade gracefully — see `extractor.py` falling back to an empty `ArchSpec` and `defaults.py` filling everything deterministically afterward.

## Conventions

- **Fail-silent contract for external tools.** Terraform, tfsec, Graphviz, Gemini, FAISS — all optional. Guards live at the call site (`shutil.which`, try/except on import). Don't add hard failures for missing binaries; surface them in `RunResult` fields (`validate_skipped`, `diagram_mermaid`) instead.
- **Assumptions are user-facing output.** Any time a stage guesses a field, append a human-readable note to `spec.assumptions`. These render in the UI panel so users can catch misalignment.
- **Deterministic first, LLM on failure.** Stage 5 (HCL emit) and stage 8 (cost) must stay deterministic. The LLM is scoped to stage 1 (extract), stage 6 (repair), and stage 9 (explain).
- **Windows-friendly tempdirs.** `diagram.py::_writable_tempdir()` prefers a project-local `.cache/diagrams/` because Windows `%TEMP%` on C: has filled up in practice. Don't route new artifact writes through `tempfile.mkdtemp()` without the same fallback.

## Gstack skills

| Skill | Purpose |
|---|---|
| `/office-hours` | Open-ended Q&A and design discussion |
| `/plan-ceo-review` | Review a plan from a CEO/product perspective |
| `/plan-eng-review` | Review a plan from an engineering perspective |
| `/review` | Code review |
| `/qa` | QA / test-plan generation |
| `/ship` | End-to-end ship checklist |
| `/cso` | Security review |
| `/autoplan` | Auto-generate an implementation plan |
| `/investigate` | Investigate a bug or incident |
| `/retro` | Run a retrospective |
| `/design-shotgun` | Rapid design exploration (multiple options) |
| `/design-html` | Produce an HTML design mock-up |
| `/document-release` | Generate release notes / changelog |

## Evaluation

`eval/reference_prompts.json` defines 5 reference cases with `expected_workload`, `expected_components`, `expected_cost_range`. `run_eval.py` computes component recall/precision by matching `resource.type` strings against `expected_components` — so if you rename a Terraform resource type in a template, update the fixtures too.
