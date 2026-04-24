from pipeline import cost, template_engine
from pipeline.schema import ArchSpec


def test_cost_non_negative():
    spec = ArchSpec(workload_type="web_api")
    tpl = template_engine.assemble(spec)
    total, items = cost.estimate(tpl)
    assert total >= 0
    assert items


def test_cost_scales_with_scale():
    spec = ArchSpec(workload_type="web_api")
    tpl = template_engine.assemble(spec)
    small, _ = cost.estimate(tpl, scale="small")
    large, _ = cost.estimate(tpl, scale="large")
    assert large > small


def test_hipaa_costs_more_than_base():
    base_tpl = template_engine.assemble(ArchSpec(workload_type="web_api"))
    hipaa_tpl = template_engine.assemble(
        ArchSpec(workload_type="web_api", compliance=["HIPAA"])
    )
    base_total, _ = cost.estimate(base_tpl)
    hipaa_total, _ = cost.estimate(hipaa_tpl)
    assert hipaa_total > base_total


def test_lambda_has_nonzero_cost_from_usage():
    """Regression: Lambda used to be $0/mo. Now its per-request charge must apply."""
    tpl = template_engine.assemble(ArchSpec(workload_type="web_api"))
    _, items = cost.estimate(tpl, scale="small")
    lambdas = [i for i in items if i["service"] == "lambda_function"]
    assert lambdas, "web_api should contain a lambda"
    assert lambdas[0]["monthly_usd"] > 0


def test_cognito_charges_kick_in_only_above_free_tier():
    tpl = template_engine.assemble(ArchSpec(workload_type="web_api", auth_required=True))
    _, small = cost.estimate(tpl, scale="small")
    _, large = cost.estimate(tpl, scale="large")
    small_cog = next((i for i in small if i["service"] == "cognito_user_pool"), None)
    large_cog = next((i for i in large if i["service"] == "cognito_user_pool"), None)
    assert small_cog and small_cog["monthly_usd"] == 0  # under 50k free tier
    assert large_cog and large_cog["monthly_usd"] > 0   # above free tier


def test_missing_pricing_entry_is_surfaced():
    fake_tpl = {"resources": [{"type": "aws_quantum_wormhole", "name": "x", "args": {}}]}
    total, items = cost.estimate(fake_tpl)
    assert total == 0.0
    assert items[0].get("note") == "no pricing entry"
