"""Structured JSON run logging.

Emits one line per stage_complete + one line per run to `.cache/runs.jsonl`.
This is a lightweight alternative to LangFuse / LangSmith — the file can be
tailed with `jq` or piped into any log collector. Keeps the project
offline-friendly (no network deps) while satisfying the "structured logging /
observability" product-grade checkbox.

Named `run_log` (not `logging`) to avoid shadowing the stdlib `logging` module
when this package is imported from stage modules.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_LOG_DIR = Path(__file__).resolve().parent.parent / ".cache"
_LOG_FILE = _LOG_DIR / "runs.jsonl"

_DISABLED = os.getenv("CLOUDARCH_LOG_DISABLED") == "1"


def _writable() -> bool:
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False


def _append(record: dict) -> None:
    if _DISABLED or not _writable():
        return
    try:
        with _LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass


def log_stage(stage: str, elapsed_seconds: float) -> None:
    _append(
        {
            "event": "stage_complete",
            "stage": stage,
            "elapsed_seconds": round(elapsed_seconds, 4),
            "ts": time.time(),
        }
    )


def log_run(prompt: str, result: Any) -> None:
    try:
        rec = {
            "event": "run_complete",
            "ts": time.time(),
            "prompt": prompt[:500],
            "workload_type": getattr(result.spec, "workload_type", None),
            "tf_valid": result.tf_valid,
            "tf_attempts": result.tf_attempts,
            "tfsec_high": result.tfsec_high,
            "monthly_cost": result.monthly_cost,
            "stage_timings": result.stage_timings,
            "total_input_tokens": result.total_input_tokens,
            "total_output_tokens": result.total_output_tokens,
            "estimated_cost_usd": result.estimated_cost_usd,
        }
        _append(rec)
    except Exception:
        pass
