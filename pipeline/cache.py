"""SQLite-backed prompt → ArchSpec cache.

Motivation: extraction is the single most expensive stage (Gemini call with
self-consistency voting, ~3x API calls). For repeat demos and dev iteration
the prompt is deterministic enough that caching gives ~80% latency/cost cut.

Cache key = sha256(prompt + extractor_prompt_version + model_name) so prompt
version bumps invalidate automatically.

Disable with env `CLOUDARCH_CACHE_DISABLED=1` (eval/ablation.py sets this to
measure the uncached baseline).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .schema import ArchSpec

_DB_PATH = Path(__file__).resolve().parent.parent / ".cache" / "prompt_cache.sqlite"


def _disabled() -> bool:
    return os.getenv("CLOUDARCH_CACHE_DISABLED") == "1"


def _conn() -> Optional[sqlite3.Connection]:
    if _disabled():
        return None
    try:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(_DB_PATH))
        c.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            "prompt_hash TEXT PRIMARY KEY, "
            "spec_json TEXT NOT NULL, "
            "created_at REAL NOT NULL, "
            "model TEXT)"
        )
        return c
    except Exception:
        return None


def _key(prompt: str, version: str, model: str) -> str:
    h = hashlib.sha256()
    h.update(prompt.encode("utf-8"))
    h.update(b"|")
    h.update(version.encode("utf-8"))
    h.update(b"|")
    h.update(model.encode("utf-8"))
    return h.hexdigest()


def get(prompt: str, version: str, model: str) -> Optional[ArchSpec]:
    c = _conn()
    if c is None:
        return None
    try:
        row = c.execute(
            "SELECT spec_json FROM cache WHERE prompt_hash = ?",
            (_key(prompt, version, model),),
        ).fetchone()
        c.close()
        if not row:
            return None
        data = json.loads(row[0])
        return ArchSpec(**{k: v for k, v in data.items() if v is not None})
    except Exception:
        return None


def put(prompt: str, version: str, model: str, spec: ArchSpec) -> None:
    c = _conn()
    if c is None:
        return
    try:
        c.execute(
            "INSERT OR REPLACE INTO cache (prompt_hash, spec_json, created_at, model) "
            "VALUES (?, ?, ?, ?)",
            (
                _key(prompt, version, model),
                json.dumps(spec.to_dict()),
                time.time(),
                model,
            ),
        )
        c.commit()
        c.close()
    except Exception:
        pass
