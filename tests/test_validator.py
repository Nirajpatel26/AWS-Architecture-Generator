from pipeline import validator


def test_missing_terraform_returns_skipped(monkeypatch):
    monkeypatch.setattr(validator, "_have", lambda b: False)
    res = validator.validate("provider \"aws\" {}")
    assert res.ok is True
    assert res.attempts == 0
    assert res.skipped_reason and "terraform" in res.skipped_reason.lower()


def test_fix_with_llm_strips_code_fences(monkeypatch):
    fenced = "```hcl\nresource \"aws_s3_bucket\" \"b\" {}\n```"
    monkeypatch.setattr(validator, "generate_text", lambda *a, **kw: fenced)
    out = validator._fix_with_llm("broken", "some error")
    assert "```" not in out
    assert "aws_s3_bucket" in out


def test_fix_with_llm_empty_response_returns_original(monkeypatch):
    monkeypatch.setattr(validator, "generate_text", lambda *a, **kw: "")
    original = "resource \"aws_s3_bucket\" \"b\" {}"
    out = validator._fix_with_llm(original, "err")
    assert out == original


def test_validation_result_defaults():
    r = validator.ValidationResult(ok=True, attempts=1, tf_code="foo")
    assert r.tfsec_high == 0
    assert r.errors == []
    assert r.skipped_reason is None
