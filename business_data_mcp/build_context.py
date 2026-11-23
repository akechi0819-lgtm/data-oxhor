"""Build the explicitly approved business-context bundle from project sources."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {
    "bridge": "customers/shadow_bi_daily/Work/Bridge/reference.json",
    "scorecard": "customers/shadow_bi_daily/Input/Reference/留学板块-官方记分卡.md",
    "dashboard": "business_data_mcp/dashboard_business_rules.md",
}


def _public_text(text: str) -> str:
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'`[^`]*[/\\][^`]*`', '相关业务配置', text)
    return text


def _clean_bridge(bridge: dict) -> dict:
    excluded = {"candidate_id", "generated_from_candidate_ids", "source_locator", "evidence_refs", "filename", "unresolved"}
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items() if key not in excluded}
        if isinstance(value, list):
            return [clean(item) for item in value if not isinstance(item, dict) or item.get("status", "confirmed") == "confirmed"]
        if isinstance(value, str):
            return re.sub(r"(?:customers|dashboard_product|market_workspace|workspace_modeling)/[^\s,;，；]+", "相关业务来源", value)
        return value
    result = clean({key: value for key, value in bridge.items() if not isinstance(value, list)})
    for key, value in bridge.items():
        if key != "unresolved" and isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            result[key] = [clean(item) for item in value if item.get("status") == "confirmed"]
    return result


def build_bundle(*, project: Path = ROOT, workspace: Path | None = None) -> dict:
    workspace = workspace or project / "customers/shadow_bi_daily"
    source = {name: ((workspace / "Work/Bridge/reference.json") if name == "bridge" else
                     (workspace / "Input/Reference/留学板块-官方记分卡.md") if name == "scorecard" else
                     (project / path)).read_text(encoding="utf-8") for name, path in INPUTS.items()}
    bridge = json.loads(source["bridge"])
    if bridge.get("schema_version") != "company_bridge.v1":
        raise ValueError("Invalid Bridge")
    # Strip source links and workspace paths, preserving all official numbers and caveats.
    scorecard = _public_text(source["scorecard"])
    manifest = {"schema_version": "business_context_bundle.v1", "bridge_version": bridge["bridge_version"],
                "source_sha256": {name: hashlib.sha256(value.encode()).hexdigest() for name, value in source.items()}}
    return {"manifest": manifest, "bridge": _clean_bridge(bridge),
            "dashboard": _public_text(source["dashboard"]),
            "study_scorecard": scorecard}


def build(output: Path, *, project: Path = ROOT, workspace: Path | None = None) -> None:
    bundle = build_bundle(project=project, workspace=workspace)
    output.mkdir(parents=True, exist_ok=True)
    for name in ("bridge", "manifest"):
        (output / (name + ".json")).write_text(json.dumps(bundle[name], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name in ("dashboard", "study_scorecard"):
        (output / (name + ".md")).write_text(bundle[name], encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.output)


if __name__ == "__main__":
    main()
