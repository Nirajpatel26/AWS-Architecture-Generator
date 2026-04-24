from pipeline import template_engine, tf_generator
from pipeline.schema import ArchSpec


def test_emit_contains_provider_block():
    spec = ArchSpec(workload_type="web_api")
    tpl = template_engine.assemble(spec)
    tf = tf_generator.emit(tpl, region="us-east-1")
    assert 'provider "aws"' in tf
    assert "us-east-1" in tf


def test_emit_renders_all_resources():
    spec = ArchSpec(workload_type="static_site")
    tpl = template_engine.assemble(spec)
    tf = tf_generator.emit(tpl)
    for r in tpl["resources"]:
        assert f'"{r["type"]}" "{r["name"]}"' in tf


def test_emit_hipaa_includes_kms_resource():
    spec = ArchSpec(workload_type="web_api", compliance=["HIPAA"])
    tpl = template_engine.assemble(spec)
    tf = tf_generator.emit(tpl)
    assert "aws_kms_key" in tf
    assert "aws_cloudtrail" in tf
