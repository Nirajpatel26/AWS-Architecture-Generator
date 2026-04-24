"""Ablation table: RAG on/off × repair on/off.

Runs the reference prompt suite in all four configurations and reports
pass_rate / tf_validity / mean_recall / mean_latency / mean_cost_usd. This is
the headline artifact for the writeup — it shows that each design decision
(RAG context injection, LLM repair loop) measurably improves one of the
outcome metrics.

Configurations are toggled via env vars read by the pipeline:
  CLOUDARCH_RAG_DISABLED=1    -> extractor._retrieve_context returns []
  CLOUDARCH_REPAIR_DISABLED=1 -> validator.validate caps attempts at 1
  CLOUDARCH_CACHE_DISABLED=1  -> prompt cache bypassed (always on for ablation
                                 so each config gets a clean measurement)

Usage:
    python -m eval.ablation
"""
from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path
from typing import Dict, List

from pipeline import orchestrator

ROOT = Path(__file__).resolve().parent
PROMPTS_FILE = ROOT / "reference_prompts.json"
RESULTS_DIR = ROOT / "results"

CONFIGS: List[Dict[str, str]] = [
    {"name": "rag_on__repair_on", "rag": "1", "repair": "1"},
    {"name": "rag_off__repair_on", "rag": "0", "repair": "1"},
    {"name": "rag_on__repair_off", "rag": "1", "repair": "0"},
    {"name": "rag_off__repair_off", "rag": "0", "repair": "0"},
]


def _set_env(rag: str, repair: str) -> None:
    if rag == "0":
        os.environ["CLOUDARCH_RAG_DISABLED"] = "1"
    else:
        os.environ.pop("CLOUDARCH_RAG_DISABLED", None)
    if repair == "0":
        os.environ["CLOUDARCH_REPAIR_DISABLED"] = "1"
    else:
        os.environ.pop("CLOUDARCH_REPAIR_DISABLED", None)
    # Always bypass the prompt cache so each config re-extracts.
    os.environ["CLOUDARCH_CACHE_DISABLED"] = "1"


def _recall(expected, got):
    if not expected:
        return 1.0
    return sum(1 for e in expected if e in got) / len(expected)


def run_one_config(cfg: dict, cases: List[dict]) -> dict:
    _set_env(cfg["rag"], cfg["repair"])
    rows = []
    for case in cases:
        t0 = time.perf_counter()
        result = orchestrator.run(case["prompt"])
        elapsed = time.perf_counter() - t0
        produced = [r["type"] for r in result.template.get("resources", [])]
        expected = case.get("expected_components", [])
        rows.append(
            {
                "id": case["id"],
                "workload_match": result.spec.workload_type == case.get("expected_workload"),
                "component_recall": _recall(expected, produced),
                "tf_valid": result.tf_valid,
                "tf_attempts": result.tf_attempts,
                "latency_seconds": round(elapsed, 3),
                "monthly_cost": result.monthly_cost,
                "estimated_cost_usd": result.estimated_cost_usd,
                "total_tokens": result.total_input_tokens + result.total_output_tokens,
            }
        )

    def _mean(key):
        vals = [r[key] for r in rows if isinstance(r[key], (int, float))]
        return round(statistics.mean(vals), 4) if vals else 0.0

    n = len(rows)
    summary = {
        "config": cfg["name"],
        "rag": cfg["rag"] == "1",
        "repair": cfg["repair"] == "1",
        "cases": n,
        "workload_match_rate": round(sum(1 for r in rows if r["workload_match"]) / n, 3),
        "tf_validity_rate": round(sum(1 for r in rows if r["tf_valid"]) / n, 3),
        "mean_component_recall": _mean("component_recall"),
        "mean_latency_seconds": _mean("latency_seconds"),
        "mean_tf_attempts": _mean("tf_attempts"),
        "mean_estimated_cost_usd": _mean("estimated_cost_usd"),
        "mean_total_tokens": _mean("total_tokens"),
    }
    return {"summary": summary, "rows": rows}


def main() -> None:
    cases = json.loads(PROMPTS_FILE.read_text(encoding="utf-8"))
    all_results = []
    for cfg in CONFIGS:
        print(f"Running config: {cfg['name']}…")
        all_results.append(run_one_config(cfg, cases))

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "ablation.json").write_text(
        json.dumps(all_results, indent=2), encoding="utf-8"
    )

    md = [
        "# Ablation Results",
        "",
        "Pipeline with each design decision toggled on/off. Higher is better "
        "for recall / tf_validity; lower is better for latency / cost / tokens.",
        "",
        "| Config | TF valid | Recall | Workload | Latency (s) | Repair attempts | $ / run | Tokens |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in all_results:
        s = r["summary"]
        md.append(
            f"| **{s['config']}** | {s['tf_validity_rate']} | {s['mean_component_recall']} | "
            f"{s['workload_match_rate']} | {s['mean_latency_seconds']} | "
            f"{s['mean_tf_attempts']} | ${s['mean_estimated_cost_usd']:.5f} | "
            f"{int(s['mean_total_tokens'])} |"
        )

    # Simple "uplift" callouts — on vs off deltas.
    by = {r["summary"]["config"]: r["summary"] for r in all_results}
    try:
        rag_uplift = by["rag_on__repair_on"]["mean_component_recall"] - by["rag_off__repair_on"]["mean_component_recall"]
        repair_uplift = by["rag_on__repair_on"]["tf_validity_rate"] - by["rag_on__repair_off"]["tf_validity_rate"]
        md += [
            "",
            "## Uplift summary",
            "",
            f"- **RAG uplift on component recall:** +{rag_uplift:.3f}",
            f"- **Repair loop uplift on tf_validity:** +{repair_uplift:.3f}",
        ]
    except KeyError:
        pass

    (RESULTS_DIR / "ablation.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps([r["summary"] for r in all_results], indent=2))


if __name__ == "__main__":
    main()
