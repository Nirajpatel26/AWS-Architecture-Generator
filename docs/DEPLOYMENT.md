# Deployment & Productionization Notes

This project is delivered as a **single-tenant internal / demo tool** — a
Streamlit app running on one host, talking to Gemini over the public API.
The choices below are intentional trade-offs for the course scope; this doc
records what would need to change before shipping it as multi-tenant SaaS.

## Auth

**Current:** no auth. Anyone who can reach the Streamlit port can generate
architectures. Safe because the tool only reads from Gemini and writes to
local `.cache/`; it does not deploy to AWS or touch customer data.

**For SaaS:** front with one of
- [`streamlit-authenticator`](https://github.com/mkhorasani/Streamlit-Authenticator)
  for username/password,
- an SSO proxy (Cloudflare Access, Tailscale Funnel, Auth0 as OIDC),
- or embed behind an app that already handles auth.

## Multi-tenancy

**Current:** single shared `.cache/prompt_cache.sqlite` and
`.cache/runs.jsonl`. A shared cache is fine — prompts aren't secret — but
logs mix tenants.

**For SaaS:** partition by tenant
- cache key: `sha256(prompt + version + model + tenant_id)` — add a
  `tenant_id` argument to `pipeline.cache.get/put`;
- `.cache/runs.jsonl` → `.cache/runs/{tenant_id}.jsonl` or ship to a
  per-tenant bucket;
- `.cache/diagrams/` already writes unique filenames, so it's safe to share.

## Rate limiting

**Current:** none. The extractor can cost ~$0.002/run at current Gemini
prices, but without caps a loop could run it up quickly.

**For SaaS:**
- Streamlit-side: [`streamlit-extras.limiter`](https://extras.streamlit.app/)
  or a thin Redis counter keyed on `{tenant_id, hour_bucket}`;
- Gemini-side: set a `GEMINI_MAX_TOKENS_PER_DAY` budget and short-circuit
  `pipeline.llm.generate_json` when exceeded (returns `{}` → pipeline
  degrades gracefully per the existing fail-silent contract).

## Observability

**Current:** structured JSON logs to `.cache/runs.jsonl` (one line per
stage completion + one per run, see `pipeline/run_log.py`). Tail with
`jq`.

**For SaaS:** pipe the JSONL into
- LangFuse (self-hosted, free) — set up a `/v1/traces` ingest endpoint
  and POST each `run_complete` record;
- Datadog / Grafana Loki / Cloudwatch — any log collector that groks JSON;
- or swap `run_log.py` out for the `langfuse` SDK directly (one call site
  in `orchestrator.run_streaming`).

## Cost tracking

Token usage + $ cost per run are already on `RunResult.estimated_cost_usd`
and logged to `runs.jsonl`. For SaaS, aggregate by `tenant_id` nightly and
bill or throttle accordingly.

## Out of scope for course delivery

- Live AWS Pricing API (breaks the deterministic-offline contract);
- Multi-cloud (GCP/Azure) targets;
- Actual `terraform apply` — the project explicitly stops at validate.
