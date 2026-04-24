"""Stage 0: prompt normalization.

Cleans noisy / multilingual / adversarial prompts into canonical English so
the downstream extractor produces stable output across variants of the same
underlying intent. This is the main lever for synthetic-stability robustness:
when every variant collapses to the same canonical form, the extracted spec
(and therefore the template, resources, and cost) becomes a function of
intent rather than phrasing.

LLM-backed when Gemini is reachable; falls back to a deterministic regex
cleaner so the pipeline never crashes on an unreachable API.
"""
from __future__ import annotations

import os
import re
from typing import Optional

from . import llm

_NORMALIZE_PROMPT = """You are a prompt-normalization assistant for a cloud-architecture
extractor. Rewrite the user's description into a single concise English
sentence that preserves ALL technical signals:

  - workload type (API, web app, data pipeline, ML training, static site)
  - compliance requirements (HIPAA, PCI, SOC2)
  - scale (user counts, traffic volume, "small/medium/large")
  - HA / multi-region / multi-AZ hints
  - data store (SQL, NoSQL, S3/object)
  - async / batch / streaming hints

Rules:
  - Translate non-English text to English.
  - Fix typos and acronyms (e.g. "HIPPA" -> "HIPAA", "PCI-DSS" -> "PCI",
    "SOC 2" -> "SOC2", "multy-az" -> "multi-AZ").
  - Strip filler ("so basically", "like", "you know", "lowkey", "tbh"),
    slang, ALL-CAPS shouting, off-topic content (weather, recipes, etc.).
  - Resolve contradictions in favor of the more specific signal
    (e.g. if text mentions PHI but also "no compliance needed", keep HIPAA).
  - Do NOT invent new constraints.
  - Output 1-2 short sentences in plain technical English.

Return strict JSON: {{"normalized": "..."}} — a single string, no commentary.

Input: "{prompt}"
"""


# Deterministic fallback — handles the common noise patterns the synthetic
# eval generates (typos, chat-speak, shouting). Not exhaustive; meant to be
# a safety net when the LLM is unavailable.
_TYPO_FIXES = [
    (r"\bhipp?aa?\b", "HIPAA"),
    (r"\bhipa\b", "HIPAA"),
    (r"\bpci[- ]?dss\b", "PCI"),
    (r"\bsoc[- ]?2\b", "SOC2"),
    (r"\bmulty[- ]?az\b", "multi-AZ"),
    (r"\bmulit[- ]?az\b", "multi-AZ"),
    (r"\bmulti[- ]?zone\b", "multi-AZ"),
    (r"\bhi[- ]?availability\b", "highly available"),
    (r"\bcomply?nt\b", "compliant"),
    (r"\bcomplient\b", "compliant"),
    (r"\btelemed\b", "telemedicine"),
    (r"\bendpoint\b", "API"),
    (r"\bdatastore\b", "database"),
    (r"\bDB\b", "database"),
]

_FILLER_PATTERNS = [
    r"\bso basically\b",
    r"\bbasically\b",
    r"\blike,? \b",
    r"\byou know\b",
    r"\blowkey\b",
    r"\btbh\b",
    r"\bumm+\b",
    r"\buhh+\b",
    r"\bgimme\b",
    r"\bkinda\b",
    r"\bsorta\b",
    r"\bplz\b",
    r"\bk?thx\b",
    r"\bnvm\b",
    r"\bidk\b",
]


def _deterministic_clean(prompt: str) -> str:
    p = prompt
    # Normalize to lowercase for matching, but preserve structure.
    lower = p.lower()
    for pat, rep in _TYPO_FIXES:
        lower = re.sub(pat, rep.lower(), lower, flags=re.IGNORECASE)
    for pat in _FILLER_PATTERNS:
        lower = re.sub(pat, " ", lower, flags=re.IGNORECASE)
    # Collapse punctuation runs and whitespace.
    lower = re.sub(r"[!?]{2,}", ".", lower)
    lower = re.sub(r"\s+", " ", lower).strip()
    # Restore canonical casing for known acronyms.
    for acronym in ("HIPAA", "PCI", "SOC2", "AWS", "API", "CDN", "SaaS"):
        lower = re.sub(
            rf"\b{acronym.lower()}\b", acronym, lower, flags=re.IGNORECASE
        )
    return lower or prompt


def normalize(prompt: str) -> str:
    """Return a canonical English rewrite of `prompt`.

    Guaranteed non-empty: on any failure returns a regex-cleaned version of
    the original, or the original itself if cleaning yielded empty text.
    Disable via `CLOUDARCH_NORMALIZE_DISABLED=1` for A/B testing.
    """
    if not prompt or not prompt.strip():
        return prompt
    if os.getenv("CLOUDARCH_NORMALIZE_DISABLED") == "1":
        return prompt

    if llm.is_available():
        try:
            data = llm.generate_json(_NORMALIZE_PROMPT.format(prompt=prompt))
            if isinstance(data, dict):
                out: Optional[str] = data.get("normalized")
                if isinstance(out, str) and out.strip():
                    return out.strip()
        except Exception:
            pass
    return _deterministic_clean(prompt)
