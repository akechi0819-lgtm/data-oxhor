from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from business_pack.service import load_pack, validate_pack
from company_bridge.service import load_bridge, validate_bridge
from data_foundation.connectors.xlsx import sha256_file
from interfaces.data_foundation import ingest_sources


ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,95}$")
SNAPSHOT_PATTERN = re.compile(r"^snapshot_[a-z0-9][a-z0-9_-]{2,62}$")


class AlignmentError(ValueError):
    def __init__(
        self, code: str, message: str, *, path: str = "$",
        session_id: str | None = None, pending_questions: list[dict[str, Any]] | None = None,
        disabled_capabilities: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.errors = [{"code": code, "path": path, "message": message}]
        self.session_id = session_id
        self.pending_questions = pending_questions or []
        self.disabled_capabilities = disabled_capabilities or []


def write_json(path: Path, document: dict[str, Any], *, overwrite: bool = True) -> None:
    if path.exists() and not overwrite:
        raise AlignmentError("OUTPUT_EXISTS", f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AlignmentError("FILE_NOT_FOUND", str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise AlignmentError("JSON_INVALID", str(exc)) from exc
    if not isinstance(value, dict):
        raise AlignmentError("TYPE_INVALID", f"JSON object required: {path}")
    return value


def workspace_paths(root: Path) -> dict[str, Path]:
    return {
        "root": root,
        "config": root / "Work" / "workspace.json",
        "pack": root / "Work" / "Pack" / "pack.json",
        "current_bridge": root / "Work" / "Bridge" / "current.json",
        "input_data": root / "Input" / "Data",
        "input_reference": root / "Input" / "Reference",
        "runs": root / "Work" / "Runs",
        "sessions": root / "Work" / "Sessions",
        "output_bridge": root / "Output" / "Bridge",
    }


def init_workspace(
    *, root: Path, company_id: str, pack_path: Path, existing_bridge_path: Path | None = None,
) -> dict[str, Any]:
    paths = workspace_paths(root)
    if root.exists():
        raise AlignmentError("WORKSPACE_EXISTS", f"workspace already exists: {root}")
    if not ID_PATTERN.fullmatch(company_id):
        raise AlignmentError("COMPANY_ID_INVALID", "company_id must be a stable lowercase identifier")
    pack = load_pack(pack_path)
    if validate_pack(pack)["status"] != "passed":
        raise AlignmentError("PACK_INVALID", "Pack failed validation")
    bridge_ref = None
    if existing_bridge_path is not None:
        bridge = load_bridge(existing_bridge_path)
        if validate_bridge(bridge, pack=pack)["status"] != "passed":
            raise AlignmentError("EXISTING_BRIDGE_INVALID", "existing Bridge failed validation")
        if bridge.get("company_id") != company_id:
            raise AlignmentError("EXISTING_BRIDGE_COMPANY_MISMATCH", "existing Bridge belongs to a different company")
        bridge_ref = "Work/Bridge/current.json"
    for directory in (
        paths["input_data"], paths["input_reference"], paths["runs"],
        paths["sessions"], paths["output_bridge"], paths["pack"].parent,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pack_path, paths["pack"])
    if existing_bridge_path is not None:
        paths["current_bridge"].parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(existing_bridge_path, paths["current_bridge"])
    config = {
        "schema_version": "bridge_alignment_workspace.v1",
        "company_id": company_id,
        "pack_path": "Work/Pack/pack.json",
        "pack_ref": {"pack_id": pack["pack_id"], "pack_version": pack["pack_version"]},
        "current_bridge_path": bridge_ref,
        "current_snapshot_id": None,
        "current_warehouse_path": None,
        "snapshot_history": [],
    }
    write_json(paths["config"], config, overwrite=False)
    return {
        "schema_version": "bridge_alignment_result.v1",
        "status": "workspace_ready",
        "workspace": str(root.resolve()),
        "input_data": str(paths["input_data"].resolve()),
        "input_reference": str(paths["input_reference"].resolve()),
        "output_bridge": str(paths["output_bridge"].resolve()),
        "errors": [],
    }


def load_workspace(root: Path) -> tuple[dict[str, Path], dict[str, Any]]:
    paths = workspace_paths(root)
    config = load_json(paths["config"])
    if config.get("schema_version") != "bridge_alignment_workspace.v1":
        raise AlignmentError("WORKSPACE_INVALID", "unsupported workspace schema")
    return paths, config


def _source_slots(input_data: Path) -> dict[str, Path]:
    slots: dict[str, Path] = {}
    for directory in sorted(path for path in input_data.iterdir() if path.is_dir() and not path.name.startswith(".")):
        if not ID_PATTERN.fullmatch(directory.name):
            raise AlignmentError("SOURCE_ID_INVALID", f"invalid source directory: {directory.name}")
        workbooks = sorted(
            path for path in directory.iterdir()
            if path.is_file() and not path.name.startswith("~$") and path.suffix.lower() in {".xlsx", ".xlsm"}
        )
        if len(workbooks) != 1:
            raise AlignmentError("SOURCE_SLOT_INVALID", f"{directory.name} must contain exactly one XLSX/XLSM")
        slots[directory.name] = workbooks[0]
    if not slots:
        raise AlignmentError("SOURCE_SLOTS_EMPTY", "Input/Data must contain at least one source directory")
    return slots


def sync_data(*, root: Path, snapshot_id: str) -> dict[str, Any]:
    paths, config = load_workspace(root)
    if not SNAPSHOT_PATTERN.fullmatch(snapshot_id):
        raise AlignmentError("SNAPSHOT_ID_INVALID", "snapshot_id is invalid")
    if snapshot_id in config["snapshot_history"]:
        raise AlignmentError("SNAPSHOT_EXISTS", "snapshot_id already exists in workspace history")
    slots = _source_slots(paths["input_data"])
    manifest = {
        "sources": {
            source_id: {"filename": path.name, "sha256": sha256_file(path)}
            for source_id, path in slots.items()
        }
    }
    import_dir = paths["runs"] / "_imports" / snapshot_id
    manifest_path = import_dir / "manifest.json"
    write_json(manifest_path, manifest, overwrite=False)
    run_id = "run_" + snapshot_id.removeprefix("snapshot_")
    try:
        result = ingest_sources(
            run_id=run_id,
            snapshot_id=snapshot_id,
            output_root=paths["runs"],
            manifest_path=manifest_path,
            source_values=[f"{source_id}={path}" for source_id, path in slots.items()],
        )
    finally:
        shutil.rmtree(import_dir, ignore_errors=True)
    if result["status"] != "passed":
        error = result["errors"][0]
        raise AlignmentError(error["code"], error["message"])
    warehouse_relative = Path("Work") / "Runs" / run_id / "data" / "snapshots" / snapshot_id / "warehouse.duckdb"
    config["current_snapshot_id"] = snapshot_id
    config["current_warehouse_path"] = warehouse_relative.as_posix()
    config["snapshot_history"].append(snapshot_id)
    write_json(paths["config"], config)
    return {
        "schema_version": "bridge_alignment_result.v1",
        "status": "data_ready",
        "snapshot_id": snapshot_id,
        "warehouse": str((root / warehouse_relative).resolve()),
        "source_ids": sorted(slots),
        "errors": [],
    }
