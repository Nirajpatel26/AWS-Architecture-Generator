"""Self-consistency voting over multiple extractor samples.

Extraction is stochastic: Gemini can swing workload classification or
compliance inference across reruns of the same prompt. We sample N times
and merge the samples with per-field voting rules tuned for this schema.

Rules (see plan):
- workload_type: majority; ties -> first sample's value
- compliance: element-wise majority (include a regime if it appears in >= ceil(N/2))
- booleans (ha_required, multi_region, async_jobs, auth_required): majority
- scale, budget_tier: majority, ties -> conservative pick
- free-text (region, project_name, data_store): first non-empty
- _assumptions / assumptions: union (deduped, order preserved)
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

_BOOL_FIELDS = ("ha_required", "multi_region", "async_jobs", "auth_required")
_FREE_TEXT_FIELDS = ("region", "project_name", "data_store", "raw_prompt")

# Lower index = more conservative; used to break ties on ordinal enums.
_SCALE_ORDER = ["small", "medium", "large"]
_BUDGET_ORDER = ["minimal", "balanced", "performance"]


def _majority(values: List[Any], tie_break=None) -> Any:
    """Return the most common non-None value. tie_break(candidates) breaks ties."""
    cleaned = [v for v in values if v is not None]
    if not cleaned:
        return None
    counts = Counter(cleaned)
    top = counts.most_common()
    best_count = top[0][1]
    candidates = [v for v, c in top if c == best_count]
    if len(candidates) == 1 or tie_break is None:
        return candidates[0]
    return tie_break(candidates)


def _conservative(order: List[str]):
    def _pick(candidates: List[str]) -> str:
        ranked = [c for c in order if c in candidates]
        return ranked[0] if ranked else candidates[0]
    return _pick


def _first_nonempty(values: List[Any]) -> Any:
    for v in values:
        if v not in (None, "", [], {}):
            return v
    return None


def _union_preserve_order(lists: List[List[str]]) -> List[str]:
    seen = []
    for lst in lists:
        if not lst:
            continue
        for item in lst:
            if item and item not in seen:
                seen.append(item)
    return seen


def _element_majority(lists: List[List[str]], n_samples: int) -> List[str]:
    """Include an element if it appears in >= ceil(n/2) sample lists."""
    threshold = (n_samples + 1) // 2
    counts: Counter = Counter()
    order: List[str] = []
    for lst in lists:
        if not lst:
            continue
        for item in set(lst):
            if item not in order:
                order.append(item)
            counts[item] += 1
    return [item for item in order if counts[item] >= threshold]


def vote_specs(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge N extractor samples into a single dict suitable for ArchSpec(**...).

    Empty samples are allowed; if every sample is empty the result is empty.
    """
    samples = [s or {} for s in samples]
    n = len(samples)
    if n == 0:
        return {}

    result: Dict[str, Any] = {}
    tie_note = None

    # workload_type — majority, ties go to first sample
    wt_values = [s.get("workload_type") for s in samples]
    cleaned_wt = [v for v in wt_values if v]
    if cleaned_wt:
        counts = Counter(cleaned_wt)
        top = counts.most_common()
        best = top[0][1]
        winners = [v for v, c in top if c == best]
        if len(winners) > 1:
            # tie: prefer the value that appeared first in sample order
            for v in cleaned_wt:
                if v in winners:
                    result["workload_type"] = v
                    break
            tie_note = (
                f"Extractor voting tie on workload_type across {n} samples "
                f"(candidates: {sorted(winners)}); kept first seen."
            )
        else:
            result["workload_type"] = winners[0]

    # compliance — element-wise majority
    compliance_lists = [s.get("compliance") or [] for s in samples]
    if any(compliance_lists):
        result["compliance"] = _element_majority(compliance_lists, n)

    # booleans — majority (ties default True if ha/auth-related? No: just first-seen)
    for field in _BOOL_FIELDS:
        vals = [s.get(field) for s in samples]
        voted = _majority(vals)
        if voted is not None:
            result[field] = voted

    # scale / budget_tier — majority with conservative tie-break
    for field, order in (("scale", _SCALE_ORDER), ("budget_tier", _BUDGET_ORDER)):
        vals = [s.get(field) for s in samples]
        voted = _majority(vals, tie_break=_conservative(order))
        if voted is not None:
            result[field] = voted

    # free-text fields — first non-empty
    for field in _FREE_TEXT_FIELDS:
        val = _first_nonempty([s.get(field) for s in samples])
        if val is not None:
            result[field] = val

    # assumptions — union. Both alias names can appear; merge both.
    all_assumption_lists = [
        s.get("_assumptions") or s.get("assumptions") or [] for s in samples
    ]
    merged = _union_preserve_order(all_assumption_lists)
    if tie_note:
        merged.append(tie_note)
    if merged:
        result["_assumptions"] = merged

    return result
