from pipeline.defaults import apply_defaults
from pipeline.schema import ArchSpec


def test_defaults_scale_small_sets_no_ha():
    spec = ArchSpec(raw_prompt="weekend side project")
    out = apply_defaults(spec)
    assert out.scale == "small"
    assert out.ha_required is False


def test_defaults_large_scale_triggers_ha():
    spec = ArchSpec(raw_prompt="enterprise scale platform for millions of users")
    out = apply_defaults(spec)
    assert out.scale == "large"
    assert out.ha_required is True


def test_defaults_detects_async_jobs():
    spec = ArchSpec(raw_prompt="API with a background job queue")
    out = apply_defaults(spec)
    assert out.async_jobs is True


def test_defaults_public_toggle_off_auth():
    spec = ArchSpec(raw_prompt="public read-only API, no auth")
    out = apply_defaults(spec)
    assert out.auth_required is False


def test_defaults_detects_hipaa():
    spec = ArchSpec(raw_prompt="HIPAA telemedicine API")
    out = apply_defaults(spec)
    assert "HIPAA" in out.compliance
