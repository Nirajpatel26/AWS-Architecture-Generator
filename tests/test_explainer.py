"""Explainer tests — LLM mocked out; we verify the deterministic fallback."""
from pipeline import explainer
from pipeline.schema import ArchSpec


def _tpl():
    return {
        "name": "web_api",
        "resources": [
            {"type": "aws_lambda_function", "name": "handler", "args": {}},
            {"type": "aws_dynamodb_table", "name": "data", "args": {}},
        ],
    }


def test_fallback_used_when_llm_returns_empty(monkeypatch):
    monkeypatch.setattr(explainer, "generate_text", lambda *a, **kw: "")
    spec = ArchSpec(workload_type="web_api", project_name="demo", compliance=["HIPAA"])
    out = explainer.explain(spec, _tpl())
    assert "demo" in out
    assert "HIPAA" in out
    assert "aws_lambda_function.handler" in out


def test_llm_response_passed_through(monkeypatch):
    monkeypatch.setattr(explainer, "generate_text", lambda *a, **kw: "## Real explanation [1]")
    spec = ArchSpec(project_name="demo")
    out = explainer.explain(spec, _tpl())
    assert out == "## Real explanation [1]"


def test_fallback_includes_retrieved_references(monkeypatch):
    monkeypatch.setattr(explainer, "generate_text", lambda *a, **kw: "")
    retrieved = [
        {"source": "hipaa.md", "snippet": "PHI must be encrypted at rest and in transit."}
    ]
    spec = ArchSpec(project_name="demo")
    out = explainer.explain(spec, _tpl(), retrieved=retrieved)
    assert "References" in out
    assert "hipaa.md" in out


def test_whitespace_only_response_triggers_fallback(monkeypatch):
    monkeypatch.setattr(explainer, "generate_text", lambda *a, **kw: "   \n\t  ")
    spec = ArchSpec(project_name="demo")
    out = explainer.explain(spec, _tpl())
    assert "Design rationale" in out
