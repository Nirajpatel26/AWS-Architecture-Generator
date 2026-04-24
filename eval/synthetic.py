"""Generative synthetic data + stability evaluation.

This replaces the old hardcoded-synonym swapper with four real generative
modes driven by Gemini:

  - paraphrase   : high-temperature rewrites that preserve intent
  - adversarial  : vague / contradictory / over-specified noise variants
  - multilingual : non-English translations (tests extractor robustness)
  - noisy        : typos, filler words, ALL CAPS, informal chat-speak

For each base case we generate N variants per mode, run the full pipeline
on each variant, and report stability metrics:

  - workload_flip_rate : variants whose inferred `workload_type` differs
                         from the base run
  - component_jaccard  : Jaccard similarity of component sets (base vs variant)
  - compliance_drift   : variants whose compliance set differs from base
  - graceful_failure   : fraction of adversarial variants that still produce
                         `tf_valid=True` (no hard crash)

Usage:
    python -m eval.synthetic              # generate + run + score
    python -m eval.synthetic --generate-only
    python -m eval.synthetic --modes paraphrase,adversarial
    python -m eval.synthetic --n 3

Falls back to a deterministic swap-based generator if Gemini is unreachable
so the eval suite still runs offline (flagged as `llm_available: false` in
the report).
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pipeline import llm, orchestrator

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "reference_prompts.json"
OUT_VARIANTS = ROOT / "synthetic_prompts.json"
RESULTS_DIR = ROOT / "results"

MODES = ("paraphrase", "adversarial", "multilingual", "noisy")

# ---------------------------------------------------------------------------
# LLM-backed variant generation
# ---------------------------------------------------------------------------

_PARAPHRASE_PROMPT = """Paraphrase the following cloud-architecture workload description {n} different
ways. Preserve the original intent — same workload type, same compliance
requirements, same scale signal — but vary wording, sentence structure, and
technical vocabulary (use synonyms, reorder clauses, switch between formal
and casual register).

Do NOT add new constraints, compliance regimes, or services. Do NOT drop
signals the original carried (e.g. if original says HIPAA, every variant
must still imply HIPAA).

Return strict JSON: {{"variants": ["...", "...", ...]}} — exactly {n} strings,
no commentary.

Original: "{prompt}"
"""

_ADVERSARIAL_PROMPT = """Generate {n} ADVERSARIAL variants of the cloud-architecture prompt below.
Each variant should stress-test the extractor in a different way:

  - vague   : strip all concrete signals, leave only a handwavy ask
  - contradictory : add a constraint that contradicts an existing signal
                    (e.g. "no compliance needed" alongside PHI)
  - over-specified : bury the core ask under irrelevant technical jargon
  - off-topic-noise : prepend/append unrelated content (weather, a recipe)
                      but keep the real ask in there

Mix types across the {n} variants. Each variant MUST still contain enough
signal that a reasonable extractor *could* recover the original workload_type
— we're testing robustness, not nonsense tolerance.

Return strict JSON: {{"variants": ["...", ...]}} — exactly {n} strings.

Original: "{prompt}"
"""

_MULTILINGUAL_PROMPT = """Translate the following cloud-architecture workload description into {n}
different languages (pick a mix: Spanish, French, German, Japanese, Mandarin,
Portuguese, Hindi, Arabic — whichever {n} fit). Preserve all technical
signals (compliance, scale, workload type).

Keep AWS service names, compliance acronyms (HIPAA, PCI, SOC2), and
technical terms (API, CDN, multi-AZ) in English — that's how engineers
actually write these in practice.

Return strict JSON: {{"variants": ["...", ...]}} — exactly {n} strings.

Original: "{prompt}"
"""

_NOISY_PROMPT = """Rewrite the following cloud-architecture workload description {n} times in
progressively noisier styles:

  - add typos and missing punctuation
  - use informal chat-speak ("gimme", "lowkey", "tbh")
  - SHOUT IN ALL CAPS in one variant
  - add filler ("so basically", "like", "you know")
  - mix upper/lower case randomly in one variant

Preserve the original workload intent. Return strict JSON:
{{"variants": ["...", ...]}} — exactly {n} strings.

