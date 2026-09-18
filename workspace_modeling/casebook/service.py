from __future__ import annotations

import hashlib
import re
import shutil
import uuid
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from workspace_modeling.bridge_alignment.workspace import AlignmentError, ID_PATTERN, load_json, load_workspace, write_json
from workspace_modeling.company_bridge.service import load_bridge


CASE_STATUSES = {"candidate", "confirmed", "rejected", "superseded"}
EVIDENCE_KINDS = {"query_result", "sql", "artifact", "log", "delivery"}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class CasebookError(AlignmentError):
    """A stable, machine-readable Casebook contract error."""


def _error(code: str, message: str, *, path: str = "$") -> None:
    raise CasebookError(code, message, path=path)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _error("FIELD_REQUIRED", f"{field} must be a non-empty string", path=f"$.{field}")
    return value.strip()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _casebook_root(root: Path) -> Path:
    return root / "Work" / "Casebook"


def _status_root(root: Path, status: str) -> Path:
    return _casebook_root(root) / {
        "candidate": "candidates",
        "confirmed": "confirmed",
        "rejected": "rejected",
        "superseded": "superseded",
    }[status]


def _case_path(root: Path, status: str, case_id: str) -> Path:
    return _status_root(root, status) / case_id


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _workspace_file(root: Path, value: str, *, field: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        _error("PATH_OUTSIDE_WORKSPACE", f"{field} must be workspace-relative", path=f"$.{field}")
    path = root / candidate
    if not path.is_file() or not _inside(root, path):
        _error("PATH_OUTSIDE_WORKSPACE", f"{field} must name a file inside the workspace", path=f"$.{field}")
    return path


def _find_case(root: Path, case_id: str) -> tuple[Path, dict[str, Any]]:
    if not ID_PATTERN.fullmatch(case_id):
        _error("CASE_ID_INVALID", "case_id must be a stable lowercase identifier", path="$.case_id")
    matches = [path for status in CASE_STATUSES if (path := _case_path(root, status, case_id)).exists()]
    if not matches:
        _error("CASE_NOT_FOUND", f"case not found: {case_id}")
    if len(matches) != 1:
        _error("CASE_STATE_INVALID", f"case exists in multiple state directories: {case_id}")
    case_path = matches[0]
    if case_path.is_symlink() or not _inside(root, case_path):
        _error("PATH_OUTSIDE_WORKSPACE", "case directory escapes the workspace")
    document = load_json(case_path / "case.json")
    _validate_case(document, case_path=case_path, expected_status=_status_for_path(case_path))
    return case_path, document


def _status_for_path(case_path: Path) -> str:
    return {
        "candidates": "candidate",
        "confirmed": "confirmed",
        "rejected": "rejected",
        "superseded": "superseded",
    }.get(case_path.parent.name, "")


def _bridge_ref(root: Path, config: dict[str, Any]) -> dict[str, str]:
    bridge_path = config.get("current_bridge_path") or config.get("bridge_reference_path")
    if not isinstance(bridge_path, str) or not bridge_path:
        _error("BRIDGE_REFERENCE_MISSING", "workspace has no Bridge reference")
    bridge = load_bridge(_workspace_file(root, bridge_path, field="bridge_reference_path"))
    if bridge.get("company_id") != config.get("company_id"):
        _error("BRIDGE_COMPANY_MISMATCH", "Bridge reference belongs to a different company")
    bridge_id = _text(bridge.get("bridge_id"), "bridge_id")
    bridge_version = _text(bridge.get("bridge_version"), "bridge_version")
    return {"bridge_id": bridge_id, "bridge_version": bridge_version}


def _required_ref(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict):
        _error("TYPE_INVALID", f"{field} must be an object", path=f"$.{field}")
    required = ("pack_id", "pack_version") if field == "pack_ref" else ("bridge_id", "bridge_version")
    return {key: _text(value.get(key), f"{field}.{key}") for key in required}


def _validate_case(document: dict[str, Any], *, case_path: Path | None = None, expected_status: str | None = None) -> None:
    if document.get("schema_version") != "casebook_case.v1":
        _error("CASE_SCHEMA_INVALID", "unsupported Casebook schema")
    required = {
        "case_id", "company_id", "primary_role", "question_category", "status", "question",
        "normalized_question", "snapshot_id", "pack_ref", "bridge_ref", "key_queries", "evidence",
        "created_at", "created_by", "summary_sha256",
    }
    missing = required - set(document)
    if missing:
        _error("CASE_FIELDS_MISSING", f"case is missing required fields: {', '.join(sorted(missing))}")
    for field in required - {"pack_ref", "bridge_ref", "key_queries", "evidence"}:
        _text(document.get(field), field)
    if document["status"] not in CASE_STATUSES or (expected_status and document["status"] != expected_status):
        _error("CASE_STATE_INVALID", "case status does not match its directory")
    if not ID_PATTERN.fullmatch(document["case_id"]):
        _error("CASE_ID_INVALID", "case_id must be a stable lowercase identifier")
    for field in ("supersedes", "superseded_by"):
        if field in document and (not isinstance(document[field], str) or not ID_PATTERN.fullmatch(document[field])):
            _error("CASE_ID_INVALID", f"{field} must be a stable lowercase identifier")
    if not SHA256_PATTERN.fullmatch(document["summary_sha256"]):
        _error("SHA256_INVALID", "summary_sha256 must be a SHA-256 digest")
    _required_ref(document["pack_ref"], "pack_ref")
    _required_ref(document["bridge_ref"], "bridge_ref")
    if not isinstance(document["key_queries"], list):
        _error("TYPE_INVALID", "key_queries must be an array", path="$.key_queries")
    if not isinstance(document["evidence"], list) or not document["evidence"]:
        _error("EVIDENCE_REQUIRED", "evidence must be a non-empty array", path="$.evidence")
    for index, evidence in enumerate(document["evidence"]):
        if not isinstance(evidence, dict):
            _error("TYPE_INVALID", "evidence item must be an object", path=f"$.evidence[{index}]")
        if set(evidence) != {"path", "sha256", "kind", "referenced_source_ids"}:
            _error("EVIDENCE_FIELDS_INVALID", "evidence fields are invalid", path=f"$.evidence[{index}]")
        path = evidence["path"]
        digest = evidence["sha256"]
        kind = evidence["kind"]
        source_ids = evidence["referenced_source_ids"]
        relative_path = Path(path) if isinstance(path, str) else Path()
        if (
            not isinstance(path, str)
            or not path.startswith("evidence/")
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or relative_path.parts[:1] != ("evidence",)
            or len(relative_path.parts) < 2
        ):
            _error("EVIDENCE_PATH_INVALID", "evidence path must be relative to evidence/", path=f"$.evidence[{index}].path")
        if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
            _error("SHA256_INVALID", "evidence sha256 must be a SHA-256 digest", path=f"$.evidence[{index}].sha256")
        if kind not in EVIDENCE_KINDS:
            _error("EVIDENCE_KIND_INVALID", "evidence kind is unsupported", path=f"$.evidence[{index}].kind")
        if not isinstance(source_ids, list) or not all(isinstance(item, str) and item for item in source_ids):
            _error("SOURCE_IDS_INVALID", "referenced_source_ids must be an array of non-empty strings", path=f"$.evidence[{index}].referenced_source_ids")
        if kind != "artifact" and not source_ids:
            _error("SOURCE_IDS_REQUIRED", "non-artifact evidence requires referenced_source_ids", path=f"$.evidence[{index}].referenced_source_ids")
        if case_path is not None:
            file_path = case_path / path
            if not file_path.is_file() or file_path.is_symlink() or not _inside(case_path, file_path):
                _error("EVIDENCE_PATH_INVALID", "stored evidence is missing or unsafe", path=f"$.evidence[{index}].path")


def create_case(
    *, root: Path, case_id: str, primary_role: str, question_category: str, question: str,
    normalized_question: str, key_queries: list[Any], evidence_sources: list[dict[str, Any]],
    summary: str, created_by: str, created_at: str | None = None, supersedes: str | None = None,
) -> dict[str, Any]:
    paths, config = load_workspace(root)
    del paths
    if not ID_PATTERN.fullmatch(case_id):
        _error("CASE_ID_INVALID", "case_id must be a stable lowercase identifier", path="$.case_id")
    if not config.get("current_snapshot_id"):
        _error("CURRENT_SNAPSHOT_MISSING", "workspace has no current Snapshot")
    # Validate the explicit Bridge against the workspace Pack before binding it.
    from workspace_modeling.business_pack.service import load_pack
    from workspace_modeling.company_bridge.service import validate_bridge
    bridge_pointer = config.get("current_bridge_path") or config.get("bridge_reference_path")
    if not isinstance(bridge_pointer, str) or not bridge_pointer:
        _error("BRIDGE_REFERENCE_MISSING", "workspace has no Bridge reference")
    bridge = load_bridge(_workspace_file(root, bridge_pointer, field="bridge_reference_path"))
    pack = load_pack(_workspace_file(root, config["pack_path"], field="pack_path"))
    validation = validate_bridge(bridge, pack=pack)
    if validation["status"] != "passed" or bridge.get("company_id") != config.get("company_id"):
        _error("BRIDGE_NOT_READY", "explicit Bridge is invalid for the workspace Pack or company")
    # The router owns the existing Snapshot describe/quality compatibility gate.
    from workspace_modeling.casebook.router import guide
    if guide(root=root).get("next_step") != "analyze":
        _error("BRIDGE_NOT_READY", "current Snapshot requires a validated explicit Bridge before creating a Casebook case")
    if not isinstance(key_queries, list):
        _error("TYPE_INVALID", "key_queries must be an array", path="$.key_queries")
    if not isinstance(evidence_sources, list) or not evidence_sources:
        _error("EVIDENCE_REQUIRED", "evidence_sources must be a non-empty array", path="$.evidence_sources")
    for status in CASE_STATUSES:
        if _case_path(root, status, case_id).exists():
            _error("CASE_EXISTS", f"case already exists: {case_id}")
    final_path = _case_path(root, "candidate", case_id)
    case_path = final_path.parent / ("." + case_id + ".pending-" + uuid.uuid4().hex)
    case_path.mkdir(parents=True)
    try:
        evidence: list[dict[str, Any]] = []
        from workspace_modeling.delivery import context, verify_delivery
        from data_platform.query.evidence import EvidenceError
        expected = context(root, primary_role)
        for ordinal, source in enumerate(evidence_sources, start=1):
            if not isinstance(source, dict) or set(source) != {"path"}:
                _error("EVIDENCE_FIELDS_INVALID", "each evidence source must select one delivery manifest path")
            source_path = _workspace_file(root, source["path"], field="evidence_sources.path")
            delivery, closure = verify_delivery(source_path, expected=expected)
            package = case_path / "evidence" / f"delivery_{ordinal}"
            for source_file in closure:
                target = package / source_file.relative_to(source_path.parent)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_file, target)
            entry = package / source_path.name
            verify_delivery(entry, expected=expected)
            source_ids = set()
            from data_platform.query.evidence import resolve_file, verify_receipt
            for reference in delivery["query_refs"]:
                receipt, _ = verify_receipt(resolve_file(source_path.parent, reference))
                source_ids.update(receipt["referenced_source_ids"])
            if not source_ids:
                _error("SOURCE_IDS_REQUIRED", "Casebook requires query evidence with physical sources")
            evidence.append({"path": entry.relative_to(case_path).as_posix(), "sha256": _hash_file(entry),
                             "kind": "delivery", "referenced_source_ids": sorted(source_ids)})
        summary_path = case_path / "summary.md"
        summary_path.write_text(_text(summary, "summary") + "\n", encoding="utf-8")
        document: dict[str, Any] = {
            "schema_version": "casebook_case.v1", "case_id": case_id, "company_id": config["company_id"],
            "primary_role": _text(primary_role, "primary_role"), "question_category": _text(question_category, "question_category"),
            "status": "candidate", "question": _text(question, "question"),
            "normalized_question": _text(normalized_question, "normalized_question"),
            "snapshot_id": config["current_snapshot_id"], "pack_ref": config["pack_ref"], "bridge_ref": _bridge_ref(root, config),
            "key_queries": key_queries, "evidence": evidence, "evidence_contract": "business_delivery.v1", "snapshot_ref": expected["snapshot_ref"],
            "created_at": created_at or datetime.now(UTC).isoformat(), "created_by": _text(created_by, "created_by"),
            "summary_sha256": _hash_file(summary_path),
        }
        if supersedes is not None:
            if not ID_PATTERN.fullmatch(supersedes):
                _error("CASE_ID_INVALID", "supersedes must be a stable lowercase identifier", path="$.supersedes")
            _, previous = _find_case(root, supersedes)
            if previous["status"] != "confirmed":
                _error("SUPERSEDE_REQUIRES_CONFIRMED", "supersedes must name a confirmed case")
            if previous["company_id"] != document["company_id"] or previous["primary_role"] != document["primary_role"]:
                _error("SUPERSEDE_SCOPE_MISMATCH", "replacement case must have the same company and primary role")
            document["supersedes"] = supersedes
        _validate_case(document, case_path=case_path, expected_status="candidate")
        write_json(case_path / "case.json", document, overwrite=False)
        os.rename(case_path, final_path)
        case_path = final_path
    except Exception as exc:
        shutil.rmtree(case_path, ignore_errors=True)
        from data_platform.query.evidence import EvidenceError
        if isinstance(exc, EvidenceError):
            _error("EVIDENCE_INVALID", str(exc))
        raise
    return {"schema_version": "casebook_result.v1", "status": "candidate_created", "case_id": case_id, "case_path": str(case_path.resolve())}


