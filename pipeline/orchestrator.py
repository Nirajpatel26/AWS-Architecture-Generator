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
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

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

    stage_errors: Dict[str, str] = {}

    def _stage(name: str, fn, *args, fallback: Any = None, **kwargs):
        """Run a stage, capturing exceptions and substituting `fallback`.

        Crashes in any single stage should degrade gracefully rather than
        abort the whole pipeline — the synthetic-stability eval (and the UI)
        treats a partial `RunResult` as much better than a raised exception.
        """
        yield ("stage_started", name)
        t0 = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — intentional catch-all per stage
            traceback.print_exc(file=sys.stderr)
            stage_errors[name] = f"{type(e).__name__}: {e}"
            result = fallback() if callable(fallback) else fallback
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
        spec = _drain(_stage(
            "extract", extractor.extract, prompt,
            fallback=lambda: schema.ArchSpec(raw_prompt=prompt),
        ))
        yield from _flush()
    else:
        stage_timings["extract"] = 0.0

    # Stage 2: defaults
    spec = _drain(_stage(
        "defaults", defaults.apply_defaults, spec,
        fallback=spec,
    ))
    yield from _flush()

    # Stage 3: assumptions / overrides
    if overrides:
        spec = _drain(_stage(
            "assumptions", assumptions.confirmed, spec, overrides,
            fallback=spec,
        ))
        yield from _flush()
    else:
        stage_timings["assumptions"] = 0.0

    # Stage 4: template assembly (plus base template for diff)
    _empty_tpl = lambda: {"resources": [], "providers": [], "variables": {}, "applied_patches": [], "patch_assumptions": []}
    base_template = _drain(_stage(
        "base_template", _build_base_template, spec,
        fallback=_empty_tpl,
    ))
    yield from _flush()
    template = _drain(_stage(
        "template_engine", template_engine.assemble, spec,
        fallback=_empty_tpl,
    ))
    yield from _flush()
    if not isinstance(template, dict):
        template = _empty_tpl()
    if not isinstance(base_template, dict):
        base_template = _empty_tpl()

    # Stage 5: HCL emit
    tf_code = _drain(_stage(
        "tf_generator", tf_generator.emit, template, spec.region,
        fallback="",
    ))
    yield from _flush()

    # Stage 6: validate + repair
    _val_fallback = lambda: validator.ValidationResult(
        ok=False, attempts=0, tf_code=tf_code or "",
        errors=["validator stage skipped (pipeline fallback)"],
        skipped_reason="exception",
    )
    val = _drain(_stage(
        "validator", validator.validate, tf_code or "",
        fallback=_val_fallback,
    ))
    yield from _flush()
    if val is None:
        val = _val_fallback()

    # Stage 7: diagram
    png_mmd = _drain(_stage(
        "diagram", diagram.render, template,
        fallback=(None, ""),
    ))
    yield from _flush()
    if not isinstance(png_mmd, tuple) or len(png_mmd) != 2:
        png_mmd = (None, "")
    png, mermaid = png_mmd

    # Stage 8: cost
    cost_tuple = _drain(_stage(
        "cost", cost.estimate, template, spec.scale,
        fallback=(0.0, []),
    ))
    yield from _flush()
    if not isinstance(cost_tuple, tuple) or len(cost_tuple) != 2:
        cost_tuple = (0.0, [])
    total, breakdown = cost_tuple

    # Stage 9: explain
    explain_result = _drain(_stage(
        "explainer", explainer.explain_structured, spec, template, retrieved or [],
        fallback=lambda: explainer.ExplainResult(rationale="", thinking=None),
    ))
    yield from _flush()
    if explain_result is None:
        explain_result = explainer.ExplainResult(rationale="", thinking=None)

    try:
        usage = llm.get_usage()
        in_tok = sum(e.get("input_tokens", 0) for e in usage)
        out_tok = sum(e.get("output_tokens", 0) for e in usage)
        est_cost = llm.estimate_cost_usd(usage)
    except Exception:
        usage, in_tok, out_tok, est_cost = [], 0, 0, 0.0

    try:
        cost_meta = cost.pricing_meta()
    except Exception:
        cost_meta = {}

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
        cost_meta=cost_meta,
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
    try:
        log_run(prompt, result)
    except Exception:
        pass
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
