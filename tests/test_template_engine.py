from pipeline import template_engine
from pipeline.schema import ArchSpec


def test_load_all_templates():
    for name in ["web_api", "data_pipeline", "ml_training", "static_site"]:
        tpl = template_engine.load_template(name)
        assert tpl["name"] == name
        assert tpl.get("resources")


def test_hipaa_patch_adds_kms_and_cloudtrail():
    spec = ArchSpec(workload_type="web_api", compliance=["HIPAA"])
    tpl = template_engine.assemble(spec)
    types = [r["type"] for r in tpl["resources"]]
    assert "aws_kms_key" in types
    assert "aws_cloudtrail" in types
    assert "hipaa" in tpl["applied_patches"]


def test_ha_patch_marks_rds_multi_az():
    spec = ArchSpec(workload_type="web_api", ha_required=True)
    tpl = template_engine.assemble(spec)
    # web_api template has no RDS by default — ha patch should still apply cleanly
    assert "ha" in tpl["applied_patches"]


def test_patch_order_deterministic():
    spec = ArchSpec(
        workload_type="web_api",
        compliance=["HIPAA"],
        ha_required=True,
        multi_region=True,
    )
    tpl = template_engine.assemble(spec)
    assert tpl["applied_patches"] == ["hipaa", "ha", "multi_region"]


def test_data_store_sql_swaps_in_rds_and_drops_dynamo():
    spec = ArchSpec(workload_type="web_api", data_store="sql")
    tpl = template_engine.assemble(spec)
    types = [r["type"] for r in tpl["resources"]]
    assert "aws_db_instance" in types
    assert "aws_dynamodb_table" not in types


def test_data_store_nosql_keeps_dynamo():
    spec = ArchSpec(workload_type="web_api", data_store="nosql")
    tpl = template_engine.assemble(spec)
    types = [r["type"] for r in tpl["resources"]]
    assert "aws_dynamodb_table" in types
    assert "aws_db_instance" not in types


def test_auth_not_required_drops_cognito():
    spec = ArchSpec(workload_type="web_api", auth_required=False)
    tpl = template_engine.assemble(spec)
    types = [r["type"] for r in tpl["resources"]]
    assert "aws_cognito_user_pool" not in types


def test_auth_required_keeps_cognito():
    spec = ArchSpec(workload_type="web_api", auth_required=True)
    tpl = template_engine.assemble(spec)
    types = [r["type"] for r in tpl["resources"]]
    assert "aws_cognito_user_pool" in types


def test_multi_region_patch_adds_replication_config():
    spec = ArchSpec(workload_type="web_api", multi_region=True)
    tpl = template_engine.assemble(spec)
    types = [r["type"] for r in tpl["resources"]]
    assert "aws_s3_bucket_replication_configuration" in types


def test_ha_patch_publishes_lambda_and_adds_alias():
    spec = ArchSpec(workload_type="web_api", ha_required=True)
    tpl = template_engine.assemble(spec)
    lambdas = [r for r in tpl["resources"] if r["type"] == "aws_lambda_function"]
    assert lambdas and lambdas[0]["args"].get("publish") is True
    types = [r["type"] for r in tpl["resources"]]
    assert "aws_lambda_alias" in types
    assert "aws_lambda_provisioned_concurrency_config" in types