def capture_case(*, root: Path, manifest_path: str) -> dict[str, Any]:
    """Create one candidate from an explicit workspace-local capture manifest.

    The manifest is only a lower-friction input shape; all Snapshot, Pack,
    Bridge, path, evidence, and state gates remain in ``create_case``.
    """
    manifest = _workspace_file(root, manifest_path, field="manifest_path")
    document = load_json(manifest)
    if document.get("schema_version") != "casebook_capture.v2":
        _error("CAPTURE_SCHEMA_INVALID", "unsupported Casebook capture manifest")
    required = {
        "schema_version", "case_id", "primary_role", "question_category", "question",
        "normalized_question", "key_queries", "evidence_sources", "summary", "created_by",
    }
    missing = required - set(document)
    if missing:
        _error("CAPTURE_FIELDS_MISSING", f"capture manifest is missing required fields: {', '.join(sorted(missing))}")
    allowed = required | {"supersedes"}
    if set(document) - allowed:
        _error("CAPTURE_FIELDS_INVALID", "capture manifest contains unsupported fields")
    return create_case(
        root=root,
        case_id=document["case_id"],
        primary_role=document["primary_role"],
        question_category=document["question_category"],
        question=document["question"],
        normalized_question=document["normalized_question"],
        key_queries=document["key_queries"],
        evidence_sources=document["evidence_sources"],
        summary=document["summary"],
        created_by=document["created_by"],
        supersedes=document.get("supersedes"),
    )


