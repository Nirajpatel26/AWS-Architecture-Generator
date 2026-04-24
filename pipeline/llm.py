"""Thin Gemini wrapper with structured-JSON output and an offline fallback.

Uses the new `google-genai` SDK (the old `google-generativeai` package is
deprecated and emits a FutureWarning at import time).
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
_API_KEY = os.getenv("GEMINI_API_KEY", "")

_client = None
_types = None
_init_error: Optional[str] = None

# -------------------------------------------------------------------------
# Token usage tracking — lets the orchestrator/eval attribute $ cost per run
# without plumbing it through every call site. Call reset_usage() at the
# start of a request, then get_usage() at the end.
# -------------------------------------------------------------------------
_USAGE_LOG: list[dict] = []

# Gemini 2.0 Flash public pricing as of 2026-04 — USD per 1M tokens.
# Hard-coded on purpose (offline-friendly, deterministic eval $).
GEMINI_PRICE_PER_1M = {
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
}


def reset_usage() -> None:
    _USAGE_LOG.clear()


def get_usage() -> list[dict]:
    return list(_USAGE_LOG)


def estimate_cost_usd(usage_log: list[dict] | None = None) -> float:
    """Sum $ cost across a usage log using GEMINI_PRICE_PER_1M."""
    log = usage_log if usage_log is not None else _USAGE_LOG
    total = 0.0
    for entry in log:
        price = GEMINI_PRICE_PER_1M.get(entry.get("model", ""), {"input": 0.10, "output": 0.40})
        total += entry.get("input_tokens", 0) * price["input"] / 1_000_000
        total += entry.get("output_tokens", 0) * price["output"] / 1_000_000
    return round(total, 6)


def _coerce_int(obj, *names) -> int:
    """Try attribute access then dict access for the first name that returns a value."""
    for name in names:
        # Attribute style (google-genai returns pydantic-like objects).
        v = getattr(obj, name, None)
        if v is None and isinstance(obj, dict):
            v = obj.get(name)
        if v is not None:
            try:
                return int(v)
            except Exception:
                continue
    return 0


def _record_usage(fn: str, resp, prompt_len_chars: int = 0) -> None:
    """Best-effort extraction of token counts from a google-genai response.

    The google-genai SDK returns `resp.usage_metadata` with
    `prompt_token_count` / `candidates_token_count` / `total_token_count`.
    Different SDK versions expose slightly different shapes, so we also try
    a few alternate names. As a last resort (e.g. SDK didn't include usage
    for this call) we back-compute from `total_token_count - input` or a
    ~4 chars/token estimate so downstream cost isn't trivially $0.
    """
    try:
        meta = getattr(resp, "usage_metadata", None) or getattr(resp, "usage", None)
        in_tok = out_tok = total = 0
        if meta is not None:
            in_tok = _coerce_int(meta, "prompt_token_count", "input_tokens", "prompt_tokens")
            out_tok = _coerce_int(
                meta, "candidates_token_count", "output_tokens", "completion_tokens"
            )
            total = _coerce_int(meta, "total_token_count", "total_tokens")

        # If SDK gave us a total but no split, infer output as the remainder.
        if total and not out_tok and in_tok:
            out_tok = max(0, total - in_tok)

        # Fallback: rough ~4 chars/token estimate from prompt + response text.
        if in_tok == 0 and prompt_len_chars > 0:
            in_tok = max(1, prompt_len_chars // 4)
        if out_tok == 0:
            try:
                resp_text = getattr(resp, "text", "") or ""
                if resp_text:
                    out_tok = max(1, len(resp_text) // 4)
            except Exception:
                pass

        _USAGE_LOG.append(
            {
                "fn": fn,
                "model": _MODEL_NAME,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "estimated": meta is None,  # True => numbers are char-based estimate
            }
        )
    except Exception:
        pass


def _get_client():
    global _client, _types, _init_error
    if _client is not None or _init_error is not None:
        return _client
    if not _API_KEY:
        _init_error = "GEMINI_API_KEY not set"
        return None
    try:
        from google import genai
        from google.genai import types as genai_types

        _client = genai.Client(api_key=_API_KEY)
        _types = genai_types
    except Exception as e:  # pragma: no cover - env issue
        _init_error = f"failed to init Gemini: {e}"
        _client = None
    return _client


def is_available() -> bool:
    return _get_client() is not None


def generate_json(
    prompt: str,
    schema: Optional[dict] = None,
    system: str = "",
) -> dict:
    """Call Gemini and parse a JSON object from the response.

    Falls back to an empty dict if Gemini is unreachable; callers layer
    deterministic defaults on top.

    Args:
        prompt: The user-turn content.
        schema: Optional JSON schema for structured output.
        system: Optional system instruction passed via GenerateContentConfig
                (preferred over embedding it in the user prompt).
    """
    client = _get_client()
    if client is None:
        return {}
    cfg_kwargs: dict[str, Any] = {"response_mime_type": "application/json"}
    if schema is not None:
        cfg_kwargs["response_schema"] = schema
    if system:
        cfg_kwargs["system_instruction"] = system
    try:
        config = _types.GenerateContentConfig(**cfg_kwargs)
        resp = client.models.generate_content(
            model=_MODEL_NAME, contents=prompt, config=config
        )
        _record_usage("generate_json", resp, prompt_len_chars=len(prompt) + len(system or ""))
        text = (resp.text or "{}").strip()
        return json.loads(text)
    except Exception:
        return {}


def generate_json_multimodal(
    prompt: str,
    image_bytes: bytes,
    mime_type: str = "image/png",
    schema: Optional[dict] = None,
) -> dict:
    """Call Gemini with a text prompt + a single image, parse JSON from response.

    Used by the vision extractor to turn hand-drawn sketches or AWS console
    screenshots into an ArchSpec. Falls back to {} on any failure.
    """
    client = _get_client()
    if client is None:
        return {}
    cfg_kwargs: dict[str, Any] = {"response_mime_type": "application/json"}
    if schema is not None:
        cfg_kwargs["response_schema"] = schema
    try:
        config = _types.GenerateContentConfig(**cfg_kwargs)
        image_part = _types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        resp = client.models.generate_content(
            model=_MODEL_NAME, contents=[prompt, image_part], config=config
        )
        _record_usage("generate_json_multimodal", resp, prompt_len_chars=len(prompt))
        text = (resp.text or "{}").strip()
        return json.loads(text)
    except Exception:
        return {}


def generate_text(prompt: str) -> str:
    client = _get_client()
    if client is None:
        return ""
    try:
        resp = client.models.generate_content(model=_MODEL_NAME, contents=prompt)
        _record_usage("generate_text", resp, prompt_len_chars=len(prompt))
        return resp.text or ""
    except Exception:
        return ""
