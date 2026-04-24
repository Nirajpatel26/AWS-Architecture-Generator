"""Prompt cache smoke tests — hit/miss/invalidation."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

from pipeline import cache
from pipeline.schema import ArchSpec


def _with_tmp_db():
    """Redirect the cache DB to a tempfile for this test."""
    tmp = tempfile.mkdtemp()
    return mock.patch.object(cache, "_DB_PATH", Path(tmp) / "prompt_cache.sqlite")


def test_miss_then_hit():
    with _with_tmp_db():
        spec = ArchSpec(raw_prompt="test", workload_type="web_api")
        assert cache.get("hello world", "v1", "gemini-2.0-flash") is None
        cache.put("hello world", "v1", "gemini-2.0-flash", spec)
        got = cache.get("hello world", "v1", "gemini-2.0-flash")
        assert got is not None
        assert got.workload_type == "web_api"


def test_version_bump_invalidates():
    with _with_tmp_db():
        spec = ArchSpec(raw_prompt="test", workload_type="web_api")
        cache.put("hello", "v1", "gemini-2.0-flash", spec)
        # Different version => cache miss.
        assert cache.get("hello", "v2", "gemini-2.0-flash") is None
        # Different model => cache miss.
        assert cache.get("hello", "v1", "gemini-1.5-pro") is None


def test_disabled_env_short_circuits():
    with _with_tmp_db():
        os.environ["CLOUDARCH_CACHE_DISABLED"] = "1"
        try:
            spec = ArchSpec(raw_prompt="test")
            cache.put("x", "v1", "m", spec)  # no-op
            assert cache.get("x", "v1", "m") is None
        finally:
            os.environ.pop("CLOUDARCH_CACHE_DISABLED", None)
