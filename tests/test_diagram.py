"""Diagram tests — focus on the deterministic Mermaid fallback + coverage of NODE_MAP."""
from pipeline import diagram, template_engine
from pipeline.schema import ArchSpec


def test_mermaid_contains_flowchart_and_user():
    tpl = {"resources": [{"type": "aws_lambda_function", "name": "handler"}]}
    m = diagram._mermaid(tpl)
    assert m.startswith("flowchart LR")
    assert "user((User / Client))" in m


def test_mermaid_skips_unknown_resource_types():
    tpl = {
        "resources": [
            {"type": "aws_lambda_function", "name": "handler"},
            {"type": "aws_unknown_service", "name": "ghost"},
        ]
    }
    m = diagram._mermaid(tpl)
    assert "aws_lambda_function_handler" in m
    assert "ghost" not in m


def test_mermaid_groups_resources_by_tier():
    spec = ArchSpec(workload_type="web_api", auth_required=True)
    tpl = template_engine.assemble(spec)
    m = diagram._mermaid(tpl)
    assert 'subgraph edge["Edge / API"]' in m
    assert 'subgraph compute["Compute"]' in m


def test_render_always_returns_mermaid_string():
    """Whether Graphviz/diagrams are installed or not, the mermaid str must come back."""
    tpl = {
        "name": "web_api",
        "resources": [{"type": "aws_lambda_function", "name": "handler"}],
    }
    png, mermaid = diagram.render(tpl)
    assert isinstance(mermaid, str) and mermaid.startswith("flowchart")
    # png is either None or a real path — never a string that isn't a file
    if png is not None:
        import os
        assert os.path.exists(png)


def test_node_map_covers_every_template_resource():
    """Any primary resource shipped in a baseline template must be renderable.

    Modifier sub-resources (S3 configuration blocks, etc.) are intentionally
    omitted from the icon map — they don't warrant their own node.
    """
    MODIFIER_SUBRESOURCES = {
        "aws_s3_bucket_public_access_block",
        "aws_s3_bucket_server_side_encryption_configuration",
        "aws_s3_bucket_replication_configuration",
    }
    for wl in ("web_api", "data_pipeline", "ml_training", "static_site"):
        tpl = template_engine.load_template(wl)
        for r in tpl["resources"]:
            rtype = r["type"]
            if rtype in MODIFIER_SUBRESOURCES:
                continue
            assert rtype in diagram._NODE_MAP, (
                f"{rtype} in {wl}.json is missing from diagram._NODE_MAP"
            )
