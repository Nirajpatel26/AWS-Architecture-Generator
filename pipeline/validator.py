"""Stage 6: terraform validate + tfsec, with LLM-driven retry on failure.

The repair path is RAG-augmented: when `terraform validate` fails, we identify
which AWS resource type(s) are implicated (from the error text + the HCL) and
retrieve matching service documentation. Those chunks are injected into the
repair prompt so the LLM has the canonical argument names / nested block
schemas for the failing resource — measurably lifts fix success rate vs.
sending only the error string.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .llm import generate_text
from .prompts import load

VALIDATOR_REPAIR_PROMPT_VERSION = "v1"

TERRAFORM_BIN = os.getenv("TERRAFORM_BIN", "terraform")
TFSEC_BIN = os.getenv("TFSEC_BIN", "tfsec")
MAX_ATTEMPTS = 3


@dataclass
class ValidationResult:
    ok: bool
    attempts: int
    tf_code: str
    validate_output: str = ""
    tfsec_output: str = ""
    tfsec_high: int = 0
    errors: List[str] = field(default_factory=list)
    skipped_reason: Optional[str] = None
    findings: List[dict] = field(default_factory=list)


def _have(binary: str) -> bool:
    return shutil.which(binary) is not None


_PLUGIN_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "terraform-plugins"


def _run(cmd: List[str], cwd: Path) -> subprocess.CompletedProcess:
    _PLUGIN_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("TF_PLUGIN_CACHE_DIR", str(_PLUGIN_CACHE_DIR))
    env.setdefault("TF_IN_AUTOMATION", "1")
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


def _run_tfsec(work: Path) -> tuple[str, int, List[dict]]:
    if not _have(TFSEC_BIN):
        return "tfsec binary not found — skipped", 0, []
    try:
        res = _run([TFSEC_BIN, ".", "--format", "json", "--no-color"], work)
        data = json.loads(res.stdout or "{}")
        raw_findings = data.get("results") or []
        findings: List[dict] = []
        for f in raw_findings:
            loc = f.get("location") or {}
            findings.append(
                {
                    "rule_id": f.get("rule_id") or f.get("long_id") or "",
                    "severity": (f.get("severity") or "").upper(),
                    "resource": f.get("resource") or "",
                    "description": f.get("description") or "",
                    "resolution": f.get("resolution") or "",
                    "location": f"{loc.get('filename', '')}:{loc.get('start_line', '')}",
                }
            )
        high = sum(1 for f in findings if f["severity"] in ("HIGH", "CRITICAL"))
        return res.stdout or "", high, findings
    except Exception as e:
        return f"tfsec error: {e}", 0, []


REPAIR_PROMPT_TEMPLATE = load(f"validator_repair.{VALIDATOR_REPAIR_PROMPT_VERSION}")


# Terraform resource types look like `aws_s3_bucket`, `aws_lambda_function`, etc.
_RESOURCE_TYPE_RE = re.compile(r"\baws_[a-z0-9_]+\b")

# Rough map from Terraform resource prefix to the service keyword we tag at
# ingest. Covers the resource types the templates emit; unknown prefixes fall
# back to unfiltered retrieval.
_TF_TO_SERVICE = {
    "aws_s3_": "s3",
    "aws_lambda_": "lambda",
    "aws_apigatewayv2_": "api_gateway",
    "aws_apigateway_": "api_gateway",
    "aws_dynamodb_": "dynamodb",
    "aws_kms_": "kms",
    "aws_cloudtrail": "cloudtrail",
    "aws_cloudwatch_": "cloudwatch",
    "aws_iam_": "iam",
    "aws_cognito_": "cognito",
    "aws_cloudfront_": "cloudfront",
    "aws_route53_": "route53",
    "aws_rds_": "rds",
    "aws_db_": "rds",
    "aws_glue_": "glue",
    "aws_athena_": "athena",
    "aws_sagemaker_": "sagemaker",
    "aws_ecr_": "ecr",
    "aws_elasticache_": "elasticache",
    "aws_sfn_": "step_functions",
    "aws_acm_": "acm",
    "aws_vpc": "vpc",
    "aws_subnet": "vpc",
    "aws_security_group": "vpc",
}


def _resource_types_from_errors(errors: str, tf_code: str) -> List[str]:
    """Pull candidate `aws_*` resource type names, error text first."""
    seen = []
    for text in (errors or "", tf_code or ""):
        for m in _RESOURCE_TYPE_RE.findall(text):
            if m not in seen:
                seen.append(m)
    return seen


def _services_for(types: List[str]) -> List[str]:
    services = []
    for t in types:
        for prefix, svc in _TF_TO_SERVICE.items():
            if t.startswith(prefix) or t == prefix.rstrip("_"):
                if svc not in services:
                    services.append(svc)
                break
    return services


def _retrieve_repair_docs(errors: str, tf_code: str, k: int = 3) -> List[dict]:
    """RAG-fetch docs for the failing resource types. Fail silent."""
    try:
        from rag import retriever
    except Exception:
        return []
    types = _resource_types_from_errors(errors, tf_code)
    if not types:
        return []
    services = _services_for(types)
    # Query = the first error line(s) + the failing resource type names. This
    # gives the retriever both the symptom and the service topic.
    err_head = "\n".join((errors or "").splitlines()[:6])
    query = f"{err_head}\n{' '.join(types[:3])}".strip()
    try:
        if services:
            hits = retriever.retrieve(query, k=k, filters={"service": services})
            if hits:
                return hits
        return retriever.retrieve(query, k=k)
    except Exception:
        return []


def _format_repair_docs(hits: List[dict]) -> str:
    if not hits:
        return ""
    lines = [
        "Relevant Terraform/AWS documentation for the failing resource "
        "(use to correct argument names and nested blocks):"
    ]
    for i, h in enumerate(hits, 1):
        src = h.get("source", "doc")
        snippet = (h.get("snippet") or "").replace("\n", " ")
        if len(snippet) > 400:
            snippet = snippet[:400] + "..."
        lines.append(f"[{i}] {src}: {snippet}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _fix_with_llm(tf_code: str, errors: str) -> str:
    docs = _retrieve_repair_docs(errors, tf_code)
    prompt = REPAIR_PROMPT_TEMPLATE.format(
        docs_block=_format_repair_docs(docs),
        errors=errors,
        tf_code=tf_code,
    )
    fixed = generate_text(prompt)
    fixed = fixed.strip()
    if fixed.startswith("```"):
        fixed = "\n".join(fixed.splitlines()[1:])
        if fixed.endswith("```"):
            fixed = fixed[: fixed.rfind("```")]
    return fixed or tf_code


def validate(tf_code: str, max_attempts: int = MAX_ATTEMPTS) -> ValidationResult:
    if not _have(TERRAFORM_BIN):
        return ValidationResult(
            ok=True,
            attempts=0,
            tf_code=tf_code,
            skipped_reason="terraform binary not found — validation skipped",
        )

    # Ablation hook: when the repair loop is disabled, cap attempts at 1 so a
    # single validate() failure is final. eval/ablation.py sets this env var.
    if os.getenv("CLOUDARCH_REPAIR_DISABLED") == "1":
        max_attempts = 1

    current = tf_code
    last_stderr = ""
    for attempt in range(1, max_attempts + 1):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "main.tf").write_text(current, encoding="utf-8")
            init = _run([TERRAFORM_BIN, "init", "-backend=false", "-input=false"], work)
            if init.returncode != 0:
                last_stderr = init.stderr
                if attempt < max_attempts:
                    current = _fix_with_llm(current, init.stderr)
                continue
            val = _run([TERRAFORM_BIN, "validate", "-no-color"], work)
            if val.returncode == 0:
                tfsec_out, high, findings = _run_tfsec(work)
                return ValidationResult(
                    ok=True,
                    attempts=attempt,
                    tf_code=current,
                    validate_output=val.stdout,
                    tfsec_output=tfsec_out,
                    tfsec_high=high,
                    findings=findings,
                )
            last_stderr = val.stdout + val.stderr
            if attempt < max_attempts:
                current = _fix_with_llm(current, last_stderr)

    return ValidationResult(
        ok=False,
        attempts=max_attempts,
        tf_code=current,
        validate_output=last_stderr,
        errors=[last_stderr],
    )
