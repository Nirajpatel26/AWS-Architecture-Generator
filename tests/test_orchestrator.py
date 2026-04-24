from pipeline import orchestrator
from pipeline.validator import ValidationResult


def test_end_to_end_smoke(monkeypatch):
    # Stub LLM and terraform validation — we're testing pipeline wiring,
    # not the external binaries or the Gemini API.
    from pipeline import llm, validator

    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: {})
    monkeypatch.setattr(llm, "generate_text", lambda *a, **k: "")
    monkeypatch.setattr(
        validator,
        "validate",
        lambda tf, **k: ValidationResult(
            ok=True, attempts=0, tf_code=tf, skipped_reason="stubbed"
        ),
    )

    result = orchestrator.run("HIPAA telemedicine API, 10k users/day, multi-AZ")
    assert result.tf_code
    assert result.template["resources"]
    assert "HIPAA" in result.spec.compliance
    assert result.monthly_cost > 0
    # Observability: per-stage timings captured; tokens list present (empty
    # since we stubbed llm). cost_meta populated from pricing module.
    assert "tf_generator" in result.stage_timings
    assert "validator" in result.stage_timings
    assert isinstance(result.token_usage, list)
    assert result.cost_meta.get("updated")


def test_streaming_yields_in_order(monkeypatch):
    from pipeline import llm, validator

    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: {})
    monkeypatch.setattr(llm, "generate_text", lambda *a, **k: "")
    monkeypatch.setattr(
        validator,
        "validate",
        lambda tf, **k: ValidationResult(ok=True, attempts=0, tf_code=tf, skipped_reason="stubbed"),
    )

    events = list(orchestrator.run_streaming("simple web API"))
    kinds = [e[0] for e in events]
    assert kinds[0] == "stage_started"
    assert kinds[-1] == "result"
    # Every stage_done must be preceded by a matching stage_started.
    started = [e[1] for e in events if e[0] == "stage_started"]
    done = [e[1] for e in events if e[0] == "stage_done"]
    for name in done:
        assert name in started
