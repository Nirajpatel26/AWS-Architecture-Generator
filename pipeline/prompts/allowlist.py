"""Deterministic AWS resource allowlist derived from templates + patches.

Scanned at import time so the extractor's guardrail prompt stays in lockstep
with the actual resource types the deterministic pipeline can emit.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import List

_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATES = _ROOT / "templates"
_PATCHES = _ROOT / "patches"


def _collect_types_from_template(doc: dict) -> List[str]:
    out = []
    for r in doc.get("resources", []) or []:
        t = r.get("type")
        if t:
            out.append(t)
    return out


def _collect_types_from_patch(doc: dict) -> List[str]:
    out = []
    for r in doc.get("add_resources", []) or []:
        t = r.get("type")
        if t:
            out.append(t)
    for m in doc.get("mutate_resources", []) or []:
        match = (m.get("match") or {}).get("type")
        if match:
            out.append(match)
        sib = m.get("add_sibling") or {}
        t = sib.get("type")
        if t:
            out.append(t)
    return out


@lru_cache(maxsize=1)
def get_allowed_types() -> List[str]:
    seen = []
    for p in sorted(_TEMPLATES.glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for t in _collect_types_from_template(doc):
            if t not in seen:
                seen.append(t)
    for p in sorted(_PATCHES.glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for t in _collect_types_from_patch(doc):
            if t not in seen:
                seen.append(t)
    return seen


def format_allowlist() -> str:
    return ", ".join(get_allowed_types())
