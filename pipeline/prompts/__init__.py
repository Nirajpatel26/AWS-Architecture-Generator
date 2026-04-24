"""Versioned prompt loader.

All LLM prompts live as `*.txt` / `*.json` files in this directory with a
`.vN` version tag baked into the filename (e.g. `extractor.system.v2.txt`).
Callers pin a specific version:

    from pipeline.prompts import load, load_json
    system = load("extractor.system.v2")
    fewshot = load_json("extractor.fewshot.v1")

This keeps prompt content out of Python source (easier to diff, easier to
A/B) and lets RunResult record which prompt versions produced a given run.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent


def _resolve(name: str, suffix: str) -> Path:
    path = _DIR / f"{name}{suffix}"
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {path}")
    return path


@lru_cache(maxsize=None)
def load(name: str) -> str:
    """Load a text prompt by versioned name (without extension)."""
    return _resolve(name, ".txt").read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def load_json(name: str):
    """Load a JSON prompt artifact (e.g. few-shot examples) by versioned name."""
    return json.loads(_resolve(name, ".json").read_text(encoding="utf-8"))
