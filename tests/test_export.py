"""ZIP bundle export smoke tests."""
from __future__ import annotations

import io
import zipfile

from pipeline import export
from pipeline.orchestrator import RunResult
from pipeline.schema import ArchSpec


def _fake_result() -> RunResult:
    return RunResult(
        spec=ArchSpec(raw_prompt="demo prompt", workload_type="web_api", project_name="demo"),
        template={"resources": [{"type": "aws_s3_bucket", "name": "main"}]},
        base_template={"resources": []},
        tf_code='resource "aws_s3_bucket" "main" {}\n',
        tf_valid=True,
        tf_attempts=1,
        tfsec_high=0,
        tfsec_findings=[{"rule_id": "AWS001", "severity": "HIGH",
                         "resource": "aws_s3_bucket.main",
                         "description": "bucket lacks encryption"}],
        cost_breakdown=[{"name": "main", "service": "s3", "monthly_usd": 2.3,
                         "fixed_usd": 2.3, "usage_usd": 0.0}],
        monthly_cost=2.3,
        cost_meta={"updated": "2026-04", "source": "static"},
        explanation="Because reasons.",
    )


def test_zip_contains_expected_files():
    data = export.build_zip(_fake_result())
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        assert "main.tf" in names
        assert "variables.tf" in names
        assert "README.md" in names
        assert "cost_breakdown.csv" in names
        # README mentions the prompt and cost
        readme = zf.read("README.md").decode("utf-8")
        assert "demo prompt" in readme
        assert "2.30" in readme or "2.3" in readme
        # CSV has header + one row
        csv_text = zf.read("cost_breakdown.csv").decode("utf-8")
        assert "monthly_usd" in csv_text
        assert "main" in csv_text
