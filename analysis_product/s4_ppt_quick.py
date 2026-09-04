#!/usr/bin/env python3
"""Small, host-neutral Quick Generate coordinator for S4 PPT delivery."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

try:
    from s4_ppt_preflight import validate_frozen_analysis
except ModuleNotFoundError:  # package import from the repository root
    from analysis_product.s4_ppt_preflight import validate_frozen_analysis


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "ppt-master"


class CommandError(RuntimeError):
    def __init__(self, record: dict[str, Any], detail: str) -> None:
        super().__init__(detail)
        self.record = record


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_checked(command: list[str], *, cwd: Path) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    elapsed_ms = round((time.monotonic() - started) * 1000)
    record = {"command": command, "exit_code": result.returncode, "elapsed_ms": elapsed_ms}
    if result.returncode:
        raise CommandError(record, f"command failed ({result.returncode}): {' '.join(command)}: " + (result.stderr or result.stdout).strip())
    return record


def run_guard_preflight(analysis: Path | None = None, evidence_root: Path | None = None) -> list[dict[str, Any]]:
    guard = run_checked([sys.executable, "scripts/attribution_guard.py"], cwd=SKILL)
    preflight_command = [sys.executable, str(ROOT / "analysis_product" / "s4_ppt_preflight.py")]
    if analysis is not None and evidence_root is not None:
        preflight_command.extend(["--frozen-analysis", str(analysis), "--evidence-root", str(evidence_root)])
    preflight = run_checked(preflight_command, cwd=ROOT)
    return [guard, preflight]


def run(command: list[str], cwd: Path | None = None) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(command, cwd=cwd, text=True)
    elapsed_ms = round((time.monotonic() - started) * 1000)
    record = {"command": command, "exit_code": result.returncode, "elapsed_ms": elapsed_ms}
    if result.returncode:
        raise CommandError(record, f"command failed ({result.returncode}): {' '.join(command)}")
    return record


def write_run_record(project: Path, stage: str, commands: list[dict[str, Any]]) -> None:
    path = project / "validation" / "quick_run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"schema_version": "s4_ppt_quick_run.v1"}
    payload[stage] = {"commands": commands, "total_elapsed_ms": sum(item["elapsed_ms"] for item in commands)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def project_name_and_parent(requested: Path) -> tuple[str, Path]:
    if not requested.name or requested.name in {".", ".."}:
        raise ValueError("Quick project path needs a directory name")
    return requested.name, requested.parent


def imported_path(project: Path, source: Path, used: set[Path]) -> Path:
    matches = [
        path for path in (project / "sources").glob(f"{source.stem}*{source.suffix}")
        if path not in used and sha256(path) == sha256(source)
    ]
    if not matches:
        raise RuntimeError(f"imported source cannot be uniquely verified: {source.name}")
    return min(matches, key=lambda path: (len(path.name), path.name))


def validate_quick_project(project: Path) -> dict[str, Any]:
    manifest_path = project / "sources" / "quick_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Quick project is missing sources/quick_manifest.json; run prepare first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "s4_ppt_quick_project.v1":
        raise ValueError("invalid Quick project manifest")
    required = ("analysis", "markdown", "evidence", "allowed_sources", "excluded_sources", "snapshot_id", "key_queries")
    if any(key not in manifest for key in required):
        raise ValueError("Quick project manifest is incomplete")
    if not isinstance(manifest["allowed_sources"], list) or not isinstance(manifest["excluded_sources"], list):
        raise ValueError("Quick project manifest source policies must be arrays")
    if any(not isinstance(source, str) or not source for source in manifest["allowed_sources"] + manifest["excluded_sources"]):
        raise ValueError("Quick project manifest source policies must contain non-empty strings")
    if set(manifest["allowed_sources"]) & set(manifest["excluded_sources"]):
        raise ValueError("Quick project manifest has overlapping source policies")
    entries = [manifest["analysis"], manifest["markdown"], *manifest["evidence"]]
    expected_paths: set[str] = {"quick_manifest.json"}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("sha256"), str):
            raise ValueError("Quick project manifest has an invalid source entry")
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.name != entry["path"]:
            raise ValueError("Quick project source path must be a filename")
        expected_paths.add(relative.name)
        path = project / "sources" / entry["path"]
        if not path.is_file() or sha256(path) != entry["sha256"]:
            raise ValueError(f"Quick project source changed or missing: {entry['path']}")
    actual_paths = {path.name for path in (project / "sources").iterdir() if path.is_file()}
    unexpected = sorted(actual_paths - expected_paths)
    if unexpected:
        raise ValueError("Quick project contains unapproved sources: " + ", ".join(unexpected))
    for evidence in manifest["evidence"]:
        if not isinstance(evidence.get("source_id"), str) or evidence["source_id"] not in manifest["allowed_sources"]:
            raise ValueError(f"Quick project evidence source is not allowed: {evidence['source_id']}")
        payload = json.loads((project / "sources" / evidence["path"]).read_text(encoding="utf-8"))
        if payload.get("snapshot_id") != manifest["snapshot_id"]:
            raise ValueError(f"Quick project evidence snapshot mismatch: {evidence['path']}")
        referenced_source_ids = payload.get("referenced_source_ids")
        if not isinstance(referenced_source_ids, list) or not referenced_source_ids:
            raise ValueError(f"Quick project evidence source provenance missing: {evidence['path']}")
        if evidence["source_id"] not in referenced_source_ids:
            raise ValueError(f"Quick project evidence source provenance does not include declared source: {evidence['path']}")
        unapproved = sorted(set(referenced_source_ids) - set(manifest["allowed_sources"]))
        if unapproved:
            raise ValueError(f"Quick project evidence source provenance is not allowed: {evidence['path']}: {', '.join(unapproved)}")
    evidence_paths = {evidence["path"] for evidence in manifest["evidence"]}
    if not isinstance(manifest["key_queries"], list) or not manifest["key_queries"]:
        raise ValueError("Quick project manifest key_queries must be a non-empty array")
    if any(not isinstance(path, str) or path not in evidence_paths for path in manifest["key_queries"]):
        raise ValueError("Quick project manifest key_queries must reference listed evidence paths")
    return manifest


def validate_quick_svg_assets(project: Path) -> None:
    """Keep the local static Quick profile free of media and motion inputs."""
    violations: list[str] = []
    animation_tags = {"animate", "animateMotion", "animateTransform", "set"}
    media_tags = {"image", "audio", "video", "foreignObject"}
    for path in sorted((project / "svg_output").glob("*.svg")):
        try:
            root = ElementTree.parse(path).getroot()
        except ElementTree.ParseError as exc:
            raise ValueError(f"invalid Quick SVG: {path.name}: {exc}") from exc
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag in media_tags:
                violations.append(f"{path.name}: <{tag}> is not allowed in local static Quick")
            if tag in animation_tags:
                violations.append(f"{path.name}: <{tag}> is not allowed in local static Quick")
            if tag == "style" and element.text:
                style_text = element.text.lower()
                if "@keyframes" in style_text or "animation" in style_text or "url(" in style_text:
                    violations.append(f"{path.name}: style animation or resource is not allowed")
            for key, value in element.attrib.items():
                attribute = key.rsplit("}", 1)[-1].lower()
                text = value.strip().lower()
                if attribute.startswith("on") or attribute.startswith("data-pptx-animation") or "animation" in attribute:
                    violations.append(f"{path.name}: animation or event attribute {attribute} is not allowed")
                if attribute == "style" and ("animation" in text or "url(" in text):
                    violations.append(f"{path.name}: style animation or resource is not allowed")
                if attribute in {"href", "src"} and (text.startswith(("http:", "https:", "//", "data:"))):
                    violations.append(f"{path.name}: external or embedded resource is not allowed")
    if violations:
        raise ValueError("Quick SVG violates local static policy: " + "; ".join(violations))


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    requested = Path(args.project).resolve()
    analysis = Path(args.analysis).resolve()
    markdown = Path(args.markdown).resolve()
    evidence_root = Path(args.evidence_root).resolve()
    if not analysis.is_file() or not markdown.is_file():
        raise ValueError("analysis JSON and Markdown files must exist")
    commands = run_guard_preflight()
    identity = validate_frozen_analysis(analysis, evidence_root)
    name, parent = project_name_and_parent(requested)
    parent.mkdir(parents=True, exist_ok=True)
    existing = {path.resolve() for path in parent.glob(f"{name}_{args.format}_*")}
    commands.append(run([sys.executable, str(SKILL / "scripts/project_manager.py"), "init", name, "--dir", str(parent), "--format", args.format, "--quick-generate"]))
    created = sorted(path.resolve() for path in parent.glob(f"{name}_{args.format}_*") if path.resolve() not in existing)
    if len(created) != 1:
        raise RuntimeError("Quick project initialization did not create exactly one project directory")
    project = created[0]
    try:
        sources = [analysis, markdown] + [evidence_root / item["path"] for item in identity["evidence"]]
        commands.append(run([sys.executable, str(SKILL / "scripts/project_manager.py"), "import-sources", str(project), *map(str, sources)]))
        used_imports: set[Path] = set()
        imported_analysis = imported_path(project, analysis, used_imports)
        used_imports.add(imported_analysis)
        imported_markdown = imported_path(project, markdown, used_imports)
        used_imports.add(imported_markdown)
        imported_evidence = []
        imported_evidence_paths: dict[str, str] = {}
        for evidence in identity["evidence"]:
            imported = imported_path(project, evidence_root / evidence["path"], used_imports)
            used_imports.add(imported)
            imported_evidence.append({"path": imported.name, "sha256": sha256(imported), "source_id": evidence["source_id"]})
            imported_evidence_paths[evidence["path"]] = imported.name
        quick_manifest = {
            "schema_version": "s4_ppt_quick_project.v1",
            "snapshot_id": identity["snapshot_id"],
            "allowed_sources": identity["allowed_sources"],
            "excluded_sources": identity["excluded_sources"],
            "key_queries": [imported_evidence_paths[path] for path in identity["key_queries"]],
            "analysis": {"path": imported_analysis.name, "sha256": sha256(imported_analysis)},
            "markdown": {"path": imported_markdown.name, "sha256": sha256(imported_markdown)},
            "evidence": imported_evidence,
        }
        (project / "sources" / "quick_manifest.json").write_text(json.dumps(quick_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except CommandError as exc:
        commands.append(exc.record)
        write_run_record(project, "prepare", commands)
        raise
    write_run_record(project, "prepare", commands)
    return {"status": "prepared", "project": str(project), "snapshot_id": identity["snapshot_id"], "evidence_count": len(identity["evidence"])}


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    project = Path(args.project).resolve()
    if not (project / "svg_output").is_dir():
        raise ValueError("Quick project is missing svg_output")
    forbidden = ("design_spec.md", "spec_lock.md", "confirm_ui", "live_preview", "notes", "svg_final")
    mixed = [name for name in forbidden if (project / name).exists()]
    if mixed:
        raise ValueError("Quick project contains Default artifacts: " + ", ".join(mixed))
    validate_quick_project(project)
    validate_quick_svg_assets(project)
    commands: list[dict[str, Any]] = []
    try:
        checker = [sys.executable, str(SKILL / "scripts/svg_quality_checker.py"), str(project), "--quick-generate", "--stage", "final", "--json"]
        commands.append(run(checker))
        output = Path(args.output).resolve() if args.output else project / "exports" / f"{project.name}.pptx"
        output.parent.mkdir(parents=True, exist_ok=True)
        commands.append(run([sys.executable, str(SKILL / "scripts/svg_to_pptx.py"), str(project), "--quick-generate", "--no-notes", "-o", str(output)]))
    except CommandError as exc:
        commands.append(exc.record)
        write_run_record(project, "finalize", commands)
        raise
    write_run_record(project, "finalize", commands)
    return {"status": "exported", "project": str(project), "pptx": str(output)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("project")
    prep.add_argument("--analysis", required=True)
    prep.add_argument("--markdown", required=True)
    prep.add_argument("--evidence-root", required=True)
    prep.add_argument("--format", default="ppt169")
    final = sub.add_parser("finalize")
    final.add_argument("project")
    final.add_argument("--output")
    args = parser.parse_args()
    try:
        result = prepare(args) if args.command == "prepare" else finalize(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
