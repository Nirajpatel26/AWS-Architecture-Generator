"""Self-consistency voting tests."""
from pipeline.voting import vote_specs


def test_empty_samples_return_empty():
    assert vote_specs([]) == {}
    assert vote_specs([{}, {}, {}]) == {}


def test_majority_workload_type():
    samples = [
        {"workload_type": "web_api"},
        {"workload_type": "web_api"},
        {"workload_type": "data_pipeline"},
    ]
    assert vote_specs(samples)["workload_type"] == "web_api"


def test_workload_type_tie_picks_first_seen_and_notes():
    samples = [
        {"workload_type": "data_pipeline"},
        {"workload_type": "web_api"},
    ]
    out = vote_specs(samples)
    assert out["workload_type"] == "data_pipeline"
    # tie should produce an assumption note
    notes = out.get("_assumptions", [])
    assert any("tie" in n.lower() for n in notes)


def test_compliance_element_majority():
    samples = [
        {"compliance": ["HIPAA", "SOC2"]},
        {"compliance": ["HIPAA"]},
        {"compliance": []},
    ]
    # HIPAA in 2/3 -> kept; SOC2 in 1/3 -> dropped
    assert vote_specs(samples)["compliance"] == ["HIPAA"]


def test_bool_majority():
    samples = [
        {"ha_required": True, "async_jobs": False},
        {"ha_required": True, "async_jobs": True},
        {"ha_required": False, "async_jobs": False},
    ]
    out = vote_specs(samples)
    assert out["ha_required"] is True
    assert out["async_jobs"] is False


def test_scale_conservative_tie_break():
    # 1 small, 1 large -> tie, conservative pick is "small"
    samples = [{"scale": "small"}, {"scale": "large"}]
    assert vote_specs(samples)["scale"] == "small"


def test_budget_conservative_tie_break():
    samples = [{"budget_tier": "performance"}, {"budget_tier": "minimal"}]
    assert vote_specs(samples)["budget_tier"] == "minimal"


def test_free_text_first_nonempty():
    samples = [
        {"region": ""},
        {"region": None},
        {"region": "eu-west-1"},
    ]
    assert vote_specs(samples)["region"] == "eu-west-1"


def test_assumptions_union_preserved():
    samples = [
        {"_assumptions": ["alpha", "beta"]},
        {"_assumptions": ["beta", "gamma"]},
        {"assumptions": ["delta"]},
    ]
    out = vote_specs(samples)["_assumptions"]
    assert out == ["alpha", "beta", "gamma", "delta"]


def test_none_values_ignored():
    samples = [
        {"workload_type": "web_api", "scale": None},
        {"workload_type": "web_api", "scale": "medium"},
        {"workload_type": "web_api", "scale": None},
    ]
    out = vote_specs(samples)
    assert out["workload_type"] == "web_api"
    assert out["scale"] == "medium"