def _decide_case(*, root: Path, case_id: str, target_status: str, decided_by: str, decision_note: str) -> dict[str, Any]:
    case_path, document = _find_case(root, case_id)
    if document["status"] != "candidate":
        _error("CASE_IMMUTABLE", "only a candidate can be decided")
    document["status"] = target_status
    document["decided_by"] = _text(decided_by, "decided_by")
    document["decision_note"] = _text(decision_note, "decision_note")
    document["decided_at"] = datetime.now(UTC).isoformat()
    write_json(case_path / "case.json", document)
    target = _case_path(root, target_status, case_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    case_path.replace(target)
    return {"schema_version": "casebook_result.v1", "status": f"case_{target_status}", "case_id": case_id, "case_path": str(target.resolve())}


def confirm_case(*, root: Path, case_id: str, decided_by: str, decision_note: str) -> dict[str, Any]:
    return _decide_case(root=root, case_id=case_id, target_status="confirmed", decided_by=decided_by, decision_note=decision_note)


def reject_case(*, root: Path, case_id: str, decided_by: str, decision_note: str) -> dict[str, Any]:
    return _decide_case(root=root, case_id=case_id, target_status="rejected", decided_by=decided_by, decision_note=decision_note)


def supersede_case(*, root: Path, case_id: str, superseding_case_id: str, decided_by: str, decision_note: str) -> dict[str, Any]:
    old_path, old = _find_case(root, case_id)
    _, replacement = _find_case(root, superseding_case_id)
    if old["status"] != "confirmed" or replacement["status"] != "confirmed":
        _error("SUPERSEDE_REQUIRES_CONFIRMED", "both cases must be confirmed before superseding")
    if old["company_id"] != replacement["company_id"] or old["primary_role"] != replacement["primary_role"]:
        _error("SUPERSEDE_SCOPE_MISMATCH", "replacement case must have the same company and primary role")
    if replacement.get("supersedes") != case_id:
        _error("SUPERSEDE_LINK_REQUIRED", "replacement case must declare supersedes when it is created")
    old["status"] = "superseded"
    old["superseded_by"] = superseding_case_id
    old["decided_by"] = _text(decided_by, "decided_by")
    old["decision_note"] = _text(decision_note, "decision_note")
    old["decided_at"] = datetime.now(UTC).isoformat()
    write_json(old_path / "case.json", old)
    target = _case_path(root, "superseded", case_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    old_path.replace(target)
    return {"schema_version": "casebook_result.v1", "status": "case_superseded", "case_id": case_id, "superseded_by": superseding_case_id}


def search_cases(*, root: Path, company_id: str, primary_role: str, question_category: str | None = None) -> dict[str, Any]:
    _, config = load_workspace(root)
    if company_id != config.get("company_id"):
        _error("COMPANY_SCOPE_MISMATCH", "Casebook search is limited to the workspace company")
    results = []
    for case_json in sorted(_status_root(root, "confirmed").glob("*/case.json")):
        case_path = case_json.parent
        if case_path.is_symlink() or case_json.is_symlink() or not _inside(root, case_path):
            _error("PATH_OUTSIDE_WORKSPACE", "Casebook path escapes the workspace")
        document = load_json(case_json)
        _validate_case(document, case_path=case_path, expected_status="confirmed")
        if document["company_id"] != company_id or document["primary_role"] != primary_role:
            continue
        if question_category is not None and document["question_category"] != question_category:
            continue
        results.append({
            "case_id": document["case_id"], "primary_role": document["primary_role"],
            "question_category": document["question_category"], "normalized_question": document["normalized_question"],
            "snapshot_id": document["snapshot_id"], "stale_for_current_snapshot": document["snapshot_id"] != config.get("current_snapshot_id"),
        })
    return {"schema_version": "casebook_result.v1", "status": "search_completed", "cases": results}


def verify_case(*, root: Path, case_id: str) -> dict[str, Any]:
    case_path, document = _find_case(root, case_id)
    errors: list[dict[str, str]] = []
    summary = case_path / "summary.md"
    if not summary.is_file() or summary.is_symlink() or _hash_file(summary) != document["summary_sha256"]:
        errors.append({"code": "SUMMARY_HASH_MISMATCH", "path": "summary.md", "message": "summary hash does not match"})
    for evidence in document["evidence"]:
        file_path = case_path / evidence["path"]
        if not file_path.is_file() or file_path.is_symlink() or _hash_file(file_path) != evidence["sha256"]:
            errors.append({"code": "EVIDENCE_HASH_MISMATCH", "path": evidence["path"], "message": "evidence hash does not match"})
        if evidence["kind"] == "delivery":
            from workspace_modeling.delivery import verify_delivery
            try:
                verify_delivery(file_path, expected={
                    "workspace_ref": {"company_id": document["company_id"]},
                    "snapshot_ref": document["snapshot_ref"],
                    **{k: document[k] for k in ("primary_role", "snapshot_id", "pack_ref", "bridge_ref")},
                })
            except (ValueError, OSError, KeyError, TypeError) as exc:
                errors.append({"code": "EVIDENCE_CLOSURE_INVALID", "path": evidence["path"], "message": str(exc)})
    return {"schema_version": "casebook_result.v1", "status": "passed" if not errors else "failed", "case_id": case_id, "verification_scope": "delivery_closure" if document.get("evidence_contract") == "business_delivery.v1" else "legacy_file_hashes", "errors": errors}
