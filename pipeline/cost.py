"""Stage 8: compute a monthly $ estimate from the assembled template.

Pricing is deterministic and layered:

  total = fixed_monthly * scale_multiplier
        + usage_charges(requests, MAU, GB transfer, KMS API calls, log ingest)

Usage volumes are driven by the `scale_assumptions` block in pricing.json so
that Lambda / API Gateway / Cognito / CloudFront / KMS — all of which are
primarily usage-priced — contribute realistic numbers instead of $0.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple

_PRICING_FILE = Path(__file__).resolve().parent / "pricing.json"

# Pricing provenance — surfaced in the Cost tab so users see the data is
# static. Bump PRICING_UPDATED whenever pricing.json is refreshed.
PRICING_UPDATED = "2026-04"
PRICING_SOURCE = "AWS public pricing, manually curated"


def pricing_meta() -> dict:
    return {"updated": PRICING_UPDATED, "source": PRICING_SOURCE}


@lru_cache(maxsize=1)
def _load_pricing() -> dict:
    return json.loads(_PRICING_FILE.read_text(encoding="utf-8"))


_FIXED_SCALE_MULT = {"small": 1.0, "medium": 2.5, "large": 8.0}


def _usage_volumes(pricing: dict, scale: str) -> dict:
    assumptions = pricing.get("scale_assumptions", {})
    return assumptions.get(scale, assumptions.get("small", {}))


def _usage_charge(rtype: str, p: dict, usage: dict) -> float:
    """Non-fixed, volume-driven charges for the resource type."""
    charge = 0.0
    req_millions = usage.get("requests_millions", 0)

    if "per_million_requests" in p and rtype in {
        "aws_lambda_function",
        "aws_apigatewayv2_api",
        "aws_api_gateway_rest_api",
    }:
        charge += float(p["per_million_requests"]) * req_millions

    if rtype == "aws_lambda_function":
        charge += float(p.get("gb_second_monthly_base", 0.0)) * req_millions

    if rtype == "aws_kms_key" and "per_million_requests" in p:
        charge += float(p["per_million_requests"]) * usage.get("kms_requests_millions", 0)

    if rtype == "aws_cognito_user_pool":
        mau = usage.get("mau", 0)
        free = int(p.get("mau_free_tier", 0))
        billable = max(0, mau - free)
        charge += float(p.get("per_mau_above_50k", 0.0)) * billable

    if rtype == "aws_cloudfront_distribution":
        charge += float(p.get("per_gb_transfer", 0.0)) * usage.get("cf_gb_transfer", 0)

    if rtype == "aws_cloudwatch_log_group":
        charge += float(p.get("per_gb_ingest", 0.0)) * usage.get("log_gb", 0)

    return charge


def estimate(template: dict, scale: str = "small") -> Tuple[float, List[Dict]]:
    pricing = _load_pricing()
    fixed_mult = _FIXED_SCALE_MULT.get(scale, 1.0)
    usage = _usage_volumes(pricing, scale)
    breakdown: List[Dict] = []
    total = 0.0

    for res in template.get("resources", []):
        rtype = res["type"]
        p = pricing.get(rtype)
        if not p:
            breakdown.append(
                {
                    "service": rtype.replace("aws_", ""),
                    "name": res["name"],
                    "monthly_usd": 0.0,
                    "note": "no pricing entry",
                }
            )
            continue

        fixed = float(p.get("monthly", 0.0))
        args = res.get("args", {}) or {}
        if rtype == "aws_db_instance" and args.get("multi_az"):
            fixed *= p.get("multi_az_multiplier", 2.0)
        fixed *= fixed_mult

        usage_cost = _usage_charge(rtype, p, usage)

        monthly = fixed + usage_cost
        total += monthly
        breakdown.append(
            {
                "service": rtype.replace("aws_", ""),
                "name": res["name"],
                "monthly_usd": round(monthly, 2),
                "fixed_usd": round(fixed, 2),
                "usage_usd": round(usage_cost, 2),
            }
        )
    return round(total, 2), breakdown
