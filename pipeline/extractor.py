"""Stage 1: prompt -> structured ArchSpec via Gemini with JSON schema.

Uses RAG to ground extraction: before calling Gemini, we retrieve the top
service-doc chunks for the user prompt and inject them as context. This helps
the extractor infer the correct workload_type / compliance tags when the
prompt uses domain-specific vocabulary the base model might miss.

Prompt engineering upgrades (v2):
- Prompts live in `pipeline/prompts/*.v2.txt` (versioned).
- Few-shot examples injected before retrieved context.
- Service allowlist derived deterministically from templates + patches,
  injected into the system prompt as a negative-prompt guardrail.
- Self-consistency voting: sample N times and merge via `pipeline.voting`.
"""
from __future__ import annotations

import json
import os
from typing import List, Optional

from . import cache as prompt_cache
from . import normalizer
from .llm import generate_json
from .prompts import load, load_json
from .prompts.allowlist import format_allowlist
from .schema import ArchSpec, GEMINI_JSON_SCHEMA
from .voting import vote_specs

EXTRACTOR_PROMPT_VERSION = "v2"
EXTRACTOR_FEWSHOT_VERSION = "v1"

# Number of samples to draw for self-consistency voting. Override via env for
# fast local dev / CI where the 3x cost is undesirable.
VOTING_SAMPLES = int(os.getenv("EXTRACTOR_VOTING_SAMPLES", "3"))

# Extractor-side RAG defaults — service_doc only (no well_architected prose),
# and a small cap because extraction is latency-sensitive.
_EXTRACTOR_K = 3


def _retrieve_context(raw_prompt: str) -> List[dict]:
    """Pull top service/compliance doc chunks for the prompt. Fail silent."""
    # Ablation hook: eval/ablation.py sets this to measure the RAG uplift.
    if os.getenv("CLOUDARCH_RAG_DISABLED") == "1":
        return []
    try:
        from rag import retriever  # local import: keep extractor importable w/o rag deps
    except Exception:
        return []
    try:
        hits = retriever.retrieve(
            raw_prompt,
            k=_EXTRACTOR_K,
            filters={"doc_type": ["service_doc", "compliance"]},
        )
        if hits:
            return hits
        return retriever.retrieve(raw_prompt, k=_EXTRACTOR_K)
    except Exception:
        return []


def _format_context(hits: List[dict]) -> str:
    if not hits:
        return ""
    lines = ["Relevant reference material (use to disambiguate workload/compliance):"]
    for i, h in enumerate(hits, 1):
        src = h.get("source", "doc")
        snippet = (h.get("snippet") or "").strip().replace("\n", " ")
        if len(snippet) > 300:
            snippet = snippet[:300] + "..."
        lines.append(f"[{i}] {src}: {snippet}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _format_fewshot(examples: List[dict]) -> str:
    if not examples:
        return ""
    lines = ["Examples:"]
    for i, ex in enumerate(examples, 1):
        inp = ex.get("input", "")
        out = json.dumps(ex.get("output", {}), separators=(",", ": "))
        lines.append(f"{i}. Input: {inp}")
        lines.append(f"   Output: {out}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _build_prompt(raw_prompt: str, hits: List[dict]) -> tuple[str, str]:
    """Return (system_text, user_text) as separate strings.

    The system text is passed via GenerateContentConfig.system_instruction so
    it is handled as a true system prompt rather than being embedded in the
    user turn.
    """
    system = load(f"extractor.system.{EXTRACTOR_PROMPT_VERSION}").format(
        allowlist=format_allowlist()
    )
    fewshot = _format_fewshot(load_json(f"extractor.fewshot.{EXTRACTOR_FEWSHOT_VERSION}"))
    context_block = _format_context(hits)
    user_tpl = load(f"extractor.user.{EXTRACTOR_PROMPT_VERSION}")
    user = user_tpl.format(
        fewshot=fewshot,
        context_block=context_block,
        raw_prompt=raw_prompt,
    )
    return system, user


def extract(raw_prompt: str, retrieved: Optional[List[dict]] = None) -> ArchSpec:
    """Extract an ArchSpec from the prompt, voting over N samples.

    The prompt is first normalized (Stage 0) into canonical English so that
    paraphrases, translations, and noisy variants collapse to a stable form
    before the LLM extraction stage. The normalized text is stored as
    `spec.raw_prompt` so downstream keyword-based defaults operate on clean
    input.

    Consults a SQLite prompt cache first — identical prompt + same prompt
    version + same model returns in ~ms. Disable with `CLOUDARCH_CACHE_DISABLED=1`.
    """
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    try:
        normalized = normalizer.normalize(raw_prompt) or raw_prompt
    except Exception:
        normalized = raw_prompt

    # Cache keys off the normalized prompt so variants that canonicalize to
    # the same text share a result.
    cached = prompt_cache.get(normalized, EXTRACTOR_PROMPT_VERSION, model_name)
    if cached is not None:
        return cached

    hits = retrieved if retrieved is not None else _retrieve_context(normalized)
    system, user = _build_prompt(normalized, hits)

    n = max(1, VOTING_SAMPLES)
    samples: List[dict] = []
    for _ in range(n):
        try:
            samples.append(
                generate_json(user, schema=GEMINI_JSON_SCHEMA, system=system) or {}
            )
        except Exception:
            samples.append({})

    data = vote_specs(samples)
    # Downstream defaults.py keyword-matches on spec.raw_prompt — use the
    # normalized text so compliance/workload hints survive through typos etc.
    data["raw_prompt"] = normalized
    try:
        spec = ArchSpec(**{k: v for k, v in data.items() if v is not None})
    except Exception:
        spec = ArchSpec(raw_prompt=normalized)

    # Only cache meaningful extractions — skip empty/fallback specs.
    if any(samples):
        prompt_cache.put(normalized, EXTRACTOR_PROMPT_VERSION, model_name, spec)
    return spec