Original: "{prompt}"
"""

_MODE_PROMPTS = {
    "paraphrase": _PARAPHRASE_PROMPT,
    "adversarial": _ADVERSARIAL_PROMPT,
    "multilingual": _MULTILINGUAL_PROMPT,
    "noisy": _NOISY_PROMPT,
}


# Deterministic fallback if Gemini is unreachable
_FALLBACK_SWAPS = [
    ("API", ["endpoint", "service", "REST API"]),
    ("database", ["datastore", "DB", "storage layer"]),
    ("multi-AZ", ["highly available", "redundant across zones"]),
    ("HIPAA", ["PHI-handling", "regulated healthcare"]),
    ("web app", ["web application", "frontend + backend app"]),
    ("analytics", ["reporting", "BI"]),
    ("pipeline", ["data flow", "ETL"]),
]


def _fallback_mutate(prompt: str, rng: random.Random) -> str:
    p = prompt
    for needle, opts in _FALLBACK_SWAPS:
        if needle.lower() in p.lower() and rng.random() < 0.6:
            p = p.replace(needle, rng.choice(opts))
    return p


def _llm_variants(prompt: str, mode: str, n: int) -> List[str]:
    tmpl = _MODE_PROMPTS[mode]
    data = llm.generate_json(tmpl.format(prompt=prompt, n=n))
    variants = data.get("variants") if isinstance(data, dict) else None
    if not variants or not isinstance(variants, list):
        return []
    return [str(v) for v in variants if isinstance(v, str) and v.strip()][:n]


def generate(
    n_per_mode: int = 5,
    modes: Tuple[str, ...] = MODES,
    seed: int = 0,
) -> Tuple[List[dict], bool]:
    """Generate synthetic variants for every reference case.

    Returns (variants_list, llm_available). If `llm_available` is False the
    variants come from the deterministic fallback."""
    cases = json.loads(SRC.read_text(encoding="utf-8"))
    rng = random.Random(seed)

    llm_ok = llm.is_available()
    out: List[dict] = []
    for case in cases:
        for mode in modes:
            variants: List[str] = []
            if llm_ok:
                variants = _llm_variants(case["prompt"], mode, n_per_mode)
            if not variants:
                variants = [
                    _fallback_mutate(case["prompt"], rng) for _ in range(n_per_mode)
                ]
            for i, v in enumerate(variants):
                out.append(
                    {
                        "base_id": case["id"],
                        "mode": mode,
                        "variant": i,
                        "prompt": v,
                        "base_prompt": case["prompt"],
                        "expected_workload": case["expected_workload"],
                        "expected_components": case["expected_components"],
                    }
                )

    OUT_VARIANTS.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out, llm_ok


# ---------------------------------------------------------------------------
# Stability evaluation
# ---------------------------------------------------------------------------


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(1, len(a | b))


DEBUG = False
THROTTLE_SEC = 0.0


def _run_spec(prompt: str) -> Optional[dict]:
    if THROTTLE_SEC > 0:
        time.sleep(THROTTLE_SEC)
    try:
        result = orchestrator.run(prompt)
    except Exception as e:
        if DEBUG:
            traceback.print_exc(file=sys.stderr)
        return {"_error": f"{type(e).__name__}: {e}"}
    return {
        "workload_type": result.spec.workload_type,
        "compliance": sorted(result.spec.compliance),
        "components": sorted({r["type"] for r in result.template.get("resources", [])}),
        "tf_valid": result.tf_valid,
        "monthly_cost": result.monthly_cost,
    }


def evaluate(variants: List[dict], verbose: bool = True) -> dict:
    """Run pipeline on base prompt + every variant, compute stability metrics."""
    cases_by_id: Dict[str, dict] = {}
    for v in variants:
        cases_by_id.setdefault(v["base_id"], {"base_prompt": v["base_prompt"], "variants": []})
        cases_by_id[v["base_id"]]["variants"].append(v)

    per_case: List[dict] = []
    for bid, bundle in cases_by_id.items():
        if verbose:
            print(f"[base] {bid}: running base prompt\u2026", file=sys.stderr)
        base = _run_spec(bundle["base_prompt"])
        if base is None or "_error" in base:
            if verbose:
                print(f"  [base] FAILED: {base}", file=sys.stderr)
            per_case.append({"base_id": bid, "error": base})
            continue

        per_mode: Dict[str, dict] = {}
        for v in bundle["variants"]:
            if verbose:
                print(f"  [{v['mode']}] variant {v['variant']}", file=sys.stderr)
            got = _run_spec(v["prompt"])
            if got and "_error" in got and verbose:
                print(f"    -> error: {got['_error']}", file=sys.stderr)
            entry = per_mode.setdefault(
                v["mode"],
                {
                    "n": 0,
                    "workload_flips": 0,
                    "jaccards": [],
                    "compliance_drifts": 0,
                    "tf_valid_count": 0,
                    "crashed": 0,
                },
            )
            entry["n"] += 1
            if got is None or "_error" in got:
                entry["crashed"] += 1
                continue
            if got["workload_type"] != base["workload_type"]:
                entry["workload_flips"] += 1
            if set(got["compliance"]) != set(base["compliance"]):
                entry["compliance_drifts"] += 1
            entry["jaccards"].append(
                _jaccard(set(got["components"]), set(base["components"]))
            )
            if got["tf_valid"]:
                entry["tf_valid_count"] += 1

        mode_summary = {}
        for mode, e in per_mode.items():
            jacc = statistics.mean(e["jaccards"]) if e["jaccards"] else 0.0
            mode_summary[mode] = {
                "n": e["n"],
                "workload_flip_rate": round(e["workload_flips"] / max(1, e["n"]), 3),
                "component_jaccard_mean": round(jacc, 3),
                "compliance_drift_rate": round(e["compliance_drifts"] / max(1, e["n"]), 3),
                "tf_valid_rate": round(e["tf_valid_count"] / max(1, e["n"]), 3),
                "crash_rate": round(e["crashed"] / max(1, e["n"]), 3),
            }
        per_case.append({"base_id": bid, "base": base, "modes": mode_summary})

    # Aggregate across all cases, per mode
    agg: Dict[str, dict] = {}
    for row in per_case:
        for mode, m in row.get("modes", {}).items():
            a = agg.setdefault(
                mode,
                {"workload_flip_rate": [], "component_jaccard": [], "compliance_drift": [], "tf_valid": [], "crash": [], "n": 0},
            )
            a["workload_flip_rate"].append(m["workload_flip_rate"])
            a["component_jaccard"].append(m["component_jaccard_mean"])
            a["compliance_drift"].append(m["compliance_drift_rate"])
            a["tf_valid"].append(m["tf_valid_rate"])
            a["crash"].append(m["crash_rate"])
            a["n"] += m["n"]

    overall = {
        mode: {
            "n": a["n"],
            "workload_flip_rate": round(statistics.mean(a["workload_flip_rate"]), 3) if a["workload_flip_rate"] else 0.0,
            "component_jaccard_mean": round(statistics.mean(a["component_jaccard"]), 3) if a["component_jaccard"] else 0.0,
            "compliance_drift_rate": round(statistics.mean(a["compliance_drift"]), 3) if a["compliance_drift"] else 0.0,
            "tf_valid_rate": round(statistics.mean(a["tf_valid"]), 3) if a["tf_valid"] else 0.0,
            "crash_rate": round(statistics.mean(a["crash"]), 3) if a["crash"] else 0.0,
        }
        for mode, a in agg.items()
    }

    # Single-number consistency score for the writeup: averaged across modes,
    # it's (1 - workload_flip) × jaccard × (1 - crash). Higher is better.
    scores = []
    for m in overall.values():
        scores.append(
            (1 - m["workload_flip_rate"]) * m["component_jaccard_mean"] * (1 - m["crash_rate"])
        )
    consistency = round(statistics.mean(scores), 3) if scores else 0.0

    return {"per_case": per_case, "overall": overall, "consistency_score": consistency}


def _write_report(report: dict, llm_available: bool) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "synthetic_stability.json").write_text(
        json.dumps({"llm_available": llm_available, **report}, indent=2),
        encoding="utf-8",
    )

    lines = ["# Synthetic stability report", ""]
    lines.append(f"- Generator: {'Gemini' if llm_available else 'deterministic fallback'}")
    if "consistency_score" in report:
        lines.append(f"- **Consistency score:** {report['consistency_score']} "
                     "(0–1, higher = more robust; combines workload stability, "
                     "component overlap, and crash rate)")
    lines.append("")
    lines.append("## Overall (averaged across reference cases)")
    lines.append("")
    lines.append("| Mode | N | workload_flip | comp_jaccard | compliance_drift | tf_valid | crash |")
    lines.append("|---|---|---|---|---|---|---|")
    for mode, m in report["overall"].items():
        lines.append(
            f"| {mode} | {m['n']} | {m['workload_flip_rate']} | "
            f"{m['component_jaccard_mean']} | {m['compliance_drift_rate']} | "
            f"{m['tf_valid_rate']} | {m['crash_rate']} |"
        )
    (RESULTS_DIR / "synthetic_stability.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5, help="variants per mode per case")
    ap.add_argument("--modes", default=",".join(MODES), help="comma-separated subset of modes")
    ap.add_argument("--generate-only", action="store_true", help="write variants and exit")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--debug", action="store_true", help="print full tracebacks from pipeline failures")
    ap.add_argument("--throttle", type=float, default=0.0, help="seconds to sleep between pipeline calls (dodge Gemini rate limits)")
    args = ap.parse_args()

    global DEBUG, THROTTLE_SEC
    DEBUG = args.debug
    THROTTLE_SEC = args.throttle

    modes = tuple(m.strip() for m in args.modes.split(",") if m.strip() in MODES)
    if not modes:
        ap.error(f"--modes must be a subset of {MODES}")

    variants, llm_ok = generate(n_per_mode=args.n, modes=modes, seed=args.seed)
    print(f"wrote {len(variants)} variants to {OUT_VARIANTS} (llm_available={llm_ok})")

    if args.generate_only:
        return

    report = evaluate(variants)
    _write_report(report, llm_ok)
    print(f"wrote stability report to {RESULTS_DIR / 'synthetic_stability.md'}")
    for mode, m in report["overall"].items():
        print(f"  {mode:12s}  flip={m['workload_flip_rate']:.2f}  jaccard={m['component_jaccard_mean']:.2f}  crash={m['crash_rate']:.2f}")


if __name__ == "__main__":
    main()
