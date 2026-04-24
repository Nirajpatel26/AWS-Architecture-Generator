"""LLM-as-judge for explanation quality.

Gemini grades each explanation on:
  - faithfulness (0-5): every claim traceable to a retrieved RAG chunk OR to
    a resource present in the template
  - completeness  (0-5): covers the major architecture decisions
  - citations_valid (bool): in-text citations (if any) correspond to real
    retrieved chunk indices

Fail-silent: returns {} when Gemini is unreachable (preserves the CLAUDE.md
fail-silent contract so eval/run_eval.py still completes offline).
"""
from __future__ import annotations

from typing import List

from pipeline.llm import generate_json

_RUBRIC = """You are a strict reviewer grading a cloud architecture rationale.

PROMPT: {prompt}

TEMPLATE RESOURCES: {resources}

RETRIEVED KNOWLEDGE (numbered [1], [2]...):
{retrieved}

RATIONALE:
{explanation}

Grade the rationale on this rubric. Output JSON only, matching:
{{
  "faithfulness": 0-5,
  "completeness": 0-5,
  "citations_valid": true|false,
  "rationale": "one-sentence justification"
}}

- faithfulness = how well every claim is supported by the retrieved chunks
  OR by a resource that actually appears in the template. Hallucinated
  services or made-up limits drop this to 0-2.
- completeness = does it cover storage, compute, security posture, and cost
  drivers? A single paragraph that only names services = 2.
- citations_valid = if the rationale cites [1], [2], etc., do the indices
  exist in the retrieved list? True if no citations are used.
"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "faithfulness": {"type": "integer"},
        "completeness": {"type": "integer"},
        "citations_valid": {"type": "boolean"},
        "rationale": {"type": "string"},
    },
    "required": ["faithfulness", "completeness", "citations_valid"],
}


def _format_retrieved(retrieved: List[dict]) -> str:
    if not retrieved:
        return "(none)"
    lines = []
    for i, h in enumerate(retrieved, 1):
        src = h.get("source", "doc")
        snip = (h.get("snippet") or "").replace("\n", " ")[:200]
        lines.append(f"[{i}] {src}: {snip}")
    return "\n".join(lines)


def judge_explanation(
    prompt: str,
    explanation: str,
    retrieved: List[dict],
    resources: List[str] | None = None,
) -> dict:
    """Grade `explanation`. Returns {} on any failure."""
    if not explanation:
        return {}
    body = _RUBRIC.format(
        prompt=prompt[:500],
        resources=", ".join(resources or []) or "(none)",
        retrieved=_format_retrieved(retrieved),
        explanation=explanation[:3000],
    )
    out = generate_json(body, schema=_SCHEMA)
    if not isinstance(out, dict):
        return {}
    return out
