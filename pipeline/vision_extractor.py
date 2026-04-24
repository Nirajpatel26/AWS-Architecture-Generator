"""Stage 1 (multimodal): image -> structured ArchSpec via Gemini Vision.

Companion to `extractor.py`. Accepts a user-uploaded image (hand-drawn
architecture sketch, AWS console screenshot, slide-deck diagram) plus an
optional text caption, and returns the same `ArchSpec` that the text
extractor produces — so every downstream stage (defaults -> template ->
TF emit -> validator -> diagram -> cost -> explainer) runs unchanged.

Same fail-silent contract as `pipeline/llm.py`: on missing API key, parse
failure, or any Gemini error, returns an empty `ArchSpec` and lets
deterministic defaults take over.
"""
from __future__ import annotations

from typing import Optional

from .llm import generate_json_multimodal
from .prompts import load
from .prompts.allowlist import format_allowlist
from .schema import ArchSpec, GEMINI_JSON_SCHEMA

VISION_PROMPT_VERSION = "v1"

_MIME_BY_EXT = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


def detect_mime(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _MIME_BY_EXT.get(ext, "image/png")


def _build_prompt(caption: str) -> str:
    system = load(f"vision_extractor.system.{VISION_PROMPT_VERSION}").format(
        allowlist=format_allowlist()
    )
    user_tpl = load(f"vision_extractor.user.{VISION_PROMPT_VERSION}")
    return user_tpl.format(system=system, caption=caption or "")


def extract_from_image(
    image_bytes: bytes,
    mime_type: str = "image/png",
    caption: str = "",
) -> ArchSpec:
    """Run Gemini Vision on the image + optional caption, return an ArchSpec."""
    prompt = _build_prompt(caption)
    data = generate_json_multimodal(
        prompt,
        image_bytes=image_bytes,
        mime_type=mime_type,
        schema=GEMINI_JSON_SCHEMA,
    ) or {}

    raw = data.get("raw_prompt") or caption or "(image upload; no caption)"
    data.setdefault("raw_prompt", raw)
    try:
        spec = ArchSpec(**{k: v for k, v in data.items() if v is not None})
    except Exception:
        spec = ArchSpec(raw_prompt=raw)

    note = "Spec extracted from uploaded image via Gemini Vision."
    if caption:
        note += f" User caption: {caption!r}."
    if note not in spec.assumptions:
        spec.assumptions.insert(0, note)
    return spec
