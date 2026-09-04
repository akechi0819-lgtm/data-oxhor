from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path
from typing import Any

from workspace_modeling.bridge_alignment.service import start_session
from workspace_modeling.bridge_alignment.workspace import (
    AlignmentError,
    ID_PATTERN,
    _source_slots,
    init_workspace,
    load_workspace,
    sync_data,
)
from workspace_modeling.business_pack.service import default_pack_path, load_pack, validate_pack
from workspace_modeling.casebook.router import guide


ONBOARDING_SCHEMA = "onboarding_result.v1"


class OnboardingError(AlignmentError):
    """A stable, machine-readable onboarding failure."""


def derive_company_id(root: Path) -> str:
    """Create an internal workspace identity without asking the user for a company name."""
    slug = re.sub(r"[^a-z0-9_.-]+", "-", root.name.lower()).strip("-._")
    return f"workspace_{(slug or 'customer')[:84]}"


def _result(*, status: str, next_step: str | None = None, **fields: Any) -> dict[str, Any]:
    return {
        "schema_version": ONBOARDING_SCHEMA,
        "status": status,
        "next_step": next_step,
        "pending_actions": [],
        "errors": [],
        **fields,
    }


def doctor(*, profile: str = "core", pack_path: Path | None = None) -> dict[str, Any]:
    if profile not in {"core", "full"}:
        raise OnboardingError("PROFILE_INVALID", "profile must be core or full")
    checks: list[dict[str, Any]] = []

    def check_module(name: str, import_name: str) -> None:
        available = importlib.util.find_spec(import_name) is not None
        checks.append({"name": name, "status": "passed" if available else "failed", "import": import_name})

    check_module("duckdb", "duckdb")
    if profile == "full":
        for name, import_name in (
            ("python-pptx", "pptx"), ("skia-pathops", "pathops"), ("uharfbuzz", "uharfbuzz"),
            ("openpyxl", "openpyxl"), ("Pillow", "PIL"), ("numpy", "numpy"),
            ("PyMuPDF", "fitz"), ("nbconvert", "nbconvert"), ("requests", "requests"),
        ):
            check_module(name, import_name)
    selected_pack = pack_path or default_pack_path()
    try:
        pack = load_pack(selected_pack)
        validation = validate_pack(pack)
        checks.append({"name": "business_pack", "status": validation["status"], "path": str(selected_pack.resolve())})
    except (OSError, ValueError, KeyError) as exc:
        checks.append({"name": "business_pack", "status": "failed", "path": str(selected_pack), "message": str(exc)})
    passed = all(item["status"] == "passed" for item in checks)
    return _result(status="doctor_passed" if passed else "doctor_failed", next_step="initialize_workspace" if passed else "install_runtime", profile=profile, checks=checks)


def import_data(*, root: Path, source_id: str, source_file: Path, replace: bool = False) -> dict[str, Any]:
    paths, _ = load_workspace(root)
    if not ID_PATTERN.fullmatch(source_id):
        raise OnboardingError("SOURCE_ID_INVALID", "source_id must be a stable lowercase identifier")
    if not source_file.is_file() or source_file.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise OnboardingError("SOURCE_FILE_INVALID", "source_file must be an existing XLSX/XLSM")
    slot = paths["input_data"] / source_id
    slot.mkdir(parents=True, exist_ok=True)
    existing = [path for path in slot.iterdir() if path.is_file() and not path.name.startswith("~$") and path.suffix.lower() in {".xlsx", ".xlsm"}]
    if existing and not replace:
        raise OnboardingError("SOURCE_EXISTS", f"source slot already contains a workbook: {source_id}; pass --replace to replace it")
    for path in existing:
        path.unlink()
    destination = slot / source_file.name
    shutil.copyfile(source_file, destination)
    return _result(status="data_imported", next_step="sync_snapshot", workspace=str(root.resolve()), source_id=source_id, source_file=str(destination.resolve()))


def status(*, root: Path) -> dict[str, Any]:
    try:
        paths, config = load_workspace(root)
    except AlignmentError as exc:
        return _result(status="not_initialized", next_step="initialize_workspace", workspace=str(root.resolve()), errors=exc.errors)
    source_ids: list[str] = []
    source_error: dict[str, Any] | None = None
    try:
        source_ids = sorted(_source_slots(paths["input_data"]))
    except AlignmentError as exc:
        source_error = exc.errors[0]
    routed = guide(root=root)
    next_step = routed.get("next_step")
    if source_error and not config.get("current_snapshot_id"):
        next_step = "import_data"
    return _result(
        status="ready" if next_step == "analyze" else "in_progress",
        next_step=next_step,
        workspace=str(root.resolve()),
        company_id=config.get("company_id"),
        business_port=config.get("business_port", "general"),
        pack_ref=config.get("pack_ref"),
        snapshot_id=config.get("current_snapshot_id"),
        bridge_reference_path=config.get("bridge_reference_path"),
        source_ids=source_ids,
        source_error=source_error,
        route=routed,
    )


def sync(*, root: Path, snapshot_id: str) -> dict[str, Any]:
    result = sync_data(root=root, snapshot_id=snapshot_id)
    payload = {key: value for key, value in result.items() if key not in {"schema_version", "status", "errors"}}
    return _result(status="snapshot_ready", next_step="align_bridge", workspace=str(root.resolve()), errors=result.get("errors", []), **payload)


def handoff(*, root: Path, session_id: str | None = None) -> dict[str, Any]:
    paths, config = load_workspace(root)
    if not config.get("current_snapshot_id"):
        raise OnboardingError("CURRENT_SNAPSHOT_MISSING", "run sync before creating an onboarding handoff")
    session_result: dict[str, Any] | None = None
    if session_id is not None:
        session_path = paths["sessions"] / session_id / "session.json"
        if session_path.exists():
            from workspace_modeling.bridge_alignment.workspace import load_json
            session = load_json(session_path)
            if session.get("snapshot_id") != config.get("current_snapshot_id"):
                raise OnboardingError("SESSION_STALE", "session does not belong to the current Snapshot")
            session_result = {"session_id": session["session_id"], "session_path": str(session_path.resolve()), "status": session["status"], "pending_questions": session.get("questions", [])}
        else:
            session_result = start_session(root=root, session_id=session_id)
    else:
        sessions = sorted(paths["sessions"].glob("*/session.json"))
        current = []
        for path in sessions:
            from workspace_modeling.bridge_alignment.workspace import load_json
            session = load_json(path)
            if session.get("snapshot_id") == config.get("current_snapshot_id") and session.get("status") != "completed":
                current.append(session)
        if current:
            session = current[0]
            session_result = {"session_id": session["session_id"], "session_path": str((root / "Work" / "Sessions" / session["session_id"] / "session.json").resolve()), "status": session["status"], "pending_questions": session.get("questions", [])}
    routed = guide(root=root)
    next_step = "align_bridge" if not config.get("bridge_reference_path") else routed.get("next_step")
    return _result(
        status="handoff_ready",
        next_step=next_step,
        workspace=str(root.resolve()),
        company_id=config.get("company_id"),
        business_port=config.get("business_port", "general"),
        snapshot_id=config.get("current_snapshot_id"),
        session=session_result,
        host_actions=["读取 Snapshot profile 与 quality", "由宿主 Agent 提出 proposed Bridge 候选", "向用户确认关键问题", "通过 bridge-alignment-wizard answer/finalize 提交确认"],
        route=routed,
    )


__all__ = ["OnboardingError", "derive_company_id", "doctor", "import_data", "status", "sync", "handoff", "init_workspace"]
