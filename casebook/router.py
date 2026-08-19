"""Read-only workspace guidance and repeat-problem suggestions for S5.3."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from bridge_alignment.profile import profile_snapshot
from bridge_alignment.workspace import AlignmentError, load_json, load_workspace
from business_pack.service import load_pack
from company_bridge.service import load_bridge, validate_bridge

from .service import CasebookError, _validate_case

__all__ = ["RouterError", "guide", "repeat_candidates"]


ROUTER_SCHEMA = "casebook_router_result.v1"
EVALUATION_SCHEMA = "pilot_evaluation.v1"


class RouterError(AlignmentError):
    """A stable, machine-readable error from the local router."""


def _error(code: str, message: str, *, path: str = "$") -> None:
    raise RouterError(code, message, path=path)


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _workspace_file(root: Path, pointer: Any, *, field: str) -> Path:
    if not isinstance(pointer, str) or not pointer:
        _error("WORKSPACE_POINTER_INVALID", f"{field} must be a non-empty relative path", path=f"$.{field}")
    relative = Path(pointer)
    if relative.is_absolute():
        _error("PATH_OUTSIDE_WORKSPACE", f"{field} must be workspace-relative", path=f"$.{field}")
    raw_path = root / relative
    if raw_path.is_symlink():
        _error("PATH_OUTSIDE_WORKSPACE", f"{field} may not be a symbolic link", path=f"$.{field}")
    resolved = raw_path.resolve()
    if not resolved.is_file() or not _inside(root, resolved):
        _error("PATH_OUTSIDE_WORKSPACE", f"{field} must name a file inside the workspace", path=f"$.{field}")
    return resolved


def _load_valid_workspace(root: Path) -> tuple[dict[str, Path], dict[str, Any]] | None:
    """A missing or invalid workspace is a guide result, not a router failure."""
    try:
        return load_workspace(root)
    except AlignmentError:
        return None


def _result(*, next_step: str, guidance: str, snapshot_id: str | None = None, bridge: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": ROUTER_SCHEMA,
        "status": "guide_completed",
        "next_step": next_step,
        "snapshot_id": snapshot_id,
        "guidance": guidance,
        "bridge": bridge,
        "errors": [],
    }


def guide(*, root: Path) -> dict[str, Any]:
    """Return the single highest-priority local next step without changing state."""
    loaded = _load_valid_workspace(root)
    if loaded is None:
        return _result(
            next_step="initialize_workspace",
            guidance="Initialize Input, Work, and Output and select a Pack before continuing.",
        )
    _, config = loaded
    if not isinstance(config.get("company_id"), str) or not config.get("company_id") or not isinstance(config.get("pack_ref"), dict):
        return _result(
            next_step="initialize_workspace",
            guidance="The workspace configuration is incomplete; initialize Input, Work, and Output and select a Pack.",
        )
    snapshot_id = config.get("current_snapshot_id")
    warehouse_pointer = config.get("current_warehouse_path")
    if not isinstance(snapshot_id, str) or not snapshot_id or not isinstance(warehouse_pointer, str) or not warehouse_pointer:
        return _result(
            next_step="sync_data",
            guidance="Place stable source files in the existing input slots and run sync-data.",
        )

    try:
        pack = load_pack(_workspace_file(root, config.get("pack_path"), field="pack_path"))
        warehouse = _workspace_file(root, warehouse_pointer, field="current_warehouse_path")
    except (AlignmentError, OSError, ValueError, duckdb.Error):
        if not isinstance(config.get("pack_path"), str) or not (root / config["pack_path"]).is_file():
            return _result(
                next_step="initialize_workspace",
                guidance="The workspace Pack pointer is not usable; initialize the workspace and select a Pack.",
                snapshot_id=snapshot_id,
            )
        return _result(
            next_step="sync_data",
            guidance="The current Snapshot pointers are not usable; place stable source files in the input slots and run sync-data.",
            snapshot_id=snapshot_id,
        )

    bridge_pointer = config.get("current_bridge_path") or config.get("bridge_reference_path")
    if not isinstance(bridge_pointer, str) or not bridge_pointer:
        return _result(
            next_step="align_bridge",
            guidance="Start the existing start -> propose -> answer -> finalize Bridge alignment flow before semantic analysis.",
            snapshot_id=snapshot_id,
        )
    try:
        bridge = load_bridge(_workspace_file(root, bridge_pointer, field="current_bridge_path"))
        # profile_snapshot uses the existing controlled Snapshot describe and quality logic read-only.
        _, description, quality = profile_snapshot(
            warehouse=warehouse,
            snapshot_id=snapshot_id,
            company_id=config["company_id"],
            pack_ref=config["pack_ref"],
        )
        validation = validate_bridge(bridge, pack=pack, description=description, quality=quality)
        if validation["status"] != "passed" or bridge.get("company_id") != config.get("company_id"):
            return _result(
                next_step="align_bridge",
                guidance="The explicit Bridge does not validate for the current Snapshot; complete the existing alignment flow before semantic analysis.",
                snapshot_id=snapshot_id,
                bridge={"status": "failed", "errors": validation.get("errors", [])},
            )
    except (AlignmentError, OSError, ValueError, KeyError, duckdb.Error):
        return _result(
            next_step="align_bridge",
            guidance="No usable explicit Bridge is available for the current Snapshot; complete the existing alignment flow before semantic analysis.",
            snapshot_id=snapshot_id,
        )
    return _result(
        next_step="analyze",
        guidance=(
            "Proceed with analysis, Casebook lookup, and delivery. Casebook matches are leads only; "
            "current numbers must be established with controlled read-only queries on the current Snapshot."
        ),
        snapshot_id=snapshot_id,
        bridge={"status": "passed", "bridge_id": bridge.get("bridge_id"), "bridge_version": bridge.get("bridge_version")},
    )


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        _error("TIMESTAMP_INVALID", f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RouterError("TIMESTAMP_INVALID", f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        _error("TIMESTAMP_INVALID", f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _case_token(case_id: str) -> str:
    # Evaluations retain a SHA-256 case identifier so feedback exports do not disclose a case name.
    return hashlib.sha256(case_id.encode("utf-8")).hexdigest()


def _manual_evaluation_case_tokens(root: Path, company_id: str) -> dict[str, set[str]]:
    tokens: dict[str, set[str]] = {}
    sessions = root / "Work" / "Evaluation" / "sessions"
    if not sessions.is_dir():
        return tokens
    for path in sorted(sessions.glob("*/evaluation.json")):
        if path.is_symlink() or not _inside(root, path):
            _error("PATH_OUTSIDE_WORKSPACE", "evaluation path escapes the workspace")
        document = load_json(path)
        if (
            document.get("schema_version") != EVALUATION_SCHEMA
            or document.get("status") != "completed"
            or document.get("company_id") != company_id
            or not isinstance(document.get("evaluation_id"), str)
            or not isinstance(document.get("cards"), list)
        ):
            continue
        evaluation_id = document["evaluation_id"]
        for card in document["cards"]:
            if not isinstance(card, dict):
                continue
            feedback = card.get("feedback")
            score = card.get("score")
            # Evaluation records use raw case IDs locally; exported feedback may retain only their SHA-256 tokens.
            if (
                not isinstance(feedback, str)
                or not feedback.strip()
                or not isinstance(card.get("reviewed_by"), str)
                or not card["reviewed_by"].strip()
                or not isinstance(card.get("reviewed_at"), str)
                or not card["reviewed_at"].strip()
                or (card.get("acceptance") is None and score is None)
            ):
                continue
            matched = card.get("matched_case_ids")
            if not isinstance(matched, list):
                continue
            for token in matched:
                if isinstance(token, str) and token:
                    tokens.setdefault(token, set()).add(evaluation_id)
    return tokens


def repeat_candidates(*, root: Path, now: datetime | None = None) -> dict[str, Any]:
    """Suggest, but never create, a Skill/template candidate for repeated evaluated cases."""
    loaded = _load_valid_workspace(root)
    if loaded is None:
        _error("WORKSPACE_INVALID", "repeat-candidates requires a valid initialized workspace")
    _, config = loaded
    company_id = config.get("company_id")
    if not isinstance(company_id, str) or not company_id:
        _error("WORKSPACE_INVALID", "workspace company_id is invalid")
    reference_time = now or datetime.now(UTC)
    if reference_time.tzinfo is None:
        _error("TIMESTAMP_INVALID", "now must include a timezone")
    threshold_time = reference_time.astimezone(UTC) - timedelta(days=90)
    evaluation_tokens = _manual_evaluation_case_tokens(root, company_id)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    confirmed = root / "Work" / "Casebook" / "confirmed"
    if confirmed.is_dir():
        for path in sorted(confirmed.glob("*/case.json")):
            case_path = path.parent
            if case_path.is_symlink() or path.is_symlink() or not _inside(root, case_path):
                _error("PATH_OUTSIDE_WORKSPACE", "Casebook path escapes the workspace")
            document = load_json(path)
            try:
                _validate_case(document, case_path=case_path, expected_status="confirmed")
            except CasebookError as exc:
                raise RouterError(exc.code, str(exc), path=exc.errors[0]["path"]) from exc
            if document["company_id"] != company_id:
                continue
            decided_at = _parse_timestamp(document.get("decided_at"), field="decided_at")
            if decided_at < threshold_time:
                continue
            case_id = document["case_id"]
            evaluation_ids = evaluation_tokens.get(case_id, set()) | evaluation_tokens.get(_case_token(case_id), set())
            if not evaluation_ids:
                continue
            grouped.setdefault((document["primary_role"], document["question_category"]), []).append({
                "case_id": case_id,
                "confirmed_at": decided_at.isoformat().replace("+00:00", "Z"),
                "evaluation_ids": sorted(evaluation_ids),
            })
    candidates = [
        {
            "suggestion": "skill_or_template_candidate",
            "primary_role": role,
            "question_category": category,
            "case_count": len(cases),
            "case_ids": [case["case_id"] for case in cases],
            "evaluation_ids": sorted({evaluation_id for case in cases for evaluation_id in case["evaluation_ids"]}),
            "window_days": 90,
            "skill_draft": {
                "schema_version": "skill_candidate_draft.v1",
                "title": f"{category} analysis for {role}",
                "purpose": f"Repeatable {category} analysis workflow for the {role} role.",
                "reusable_steps": [
                    "Inspect the current Snapshot and validated Bridge.",
                    "Search confirmed Casebook cases for method references.",
                    "Re-run controlled read-only queries against the current Snapshot.",
                    "State evidence, limits, and the requested delivery format.",
                ],
                "evidence_requirements": ["current_snapshot", "validated_bridge", "controlled_query_result"],
                "forbidden_conclusions": ["Treat historical case numbers as current facts."],
                "source_cases": [case["case_id"] for case in cases],
            },
        }
        for (role, category), cases in sorted(grouped.items())
        if len(cases) >= 3
    ]
    return {
        "schema_version": ROUTER_SCHEMA,
        "status": "repeat_candidates_completed",
        "candidates": candidates,
        "errors": [],
    }
