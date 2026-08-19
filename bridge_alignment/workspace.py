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
        "bridge_reference": root / "Work" / "Bridge" / "reference.json",
        "input_data": root / "Input" / "Data",
        "input_reference": root / "Input" / "Reference",
        "runs": root / "Work" / "Runs",
        "sessions": root / "Work" / "Sessions",
        "output_bridge": root / "Output" / "Bridge",
    }


def init_workspace(
    *, root: Path, company_id: str, pack_path: Path, existing_bridge_path: Path | None = None,
    business_port: str = "general",
) -> dict[str, Any]:
    paths = workspace_paths(root)
    if root.exists():
        raise AlignmentError("WORKSPACE_EXISTS", f"workspace already exists: {root}")
    if not ID_PATTERN.fullmatch(company_id):
        raise AlignmentError("COMPANY_ID_INVALID", "company_id must be a stable lowercase identifier")
    if not ID_PATTERN.fullmatch(business_port):
        raise AlignmentError("BUSINESS_PORT_INVALID", "business_port must be a stable lowercase identifier")
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
        bridge_ref = "Work/Bridge/reference.json"
    for directory in (
        paths["input_data"], paths["input_reference"], paths["runs"],
        paths["sessions"], paths["output_bridge"], paths["pack"].parent,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pack_path, paths["pack"])
    if existing_bridge_path is not None:
        paths["bridge_reference"].parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(existing_bridge_path, paths["bridge_reference"])
    config = {
        "schema_version": "bridge_alignment_workspace.v1",
        "company_id": company_id,
        "business_port": business_port,
        "pack_path": "Work/Pack/pack.json",
        "pack_ref": {"pack_id": pack["pack_id"], "pack_version": pack["pack_version"]},
        "bridge_reference_path": bridge_ref,
        "current_snapshot_id": None,
        "current_warehouse_path": None,
        "used_snapshot_ids": [],
    }
    write_json(paths["config"], config, overwrite=False)
    return {
        "schema_version": "bridge_alignment_result.v1",
        "status": "workspace_ready",
        "workspace": str(root.resolve()),
        "company_id": company_id,
        "business_port": business_port,
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


def _active_sessions(paths: dict[str, Path], snapshot_id: str | None) -> list[str]:
    if snapshot_id is None:
        return []
    active = []
    for session_path in sorted(paths["sessions"].glob("*/session.json")):
        session = load_json(session_path)
        if session.get("snapshot_id") == snapshot_id and session.get("status") != "completed":
            active.append(str(session.get("session_id") or session_path.parent.name))
    return active


def _current_run_root(root: Path, paths: dict[str, Path], config: dict[str, Any]) -> Path | None:
    warehouse_path = config.get("current_warehouse_path")
    snapshot_id = config.get("current_snapshot_id")
    if warehouse_path is None and snapshot_id is None:
        return None
    relative = Path(str(warehouse_path))
    parts = relative.parts
    if (
        relative.is_absolute()
        or len(parts) != 7
        or parts[:2] != ("Work", "Runs")
        or parts[2].startswith("run_") is False
        or parts[3:5] != ("data", "snapshots")
        or parts[5] != snapshot_id
        or parts[6] != "warehouse.duckdb"
    ):
        raise AlignmentError("WORKSPACE_INVALID", "current warehouse pointer is invalid")
    run_root = (root / Path(*parts[:3])).resolve()
    if run_root.parent != paths["runs"].resolve():
        raise AlignmentError("WORKSPACE_INVALID", "current Run path is outside workspace")
    return run_root


def sync_data(*, root: Path, snapshot_id: str) -> dict[str, Any]:
    paths, config = load_workspace(root)
    if not SNAPSHOT_PATTERN.fullmatch(snapshot_id):
        raise AlignmentError("SNAPSHOT_ID_INVALID", "snapshot_id is invalid")
    run_id = "run_" + snapshot_id.removeprefix("snapshot_")
    new_run_root = paths["runs"] / run_id
    new_snapshot_root = new_run_root / "data" / "snapshots" / snapshot_id
    if snapshot_id in config.get("used_snapshot_ids", []) or new_snapshot_root.exists():
        raise AlignmentError("SNAPSHOT_EXISTS", "snapshot already exists and cannot be overwritten")
    active_sessions = _active_sessions(paths, config.get("current_snapshot_id"))
    if active_sessions:
        raise AlignmentError(
            "ACTIVE_SESSION_EXISTS",
            f"complete the current Snapshot sessions before refreshing data: {', '.join(active_sessions)}",
        )
    old_run_root = _current_run_root(root, paths, config)
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
    config.pop("snapshot_history", None)
    config["used_snapshot_ids"] = [*config.get("used_snapshot_ids", []), snapshot_id]
    write_json(paths["config"], config)
    warnings = []
    if old_run_root is not None and old_run_root != new_run_root.resolve():
        try:
            shutil.rmtree(old_run_root)
        except OSError as exc:
            warnings.append(f"old Snapshot cleanup pending: {exc}")
    return {
        "schema_version": "bridge_alignment_result.v1",
        "status": "data_ready",
        "snapshot_id": snapshot_id,
        "warehouse": str((root / warehouse_relative).resolve()),
        "source_ids": sorted(slots),
        "warnings": warnings,
        "errors": [],
    }
