"""Run the reference prompt suite and produce a metrics report.

Extended with "hard" metrics:
- Per-stage latency (p50/p95 aggregated across cases → latency_histogram.json)
- Token usage + estimated $ cost per run, summed in the report
- LLM-as-judge grade on explanation faithfulness/completeness (when Gemini
  is reachable — gracefully skipped offline).

Usage:
    python -m eval.run_eval
"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Dict, List

from pipeline import orchestrator

try:
    from .judge import judge_explanation
except Exception:  # pragma: no cover
    def judge_explanation(*_args, **_kwargs):
        return {}

ROOT = Path(__file__).resolve().parent
PROMPTS_FILE = ROOT / "reference_prompts.json"
RESULTS_DIR = ROOT / "results"


def _recall(expected: List[str], got: List[str]) -> float:
    if not expected:
        return 1.0
    hits = sum(1 for e in expected if e in got)
    return hits / len(expected)


def _precision(expected: List[str], got: List[str]) -> float:
    if not got:
        return 0.0
    hits = sum(1 for g in got if g in expected)
    return hits / len(got)


def run_one(case: dict) -> dict:
    t0 = time.perf_counter()
    result = orchestrator.run(case["prompt"])
    wall = time.perf_counter() - t0
    produced = [r["type"] for r in result.template.get("resources", [])]
    expected = case.get("expected_components", [])
    low, high = case.get("expected_cost_range", [0, 1e9])
    cost_ok = low <= result.monthly_cost <= high

    expected_compliance = set(case.get("expected_compliance", []))
    got_compliance = set(result.spec.compliance)
    compliance_match = expected_compliance.issubset(got_compliance)

    checks = {
        "workload_match": result.spec.workload_type == case.get("expected_workload"),
        "component_recall_ok": _recall(expected, produced) >= 0.6,
        "tf_valid": result.tf_valid,
        "cost_within_range": cost_ok,
        "compliance_match": compliance_match,
    }
    overall_pass = all(checks.values())

    # LLM-as-judge; returns {} when Gemini isn't configured.
    judge = judge_explanation(
        case["prompt"],
        result.explanation,
        retrieved=[],  # run_eval doesn't currently pass retrieved; judge handles empty
        resources=produced,
    )

    return {
        "id": case["id"],
        "prompt": case["prompt"],
        "workload_match": checks["workload_match"],
        "component_recall": round(_recall(expected, produced), 3),
        "component_precision": round(_precision(expected, produced), 3),
        "tf_valid": result.tf_valid,
        "tf_attempts": result.tf_attempts,
        "tfsec_high": result.tfsec_high,
        "monthly_cost": result.monthly_cost,
        "cost_within_range": cost_ok,
        "compliance_match": compliance_match,
        "expected_compliance": sorted(expected_compliance),
        "got_compliance": sorted(got_compliance),
        "validate_skipped": result.validate_skipped,
        "assumptions": result.spec.assumptions,
        "produced_components": produced,
        "pass": overall_pass,
        "produced_workload": result.spec.workload_type,
        "prompt_versions": result.prompt_versions,
        "explain_thinking": result.explain_thinking,
        # Hard metrics
        "stage_timings": result.stage_timings,
        "wall_seconds": round(wall, 3),
        "total_input_tokens": result.total_input_tokens,
        "total_output_tokens": result.total_output_tokens,
        "total_tokens": result.total_input_tokens + result.total_output_tokens,
        "estimated_cost_usd": result.estimated_cost_usd,
        "judge": judge,
    }


def _pct(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    vals = sorted(values)
    k = (len(vals) - 1) * q
    f = int(k)
    c = min(f + 1, len(vals) - 1)
    if f == c:
        return round(vals[f], 4)
    return round(vals[f] + (vals[c] - vals[f]) * (k - f), 4)


def _latency_histogram(rows: List[dict]) -> Dict[str, dict]:
    per_stage: Dict[str, List[float]] = {}
    for r in rows:
        for stage, t in (r.get("stage_timings") or {}).items():
            per_stage.setdefault(stage, []).append(float(t))
    return {
        stage: {
            "n": len(ts),
            "p50": _pct(ts, 0.5),
            "p95": _pct(ts, 0.95),
            "mean": round(statistics.mean(ts), 4) if ts else 0.0,
            "max": round(max(ts), 4) if ts else 0.0,
            "samples": [round(t, 4) for t in ts],
        }
        for stage, ts in per_stage.items()
    }


def summarize(rows: List[dict], hist: Dict[str, dict]) -> Dict[str, float]:
    def mean(key):
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return round(statistics.mean(vals), 3) if vals else 0.0

    n = len(rows)

    # judge means, only over rows that got a non-empty judge response
    faith_vals = [r["judge"].get("faithfulness") for r in rows if r.get("judge")]
    faith_vals = [v for v in faith_vals if isinstance(v, (int, float))]
    comp_vals = [r["judge"].get("completeness") for r in rows if r.get("judge")]
    comp_vals = [v for v in comp_vals if isinstance(v, (int, float))]

    summary = {
        "cases": n,
        "pass_count": sum(1 for r in rows if r["pass"]),
        "fail_count": sum(1 for r in rows if not r["pass"]),
        "pass_rate": round(sum(1 for r in rows if r["pass"]) / n, 3),
        "workload_match_rate": round(sum(r["workload_match"] for r in rows) / n, 3),
        "mean_component_recall": mean("component_recall"),
        "mean_component_precision": mean("component_precision"),
        "tf_validity_rate": round(sum(1 for r in rows if r["tf_valid"]) / n, 3),
        "cost_within_range_rate": round(sum(1 for r in rows if r["cost_within_range"]) / n, 3),
        "compliance_match_rate": round(sum(1 for r in rows if r["compliance_match"]) / n, 3),
        "total_tfsec_high": sum(r.get("tfsec_high", 0) for r in rows),
        # Hard metrics
        "total_input_tokens": sum(r.get("total_input_tokens", 0) for r in rows),
        "total_output_tokens": sum(r.get("total_output_tokens", 0) for r in rows),
        "total_cost_usd": round(sum(r.get("estimated_cost_usd", 0.0) for r in rows), 6),
        "mean_cost_per_run_usd": round(mean("estimated_cost_usd"), 6),
        "mean_wall_seconds": mean("wall_seconds"),
        "p50_wall_seconds": _pct([r["wall_seconds"] for r in rows], 0.5),
        "p95_wall_seconds": _pct([r["wall_seconds"] for r in rows], 0.95),
    }
    # Per-stage p50/p95 for summary (samples live in histogram file)
    for stage, s in hist.items():
        summary[f"p50_{stage}_seconds"] = s["p50"]
        summary[f"p95_{stage}_seconds"] = s["p95"]
    if faith_vals:
        summary["mean_judge_faithfulness"] = round(statistics.mean(faith_vals), 2)
    if comp_vals:
        summary["mean_judge_completeness"] = round(statistics.mean(comp_vals), 2)
    return summary


def _stability_rate() -> float | None:
    """Fraction of synthetic variants whose extracted workload matches their base."""
    synth = ROOT / "synthetic_prompts.json"
    if not synth.exists():
        return None
    try:
        variants = json.loads(synth.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not variants:
        return None
    matches = 0
    total = 0
    for v in variants:
        result = orchestrator.run(v["prompt"])
        total += 1
        if result.spec.workload_type == v.get("expected_workload"):
            matches += 1
    return round(matches / total, 3) if total else None


def main() -> None:
    cases = json.loads(PROMPTS_FILE.read_text(encoding="utf-8"))
    rows = [run_one(c) for c in cases]
    hist = _latency_histogram(rows)
    summary = summarize(rows, hist)
    stability = _stability_rate()
    if stability is not None:
        summary["workload_stability_rate"] = stability

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "per_case.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (RESULTS_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (RESULTS_DIR / "latency_histogram.json").write_text(
        json.dumps(hist, indent=2), encoding="utf-8"
    )

    md = ["# Eval Results", "", "## Summary", ""]
    for k, v in summary.items():
        md.append(f"- **{k}**: {v}")
    md.append("")
    md.append("## Per-case breakdown")
    md.append("")
    md.append("| id | pass | workload | recall | precision | tf_valid | tfsec_high | cost | $ / run | wall (s) |")
    md.append("|----|------|----------|--------|-----------|----------|------------|------|---------|----------|")
    for r in rows:
        mark = "PASS" if r["pass"] else "FAIL"
        md.append(
            f"| {r['id']} | {mark} | {r['workload_match']} | {r['component_recall']} | "
            f"{r['component_precision']} | {r['tf_valid']} | {r['tfsec_high']} | "
            f"${r['monthly_cost']:.2f} | ${r['estimated_cost_usd']:.5f} | "
            f"{r['wall_seconds']} |"
        )
    md.append("")
    md.append("## Latency histogram (per stage, seconds)")
    md.append("")
    md.append("| Stage | n | p50 | p95 | mean | max |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for stage, s in hist.items():
        md.append(f"| {stage} | {s['n']} | {s['p50']} | {s['p95']} | {s['mean']} | {s['max']} |")
    (RESULTS_DIR / "results.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
