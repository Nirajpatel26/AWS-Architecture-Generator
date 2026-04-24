"""End-to-end pipeline orchestration (LangGraph-style, but lightweight).

Instrumentation:
- Per-stage wall-clock latency in `RunResult.stage_timings` (seconds).
- Per-run LLM token usage + $ cost estimate in `RunResult.token_usage` /
  `RunResult.estimated_cost_usd`.
- `run_streaming()` yields (event, payload) tuples so the Streamlit UI can
  update stage-by-stage instead of staring at a 30s spinner.
"""
from __future__ import annotations

import copy
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

from . import (
    assumptions,
    cost,
    defaults,
    diagram,
    explainer,
    extractor,
    llm,
    schema,
    template_engine,
    tf_generator,
    validator,
)
from .run_log import log_stage, log_run


@dataclass
class RunResult:
    spec: schema.ArchSpec
    template: dict
    base_template: dict
    tf_code: str
    tf_valid: bool
    tf_attempts: int
    tf_errors: List[str] = field(default_factory=list)
    tfsec_high: int = 0
    tfsec_findings: List[dict] = field(default_factory=list)
    diagram_path: Optional[str] = None
    diagram_mermaid: str = ""
    monthly_cost: float = 0.0
    cost_breakdown: List[dict] = field(default_factory=list)
    cost_meta: Dict[str, str] = field(default_factory=dict)
    explanation: str = ""
    explain_thinking: Optional[str] = None
    validate_skipped: Optional[str] = None
    prompt_versions: Dict[str, str] = field(default_factory=dict)
    # Observability
    stage_timings: Dict[str, float] = field(default_factory=dict)
    token_usage: List[dict] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0


def _build_base_template(spec: schema.ArchSpec) -> dict:
    """Template with spec-based filtering but NO patches applied. Used for diff view."""
    tpl = template_engine.load_template(spec.workload_type)
    tpl["resources"] = template_engine._filter_by_spec(tpl.get("resources", []), spec)
    project_name = spec.project_name or tpl.get("variables", {}).get("project_name", "cloudarch")
    return template_engine._substitute(
        copy.deepcopy(tpl),
        {"project_name": project_name, "region": spec.region or "us-east-1"},
    )


def _prompt_versions() -> Dict[str, str]:
    return {
        "extractor": extractor.EXTRACTOR_PROMPT_VERSION,
        "extractor_fewshot": extractor.EXTRACTOR_FEWSHOT_VERSION,
        "explainer": explainer.EXPLAINER_PROMPT_VERSION,
        "validator_repair": validator.VALIDATOR_REPAIR_PROMPT_VERSION,
    }


def run_streaming(
    prompt: str,
    overrides: dict | None = None,
    retrieved: List[dict] | None = None,
    spec: Optional[schema.ArchSpec] = None,
) -> Iterator[Tuple[str, Any]]:
    """Generator variant of `run()` yielding stage events for UI streaming.

    Events:
      ("stage_started", stage_name)
      ("stage_done", stage_name, elapsed_seconds)
      ("result", RunResult)
    """
    llm.reset_usage()
    stage_timings: Dict[str, float] = {}

    def _stage(name: str, fn, *args, **kwargs):
        yield ("stage_started", name)
        t0 = time.perf_counter()
        result = fn(*args, **kwargs)
        elapsed = time.perf_counter() - t0
        stage_timings[name] = round(elapsed, 4)
        log_stage(name, elapsed)
        yield ("stage_done", name, round(elapsed, 4))
        yield ("__result__", result)

    def _drain(gen):
        """Consume a _stage generator, forwarding events and returning the stage result."""
        last = None
        for evt in gen:
            if isinstance(evt, tuple) and evt and evt[0] == "__result__":
                last = evt[1]
            else:
                pending.append(evt)
        return last

    pending: list = []

    def _flush():
        while pending:
            yield pending.pop(0)

    # Stage 1: extract
    if spec is None:
        spec = _drain(_stage("extract", extractor.extract, prompt))
        yield from _flush()
    else:
        stage_timings["extract"] = 0.0

    # Stage 2: defaults
    spec = _drain(_stage("defaults", defaults.apply_defaults, spec))
    yield from _flush()

    # Stage 3: assumptions / overrides
    if overrides:
        spec = _drain(_stage("assumptions", assumptions.confirmed, spec, overrides))
        yield from _flush()
    else:
        stage_timings["assumptions"] = 0.0

    # Stage 4: template assembly (plus base template for diff)
    base_template = _drain(_stage("base_template", _build_base_template, spec))
    yield from _flush()
    template = _drain(_stage("template_engine", template_engine.assemble, spec))
    yield from _flush()

    # Stage 5: HCL emit
    tf_code = _drain(_stage("tf_generator", tf_generator.emit, template, spec.region))
    yield from _flush()

    # Stage 6: validate + repair
    val = _drain(_stage("validator", validator.validate, tf_code))
    yield from _flush()

    # Stage 7: diagram
    png_mmd = _drain(_stage("diagram", diagram.render, template))
    yield from _flush()
    png, mermaid = png_mmd

    # Stage 8: cost
    cost_tuple = _drain(_stage("cost", cost.estimate, template, spec.scale))
    yield from _flush()
    total, breakdown = cost_tuple

    # Stage 9: explain
    explain_result = _drain(
        _stage("explainer", explainer.explain_structured, spec, template, retrieved or [])
    )
    yield from _flush()

    usage = llm.get_usage()
    in_tok = sum(e.get("input_tokens", 0) for e in usage)
    out_tok = sum(e.get("output_tokens", 0) for e in usage)
    est_cost = llm.estimate_cost_usd(usage)

    result = RunResult(
        spec=spec,
        template=template,
        base_template=base_template,
        tf_code=val.tf_code,
        tf_valid=val.ok,
        tf_attempts=val.attempts,
        tf_errors=val.errors,
        tfsec_high=val.tfsec_high,
        tfsec_findings=val.findings,
        diagram_path=png,
        diagram_mermaid=mermaid,
        monthly_cost=total,
        cost_breakdown=breakdown,
        cost_meta=cost.pricing_meta(),
        explanation=explain_result.rationale,
        explain_thinking=explain_result.thinking,
        validate_skipped=val.skipped_reason,
        prompt_versions=_prompt_versions(),
        stage_timings=stage_timings,
        token_usage=usage,
        total_input_tokens=in_tok,
        total_output_tokens=out_tok,
        estimated_cost_usd=est_cost,
    )
    log_run(prompt, result)
    yield ("result", result)


def run(
    prompt: str,
    overrides: dict | None = None,
    retrieved: List[dict] | None = None,
    spec: Optional[schema.ArchSpec] = None,
) -> RunResult:
    """Synchronous wrapper that drains run_streaming() to its final result."""
    final: Optional[RunResult] = None
    for evt in run_streaming(prompt, overrides=overrides, retrieved=retrieved, spec=spec):
        if evt[0] == "result":
            final = evt[1]
    assert final is not None, "run_streaming did not yield a result"
    return final


def result_to_dict(r: RunResult) -> dict:
    d = asdict(r)
    d["spec"] = r.spec.to_dict()
    return d
