#!/usr/bin/env python3
"""Verify the local-only S4 PPT runtime before a Codex or Harness turn."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "ppt-master"
REQUIRED_MODULES = {
    "pptx": "python-pptx",
    "xlsxwriter": "XlsxWriter",
    "pathops": "skia-pathops",
    "uharfbuzz": "uharfbuzz",
}
BLOCKED_PREFIXES = (
    "IMAGE_", "GEMINI_", "OPENAI_", "MINIMAX_", "STABILITY_", "BFL_", "IDEOGRAM_",
    "QWEN_", "DASHSCOPE_", "ZHIPU_", "BIGMODEL_", "VOLCENGINE_", "ARK_", "MODELSCOPE_",
    "SILICONFLOW_", "FAL_", "REPLICATE_", "OPENROUTER_", "ELEVENLABS_", "COSYVOICE_",
    "PEXELS_", "PIXABAY_", "GOOGLE_API_KEY",
)


def blocked_environment() -> dict[str, str]:
    return {key: "" for key in os.environ if key.startswith(BLOCKED_PREFIXES)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_frozen_analysis(analysis_path: Path, evidence_root: Path) -> dict[str, Any]:
    """Validate a host-neutral frozen analysis and its same-snapshot evidence."""
    value = json.loads(analysis_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("frozen analysis must be a JSON object")
    required = ("schema_version", "snapshot_id", "allowed_sources", "excluded_sources", "evidence", "key_queries")
    missing = [key for key in required if key not in value]
    if missing:
        raise ValueError("frozen analysis manifest missing: " + ", ".join(missing))
    if value["schema_version"] != "s4_ppt_frozen_analysis.v1":
        raise ValueError("unsupported frozen analysis schema; regenerate as s4_ppt_frozen_analysis.v1")
    if not isinstance(value["snapshot_id"], str) or not value["snapshot_id"]:
        raise ValueError("snapshot_id must be a non-empty string")
    if not isinstance(value["allowed_sources"], list) or not isinstance(value["excluded_sources"], list):
        raise ValueError("allowed_sources and excluded_sources must be arrays")
    if any(not isinstance(source, str) or not source for source in value["allowed_sources"] + value["excluded_sources"]):
        raise ValueError("source policies must contain non-empty strings")
    if len(set(value["allowed_sources"])) != len(value["allowed_sources"]):
        raise ValueError("allowed_sources must not contain duplicates")
    if len(set(value["excluded_sources"])) != len(value["excluded_sources"]):
        raise ValueError("excluded_sources must not contain duplicates")
    if set(value["allowed_sources"]) & set(value["excluded_sources"]):
        raise ValueError("allowed_sources and excluded_sources overlap")
    evidence = value["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("evidence must be a non-empty array")
    if not isinstance(value["key_queries"], list) or not value["key_queries"]:
        raise ValueError("key_queries must be a non-empty array")
    checked: list[dict[str, str]] = []
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str) or not isinstance(item.get("source_id"), str):
            raise ValueError("each evidence item requires path, sha256, and source_id")
        if item["source_id"] not in value["allowed_sources"]:
            raise ValueError(f"evidence source is not allowed: {item['source_id']}")
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"evidence path must stay under evidence root: {relative}")
        path = evidence_root / relative
        if not path.is_file():
            raise ValueError(f"evidence file missing: {relative}")
        actual = _sha256(path)
        if actual != item["sha256"]:
            raise ValueError(f"evidence hash mismatch: {relative}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("snapshot_id") != value["snapshot_id"]:
            raise ValueError(f"evidence snapshot mismatch: {relative}")
        referenced_source_ids = payload.get("referenced_source_ids")
        if not isinstance(referenced_source_ids, list) or not referenced_source_ids or any(not isinstance(source, str) for source in referenced_source_ids):
            raise ValueError(f"evidence source provenance missing: {relative}")
        if item["source_id"] not in referenced_source_ids:
            raise ValueError(f"evidence source provenance does not include declared source: {relative}")
        unapproved = sorted(set(referenced_source_ids) - set(value["allowed_sources"]))
        if unapproved:
            raise ValueError(f"evidence source provenance is not allowed: {relative}: {', '.join(unapproved)}")
        checked.append({"path": relative.as_posix(), "sha256": actual, "source_id": item["source_id"]})
    evidence_paths = {item["path"] for item in checked}
    if any(not isinstance(path, str) or path not in evidence_paths for path in value["key_queries"]):
        raise ValueError("key_queries must reference listed evidence paths")
    return {
        "schema_version": value["schema_version"],
        "snapshot_id": value["snapshot_id"],
        "allowed_sources": value["allowed_sources"],
        "excluded_sources": value["excluded_sources"],
        "evidence": checked,
        "key_queries": value["key_queries"],
    }


def verify() -> list[str]:
    errors: list[str] = []
    for relative in ("SKILL.md", "scripts/attribution_guard.py", "scripts/svg_to_pptx.py"):
        if not (SKILL / relative).is_file():
            errors.append(f"missing skill file: {relative}")
    for module, distribution in REQUIRED_MODULES.items():
        try:
            importlib.import_module(module)
        except Exception as exc:  # pragma: no cover - platform import messages vary
            errors.append(f"{distribution} unavailable: {exc}")
    credentials = sorted(key for key in os.environ if key.startswith(BLOCKED_PREFIXES) and os.environ.get(key))
    if credentials:
        errors.append("provider credentials must be removed before local-only S4 execution: " + ", ".join(credentials))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-env", action="store_true")
    parser.add_argument("--frozen-analysis", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    args = parser.parse_args()
    errors = verify()
    if bool(args.frozen_analysis) != bool(args.evidence_root):
        errors.append("--frozen-analysis and --evidence-root must be provided together")
    if args.frozen_analysis and args.evidence_root:
        try:
            validate_frozen_analysis(args.frozen_analysis, args.evidence_root)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"frozen analysis invalid: {exc}")
    if errors:
        print("S4_PPT_PREFLIGHT_FAILED")
        print("\n".join(errors))
        return 1
    if args.print_env:
        for key, value in sorted(blocked_environment().items()):
            print(f"{key}={value}")
    print("S4_PPT_PREFLIGHT_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
