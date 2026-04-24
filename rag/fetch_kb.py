"""Populate rag/knowledge_base/aws_docs/ with official AWS documentation.

Clones the awsdocs/* GitHub repos that match services used by our templates,
and downloads the AWS HIPAA-eligibility reference page as HTML. After running
this, re-run `python -m rag.ingest` to rebuild the FAISS index.

Usage:
    python -m rag.fetch_kb                 # clone everything
    python -m rag.fetch_kb --only lambda   # just one
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "knowledge_base" / "aws_docs"

# Services used by templates/ — maps local folder -> awsdocs repo
REPOS: dict[str, str] = {
    "lambda": "https://github.com/awsdocs/aws-lambda-developer-guide",
    "api_gateway": "https://github.com/awsdocs/amazon-api-gateway-developer-guide",
    "dynamodb": "https://github.com/awsdocs/amazon-dynamodb-developer-guide",
    "s3": "https://github.com/awsdocs/amazon-s3-developer-guide",
    "cloudfront": "https://github.com/awsdocs/amazon-cloudfront-developer-guide",
    "route53": "https://github.com/awsdocs/amazon-route53-docs",
    "acm": "https://github.com/awsdocs/aws-certificate-user-guide",
    "kms": "https://github.com/awsdocs/aws-kms-developer-guide",
    "cloudtrail": "https://github.com/awsdocs/aws-cloudtrail-user-guide",
    "cognito": "https://github.com/awsdocs/amazon-cognito-developer-guide",
    "glue": "https://github.com/awsdocs/aws-glue-developer-guide",
    "athena": "https://github.com/awsdocs/amazon-athena-user-guide",
    "step_functions": "https://github.com/awsdocs/aws-step-functions-developer-guide",
    "sagemaker": "https://github.com/awsdocs/amazon-sagemaker-developer-guide",
    "ecr": "https://github.com/awsdocs/amazon-ecr-user-guide",
    "rds": "https://github.com/awsdocs/amazon-rds-user-guide",
    "elasticache": "https://github.com/awsdocs/amazon-elasticache-docs",
    "cloudwatch": "https://github.com/awsdocs/amazon-cloudwatch-user-guide",
    "iam": "https://github.com/awsdocs/iam-user-guide",
    "vpc": "https://github.com/awsdocs/amazon-vpc-user-guide",
    # No public awsdocs repo for the WAF framework — pulled as HTML below.
}

# Direct-fetch HTML pages we want as part of the KB
EXTRA_PAGES: dict[str, str] = {
    "hipaa_eligibility.html": "https://aws.amazon.com/compliance/hipaa-eligible-services-reference/",
    "hipaa_overview.html": "https://aws.amazon.com/compliance/hipaa-compliance/",
    "pci_overview.html": "https://aws.amazon.com/compliance/pci-dss-level-1-faqs/",
    "soc2_overview.html": "https://aws.amazon.com/compliance/soc-faqs/",
    "compliance_services_in_scope.html": "https://aws.amazon.com/compliance/services-in-scope/",
    "well_architected_framework.html": "https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html",
    "well_architected_operational.html": "https://docs.aws.amazon.com/wellarchitected/latest/operational-excellence-pillar/welcome.html",
    "well_architected_security.html": "https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/welcome.html",
    "well_architected_reliability.html": "https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/welcome.html",
    "well_architected_performance.html": "https://docs.aws.amazon.com/wellarchitected/latest/performance-efficiency-pillar/welcome.html",
    "well_architected_cost.html": "https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/welcome.html",
    "well_architected_sustainability.html": "https://docs.aws.amazon.com/wellarchitected/latest/sustainability-pillar/welcome.html",
    # Service product pages for services whose awsdocs/* GitHub repos are
    # empty shells (README/LICENSE only). AWS moved the content to
    # docs.aws.amazon.com; these product/feature pages are the best
    # self-contained single-URL summary for each service.
    "service_iam.html":            "https://aws.amazon.com/iam/features/",
    "service_cognito.html":        "https://aws.amazon.com/cognito/features/",
    "service_rds.html":            "https://aws.amazon.com/rds/features/",
    "service_glue.html":           "https://aws.amazon.com/glue/features/",
    "service_athena.html":         "https://aws.amazon.com/athena/features/",
    "service_sagemaker.html":      "https://aws.amazon.com/sagemaker/features/",
    "service_step_functions.html": "https://aws.amazon.com/step-functions/features/",
    "service_route53.html":        "https://aws.amazon.com/route53/features/",
    "service_elasticache.html":    "https://aws.amazon.com/elasticache/features/",
}


def _have_git() -> bool:
    return shutil.which("git") is not None


def _clone(name: str, url: str, force: bool = False) -> str:
    dest = TARGET / name
    if dest.exists() and not force:
        return "exists"
    if dest.exists() and force:
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        ["git", "clone", "--depth", "1", "--quiet", url, str(dest)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if res.returncode != 0:
        return f"fail: {res.stderr.strip().splitlines()[-1] if res.stderr else 'unknown'}"
    return "ok"


def _fetch(name: str, url: str, force: bool = False) -> str:
    dest = TARGET / name
    if dest.exists() and not force:
        return "exists"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cloud-arch-designer/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            dest.write_bytes(resp.read())
        return "ok"
    except Exception as e:
        return f"fail: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="clone just one repo by folder name")
    ap.add_argument("--force", action="store_true", help="re-clone even if present")
    args = ap.parse_args()

    if not _have_git():
        print("ERROR: `git` is not on PATH — cannot clone AWS docs.", file=sys.stderr)
        return 2

    repos = REPOS
    if args.only:
        if args.only not in repos:
            print(f"Unknown --only={args.only}. Valid: {', '.join(repos)}", file=sys.stderr)
            return 2
        repos = {args.only: repos[args.only]}

    print(f"Cloning {len(repos)} awsdocs repo(s) into {TARGET}")
    total = {"ok": 0, "exists": 0, "fail": 0}
    for name, url in repos.items():
        status = _clone(name, url, force=args.force)
        key = "ok" if status == "ok" else ("exists" if status == "exists" else "fail")
        total[key] += 1
        print(f"  [{key:6}] {name:18} {status if key == 'fail' else ''}")

    if not args.only:
        print(f"\nFetching {len(EXTRA_PAGES)} reference page(s)")
        for name, url in EXTRA_PAGES.items():
            status = _fetch(name, url, force=args.force)
            key = "ok" if status == "ok" else ("exists" if status == "exists" else "fail")
            total[key] += 1
            print(f"  [{key:6}] {name:24} {status if key == 'fail' else ''}")

    print(f"\nSummary: {total}")
    print(f"\nNext step: python -m rag.ingest")
    return 0 if total["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
