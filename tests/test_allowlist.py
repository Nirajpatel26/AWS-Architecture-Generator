"""Allowlist tests — ensures prompts stay in lockstep with templates/patches."""
import json
from pathlib import Path

from pipeline.prompts.allowlist import format_allowlist, get_allowed_types

ROOT = Path(__file__).resolve().parents[1]


def test_allowlist_includes_every_template_resource_type():
    allowed = set(get_allowed_types())
    for tpl_path in (ROOT / "templates").glob("*.json"):
        doc = json.loads(tpl_path.read_text(encoding="utf-8"))
        for r in doc.get("resources", []):
            assert r["type"] in allowed, f"missing {r['type']} from {tpl_path.name}"


def test_allowlist_includes_every_patch_resource_type():
    allowed = set(get_allowed_types())
    for patch_path in (ROOT / "patches").glob("*.json"):
        doc = json.loads(patch_path.read_text(encoding="utf-8"))
        for r in doc.get("add_resources", []) or []:
            assert r["type"] in allowed, f"missing add_resources {r['type']} from {patch_path.name}"
        for m in doc.get("mutate_resources", []) or []:
            sib = m.get("add_sibling")
            if sib:
                assert sib["type"] in allowed, f"missing sibling {sib['type']} from {patch_path.name}"


def test_format_allowlist_is_nonempty_string():
    formatted = format_allowlist()
    assert isinstance(formatted, str)
    assert "aws_" in formatted
    assert "," in formatted


def test_allowlist_is_deduplicated():
    types = get_allowed_types()
    assert len(types) == len(set(types))
