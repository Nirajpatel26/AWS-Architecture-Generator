"""Extractor tests — mock the LLM so we never hit the real API."""
from pipeline import extractor
from pipeline.schema import ArchSpec


def test_empty_llm_response_falls_back_to_defaults(monkeypatch):
    monkeypatch.setattr(extractor, "generate_json", lambda *a, **kw: {})
    spec = extractor.extract("build me a thing")
    assert isinstance(spec, ArchSpec)
    assert spec.raw_prompt == "build me a thing"
    assert spec.workload_type == "web_api"  # schema default


def test_valid_llm_response_populates_fields(monkeypatch):
    fake = {
        "workload_type": "data_pipeline",
        "scale": "medium",
        "compliance": ["HIPAA"],
        "region": "eu-west-1",
        "ha_required": True,
    }
    monkeypatch.setattr(extractor, "generate_json", lambda *a, **kw: fake)
    spec = extractor.extract("batch analytics with phi")
    assert spec.workload_type == "data_pipeline"
    assert spec.scale == "medium"
    assert "HIPAA" in spec.compliance
    assert spec.region == "eu-west-1"
    assert spec.ha_required is True
    assert spec.raw_prompt == "batch analytics with phi"


def test_invalid_enum_falls_back_silently(monkeypatch):
    """If Gemini hallucinates an invalid workload_type, we must not crash."""
    monkeypatch.setattr(
        extractor, "generate_json", lambda *a, **kw: {"workload_type": "kubernetes_cluster"}
    )
    spec = extractor.extract("run my k8s stuff")
    assert isinstance(spec, ArchSpec)
    assert spec.raw_prompt == "run my k8s stuff"


def test_none_values_are_dropped_not_validated(monkeypatch):
    """Gemini sometimes emits explicit null — those should not poison the model."""
    monkeypatch.setattr(
        extractor,
        "generate_json",
        lambda *a, **kw: {"workload_type": "web_api", "scale": None, "region": None},
    )
    spec = extractor.extract("api")
    assert spec.workload_type == "web_api"
    assert spec.scale == "small"
    assert spec.region == "us-east-1"
