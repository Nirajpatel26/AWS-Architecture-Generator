"""Stage 5: emit Terraform HCL from an assembled template dict.

The baseline emitter is deterministic — it turns the JSON resource list into
valid HCL without calling the LLM. On validator failure the LLM is invoked to
propose corrections (see validator.py).
"""
from __future__ import annotations

import json
from typing import Any

# Variables emitted into every generated configuration.
# Override any of these in terraform.tfvars (see terraform.tfvars.example).
_STANDARD_VARIABLES: dict[str, dict] = {
    "aws_region": {
        "type": "string",
        "description": "AWS region to deploy into",
        "default": "us-east-1",
    },
    "lambda_runtime": {
        "type": "string",
        "description": "Lambda function runtime identifier",
        "default": "python3.12",
    },
    "lambda_memory_size": {
        "type": "number",
        "description": "Lambda memory allocation in MB (128-10240)",
        "default": 512,
    },
    "lambda_timeout": {
        "type": "number",
        "description": "Lambda execution timeout in seconds (1-900)",
        "default": 10,
    },
    "lambda_handler": {
        "type": "string",
        "description": "Lambda handler entry-point as module.function",
        "default": "main.handler",
    },
    "lambda_filename": {
        "type": "string",
        "description": "Path to the Lambda deployment zip artifact",
        "default": "handler.zip",
    },
    "log_retention_days": {
        "type": "number",
        "description": "CloudWatch log group retention in days",
        "default": 14,
    },
    "db_password": {
        "type": "string",
        "description": "Master password for the RDS instance (only used when data_store=sql)",
        "default": "changeme-in-tfvars",
    },
    "dr_region": {
        "type": "string",
        "description": "Secondary AWS region used by the multi-region patch",
        "default": "us-west-2",
    },
}


def _hcl_value(v: Any, indent: int = 1) -> str:
    pad = "  " * indent
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        if v.startswith("aws_") and "." in v and not v.startswith('"'):
            # reference expression e.g. aws_s3_bucket.raw.id
            return v
        if v.startswith("${") and v.endswith("}"):
            # Unwrap to a bare HCL expression so embedded quotes remain valid.
            return v[2:-1]
        return json.dumps(v)
    if isinstance(v, list):
        if not v:
            return "[]"
        inner = ", ".join(_hcl_value(x, indent) for x in v)
        return f"[{inner}]"
    if isinstance(v, dict):
        lines = ["{"]
        for k, val in v.items():
            rendered = _hcl_value(val, indent + 1)
            if isinstance(val, dict):
                lines.append(f"{pad}  {k} {rendered}")
            else:
                lines.append(f"{pad}  {k} = {rendered}")
        lines.append(f"{pad}}}")
        return "\n".join(lines)
    return json.dumps(str(v))


def _render_resource(res: dict) -> str:
    rtype = res["type"]
    rname = res["name"]
    args = res.get("args", {})
    lines = [f'resource "{rtype}" "{rname}" {{']
    for k, v in args.items():
        rendered = _hcl_value(v, indent=1)
        if isinstance(v, dict):
            lines.append(f"  {k} {rendered}")
        else:
            lines.append(f"  {k} = {rendered}")
    lines.append("}")
    return "\n".join(lines)


def _render_variables(region: str) -> str:
    blocks = []
    for name, meta in _STANDARD_VARIABLES.items():
        default = meta["default"] if name != "aws_region" else region
        default_hcl = json.dumps(default) if isinstance(default, str) else str(default)
        block = (
            f'variable "{name}" {{\n'
            f'  type        = {meta["type"]}\n'
            f'  description = {json.dumps(meta["description"])}\n'
            f'  default     = {default_hcl}\n'
            f'}}'
        )
        blocks.append(block)
    return "\n\n".join(blocks)


def _render_provider(extra: list | None = None) -> str:
    out = [
        'terraform {',
        '  required_providers {',
        '    aws = { source = "hashicorp/aws", version = ">= 5.0" }',
        '  }',
        '}',
        '',
        'provider "aws" {',
        '  region = var.aws_region',
        '}',
    ]
    for p in extra or []:
        alias = p.get("alias")
        region_line = (
            f'  region = var.{p["region_var"]}' if p.get("region_var")
            else f'  region = "{p.get("region", "us-east-1")}"'
        )
        out += ["", 'provider "aws" {', f'  alias  = "{alias}"', region_line, "}"]
    return "\n".join(out)


def emit(template: dict, region: str = "us-east-1") -> str:
    variables = _render_variables(region)
    header = _render_provider(template.get("providers", []))
    resources = "\n\n".join(_render_resource(r) for r in template.get("resources", []))
    return f"{variables}\n\n{header}\n\n{resources}\n"
