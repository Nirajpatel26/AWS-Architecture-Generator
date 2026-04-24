"""Stage 9: generate a markdown design rationale with RAG citations.

v2 upgrade: structured chain-of-thought. The prompt asks Gemini to emit a
<thinking> block followed by a <rationale> block. The parser returns only
the rationale to callers and stashes the thinking separately so UIs can
hide it while eval artifacts keep it for inspection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from .llm import generate_text
from .prompts import load
from .schema import ArchSpec

EXPLAINER_PROMPT_VERSION = "v2"


@dataclass
class ExplainResult:
    rationale: str
    thinking: Optional[str] = None


def _fallback(spec: ArchSpec, template: dict, retrieved: List[dict]) -> str:
    lines = [
        f"## Design rationale for `{spec.project_name}`",
        "",
        f"**Workload:** {spec.workload_type} ({spec.scale})",
        f"**Region:** {spec.region}" + (" + multi-region" if spec.multi_region else ""),
        f"**Compliance:** {', '.join(spec.compliance) or 'none'}",
        f"**HA:** {'yes' if spec.ha_required else 'no'}",
        "",
        "### Components chosen",
    ]
    for r in template.get("resources", []):
        lines.append(f"- `{r['type']}.{r['name']}`")
    if retrieved:
        lines += ["", "### References"]
        for r in retrieved[:5]:
            lines.append(f"- {r.get('source', 'doc')}: {r.get('snippet', '')[:140]}")
    return "\n".join(lines)


_THINKING_RE = re.compile(r"<thinking>(.*?)</thinking>", re.DOTALL | re.IGNORECASE)
_RATIONALE_RE = re.compile(r"<rationale>(.*?)</rationale>", re.DOTALL | re.IGNORECASE)


def _parse_cot(text: str) -> ExplainResult:
    """Split structured CoT output. Falls back to raw text if tags missing."""
    thinking_match = _THINKING_RE.search(text)
    rationale_match = _RATIONALE_RE.search(text)
    thinking = thinking_match.group(1).strip() if thinking_match else None
    if rationale_match:
        return ExplainResult(rationale=rationale_match.group(1).strip(), thinking=thinking)
    # Tag-less output: strip any stray <thinking> block before returning.
    cleaned = _THINKING_RE.sub("", text).strip()
    return ExplainResult(rationale=cleaned, thinking=thinking)


def explain_structured(
    spec: ArchSpec, template: dict, retrieved: List[dict] | None = None
) -> ExplainResult:
    """Structured variant: returns rationale + optional thinking trace."""
    retrieved = retrieved or []
    context = "\n".join(
        f"[{i+1}] {r.get('source', '')}: {r.get('snippet', '')}"
        for i, r in enumerate(retrieved[:5])
    )
    components = ", ".join(r["type"] for r in template.get("resources", []))
    prompt = load(f"explainer.{EXPLAINER_PROMPT_VERSION}").format(
        raw_prompt=spec.raw_prompt,
        workload_type=spec.workload_type,
        scale=spec.scale,
        compliance=spec.compliance,
        ha_required=spec.ha_required,
        components=components,
        context=context,
    )
    text = generate_text(prompt).strip()
    if not text:
        return ExplainResult(rationale=_fallback(spec, template, retrieved))
    parsed = _parse_cot(text)
    if not parsed.rationale:
        return ExplainResult(rationale=_fallback(spec, template, retrieved), thinking=parsed.thinking)
    return parsed


def explain(spec: ArchSpec, template: dict, retrieved: List[dict] | None = None) -> str:
    """Back-compat string API — returns just the rationale."""
    return explain_structured(spec, template, retrieved).rationale
