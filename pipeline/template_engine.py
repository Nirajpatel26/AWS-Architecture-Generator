"""Stage 4: load template JSON and apply patch transformations."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

from .schema import ArchSpec

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "templates"
PATCH_DIR = ROOT / "patches"


def load_template(workload_type: str) -> dict:
    path = TEMPLATE_DIR / f"{workload_type}.json"
    if not path.exists():
        raise FileNotFoundError(f"Unknown workload template: {workload_type}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_patch(name: str) -> dict:
    path = PATCH_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _substitute(obj: Any, vars: Dict[str, str]) -> Any:
    if isinstance(obj, str):
        out = obj
        for k, v in vars.items():
            out = out.replace("{{" + k + "}}", str(v))
        return out
    if isinstance(obj, list):
        return [_substitute(x, vars) for x in obj]
    if isinstance(obj, dict):
        return {k: _substitute(v, vars) for k, v in obj.items()}
    return obj


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def apply_patch(tpl: dict, patch: dict) -> dict:
    tpl = copy.deepcopy(tpl)
    resources: List[dict] = tpl.setdefault("resources", [])

    # mutations first so later adds see the mutated state
    for rule in patch.get("mutate_resources", []):
        match_type = rule.get("match", {}).get("type")
        for res in list(resources):
            if res["type"] != match_type:
                continue
            merge = rule.get("merge_args")
            if merge:
                res["args"] = _merge(res.get("args", {}), merge)
            sibling = rule.get("add_sibling")
            if sibling:
                rendered = _substitute(copy.deepcopy(sibling), {"match.name": res["name"]})
                resources.append(rendered)

    for add in patch.get("add_resources", []):
        resources.append(copy.deepcopy(add))

    providers = tpl.setdefault("providers", [])
    for p in patch.get("providers", []):
        providers.append(copy.deepcopy(p))

    applied = tpl.setdefault("applied_patches", [])
    applied.append(patch["name"])

    patch_assumptions = patch.get("assumptions", [])
    tpl.setdefault("patch_assumptions", []).extend(patch_assumptions)
    return tpl


def _filter_by_spec(resources: List[dict], spec: ArchSpec) -> List[dict]:
    """Drop resources whose slot/data_store/required_if tags don't match spec.

    - `data_stores`: keep only if spec.data_store is in the list
    - `required_if`: spec attribute must be truthy; `optional:true` + falsy → drop
    """
    kept: List[dict] = []
    for res in resources:
        allowed_stores = res.get("data_stores")
        if allowed_stores and spec.data_store not in allowed_stores:
            continue

        required_if = res.get("required_if")
        if required_if:
            if not getattr(spec, required_if, False):
                if res.get("optional"):
                    continue
        kept.append(res)
    return kept


def assemble(spec: ArchSpec) -> dict:
    tpl = load_template(spec.workload_type)
    tpl["resources"] = _filter_by_spec(tpl.get("resources", []), spec)

    patches_to_apply: List[dict] = []
    if spec.compliance and "HIPAA" in spec.compliance:
        patches_to_apply.append(load_patch("hipaa"))
    if spec.ha_required:
        patches_to_apply.append(load_patch("ha"))
    if spec.multi_region:
        patches_to_apply.append(load_patch("multi_region"))
    if spec.compliance and "PCI" in spec.compliance:
        patches_to_apply.append(load_patch("pci"))
    if spec.compliance and "SOC2" in spec.compliance:
        patches_to_apply.append(load_patch("soc2"))

    patches_to_apply.sort(key=lambda p: p.get("order", 99))
    for p in patches_to_apply:
        tpl = apply_patch(tpl, p)

    project_name = spec.project_name or tpl.get("variables", {}).get("project_name", "cloudarch")
    tpl = _substitute(
        tpl,
        {
            "project_name": project_name,
            "region": spec.region or "us-east-1",
        },
    )
    spec.assumptions.extend(tpl.get("patch_assumptions", []))
    return tpl
