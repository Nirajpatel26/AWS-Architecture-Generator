"""LLM-as-judge offline-fallback test."""
from __future__ import annotations

from unittest import mock

from eval import judge


def test_empty_explanation_returns_empty():
    assert judge.judge_explanation("prompt", "", []) == {}


def test_gemini_unavailable_returns_empty():
    with mock.patch.object(judge, "generate_json", return_value={}):
        out = judge.judge_explanation("prompt", "some rationale", [])
        assert out == {}


def test_gemini_returns_scores():
    fake = {"faithfulness": 4, "completeness": 3, "citations_valid": True, "rationale": "ok"}
    with mock.patch.object(judge, "generate_json", return_value=fake):
        out = judge.judge_explanation("prompt", "some rationale", [])
        assert out["faithfulness"] == 4
        assert out["citations_valid"] is True
