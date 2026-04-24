from pipeline import assumptions
from pipeline.schema import ArchSpec


def test_render_empty_returns_marker():
    spec = ArchSpec()
    md = assumptions.render_markdown(spec)
    assert "No assumptions" in md


def test_render_lists_each_assumption():
    spec = ArchSpec()
    spec.assumptions = ["encrypted at rest", "multi-AZ RDS"]
    md = assumptions.render_markdown(spec)
    assert "- encrypted at rest" in md
    assert "- multi-AZ RDS" in md


def test_confirmed_applies_valid_overrides():
    spec = ArchSpec()
    out = assumptions.confirmed(spec, {"scale": "large", "region": "eu-west-1"})
    assert out.scale == "large"
    assert out.region == "eu-west-1"


def test_confirmed_ignores_none_and_unknown_keys():
    spec = ArchSpec(scale="medium")
    out = assumptions.confirmed(spec, {"scale": None, "bogus_field": "xyz"})
    assert out.scale == "medium"  # None must not overwrite
    assert not hasattr(out, "bogus_field")
