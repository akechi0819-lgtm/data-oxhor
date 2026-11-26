"""Snapshot identity, source slots, and publication for the BI workspace."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from data_platform.connectors.xlsx import sha256_file
from interfaces.data_platform import ingest_sources


ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,95}$")
SNAPSHOT_PATTERN = re.compile(r"^snapshot_[a-z0-9][a-z0-9_-]{2,62}$")


class WorkspaceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def write_json(path: Path, document: dict[str, Any], *, overwrite: bool = True) -> None:
    if path.exists() and not overwrite:
        raise WorkspaceError("OUTPUT_EXISTS", f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise WorkspaceError("FILE_NOT_FOUND", str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise WorkspaceError("JSON_INVALID", str(exc)) from exc
    if not isinstance(value, dict):
        raise WorkspaceError("TYPE_INVALID", f"JSON object required: {path}")
    return value


def workspace_paths(root: Path) -> dict[str, Path]:
    return {"config": root / "Work/workspace.json", "input_data": root / "Input/Data",
            "runs": root / "Work/Runs"}


def init_workspace(*, root: Path, company_id: str, business_port: str = "operations") -> None:
    paths = workspace_paths(root)
    if not ID_PATTERN.fullmatch(company_id):
        raise WorkspaceError("COMPANY_ID_INVALID", "company_id must be a stable lowercase identifier")
    paths["input_data"].mkdir(parents=True, exist_ok=True)
    write_json(paths["config"], {
        "schema_version": "bridge_alignment_workspace.v1", "company_id": company_id,
        "business_port": business_port, "current_snapshot_id": None,
        "current_warehouse_path": None, "used_snapshot_ids": [],
    }, overwrite=False)


def load_workspace(root: Path) -> tuple[dict[str, Path], dict[str, Any]]:
    paths = workspace_paths(root)
    config = load_json(paths["config"])
    if config.get("schema_version") != "bridge_alignment_workspace.v1":
        raise WorkspaceError("WORKSPACE_INVALID", "unsupported workspace schema")
    return paths, config


def _source_slots(input_data: Path) -> dict[str, Path]:
    slots: dict[str, Path] = {}
    for directory in sorted(path for path in input_data.iterdir() if path.is_dir() and not path.name.startswith(".")):
        if not ID_PATTERN.fullmatch(directory.name):
            raise WorkspaceError("SOURCE_ID_INVALID", f"invalid source directory: {directory.name}")
        workbooks = sorted(
            path for path in directory.iterdir()
            if path.is_file() and not path.name.startswith("~$") and path.suffix.lower() in {".xlsx", ".xlsm"}
        )
        if len(workbooks) != 1:
            raise WorkspaceError("SOURCE_SLOT_INVALID", f"{directory.name} must contain exactly one XLSX/XLSM")
        slots[directory.name] = workbooks[0]
    if not slots:
        raise WorkspaceError("SOURCE_SLOTS_EMPTY", "Input/Data must contain at least one source directory")
    return slots


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
        raise WorkspaceError("WORKSPACE_INVALID", "current warehouse pointer is invalid")
    run_root = (root / Path(*parts[:3])).resolve()
    if run_root.parent != paths["runs"].resolve():
        raise WorkspaceError("WORKSPACE_INVALID", "current Run path is outside workspace")
    return run_root


def _validate_sync_preconditions(
    *, root: Path, paths: dict[str, Path], config: dict[str, Any], snapshot_id: str,
) -> Path | None:
    if not SNAPSHOT_PATTERN.fullmatch(snapshot_id):
        raise WorkspaceError("SNAPSHOT_ID_INVALID", "snapshot_id is invalid")
    run_id = "run_" + snapshot_id.removeprefix("snapshot_")
    new_run_root = paths["runs"] / run_id
    new_snapshot_root = new_run_root / "data" / "snapshots" / snapshot_id
    if snapshot_id in config.get("used_snapshot_ids", []) or new_snapshot_root.exists():
        raise WorkspaceError("SNAPSHOT_EXISTS", "snapshot already exists and cannot be overwritten")
    return _current_run_root(root, paths, config)


def validate_sync_preconditions(*, root: Path, snapshot_id: str) -> None:
    """Check the same Snapshot/pointer constraints used by ``sync_data``."""
    paths, config = load_workspace(root)
    _validate_sync_preconditions(root=root, paths=paths, config=config, snapshot_id=snapshot_id)


def current_snapshot_root(root: Path) -> Path | None:
    """Return the configured current Snapshot directory after validating its pointer."""
    paths, config = load_workspace(root)
    snapshot_id = config.get("current_snapshot_id")
    run_root = _current_run_root(root, paths, config)
    if snapshot_id is None:
        return None
    if run_root is None:
        raise WorkspaceError("WORKSPACE_INVALID", "current warehouse pointer is missing")
    return run_root / "data" / "snapshots" / str(snapshot_id)


def sync_data(*, root: Path, snapshot_id: str) -> dict[str, Any]:
    paths, config = load_workspace(root)
    old_run_root = _validate_sync_preconditions(
        root=root, paths=paths, config=config, snapshot_id=snapshot_id,
    )
    run_id = "run_" + snapshot_id.removeprefix("snapshot_")
    new_run_root = paths["runs"] / run_id
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
        raise WorkspaceError(error["code"], error["message"])
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
        "status": "snapshot_ready",
        "snapshot_id": snapshot_id,
        "warehouse": str((root / warehouse_relative).resolve()),
        "source_ids": sorted(slots),
        "warnings": warnings,
        "errors": [],
    }
