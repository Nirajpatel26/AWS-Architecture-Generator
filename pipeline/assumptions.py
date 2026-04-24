"""Stage 3: format assumptions for the user review panel."""
from __future__ import annotations

from typing import List

from .schema import ArchSpec


def render_markdown(spec: ArchSpec) -> str:
    if not spec.assumptions:
        return "_No assumptions — all fields explicitly provided._"
    lines = ["The system made the following assumptions — edit the spec if any are wrong:\n"]
    for a in spec.assumptions:
        lines.append(f"- {a}")
    return "\n".join(lines)


def confirmed(spec: ArchSpec, overrides: dict) -> ArchSpec:
    """Apply user overrides (from the Streamlit review panel) onto the spec."""
    for k, v in overrides.items():
        if hasattr(spec, k) and v is not None:
            setattr(spec, k, v)
    return spec
