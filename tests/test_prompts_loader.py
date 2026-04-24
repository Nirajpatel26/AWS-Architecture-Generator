"""Prompt loader tests."""
import pytest

from pipeline.prompts import load, load_json


def test_load_extractor_system_v2():
    text = load("extractor.system.v2")
    assert "NEVER" in text
    assert "{allowlist}" in text


def test_load_fewshot_v1_is_list():
    data = load_json("extractor.fewshot.v1")
    assert isinstance(data, list)
    assert len(data) >= 3
    for ex in data:
        assert "input" in ex
        assert "output" in ex
        assert "workload_type" in ex["output"]


def test_missing_prompt_raises():
    with pytest.raises(FileNotFoundError):
        load("does_not_exist.v99")


def test_load_is_cached():
    first = load("extractor.user.v2")
    second = load("extractor.user.v2")
    assert first is second  # lru_cache returns the same string object
