from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,95}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
CARD_TERMINAL_STATUSES = {"passed", "failed", "blocked", "skipped"}
ATTACHMENT_DENIED_SUFFIXES = {".xlsx", ".xlsm", ".xls", ".duckdb", ".parquet"}


class PilotFeedbackError(ValueError):
    """A deterministic, structured error suitable for the shared CLI."""

    def __init__(self, code: str, message: str, *, path: str = "$") -> None:
        super().__init__(message)
        self.code = code
        self.errors = [{"code": code, "path": path, "message": message}]


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PilotFeedbackError("FILE_NOT_FOUND", str(exc), path=str(path)) from exc
    except json.JSONDecodeError as exc:
        raise PilotFeedbackError(code, str(exc), path=str(path)) from exc
    if not isinstance(value, dict):
        raise PilotFeedbackError("JSON_OBJECT_REQUIRED", f"JSON object required: {path}", path=str(path))
    return value


def _write_json(path: Path, value: dict[str, Any], *, overwrite: bool = True) -> None:
    if path.exists() and not overwrite:
        raise PilotFeedbackError("OUTPUT_EXISTS", f"output already exists: {path}", path=str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _require_id(value: Any, name: str, *, path: str = "$") -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise PilotFeedbackError("ID_INVALID", f"{name} must be a stable lowercase identifier", path=f"{path}.{name}")
    return value


def _require_nonempty_string(value: Any, name: str, *, path: str = "$") -> str:
    if not isinstance(value, str) or not value.strip():
        raise PilotFeedbackError("FIELD_REQUIRED", f"{name} must be a non-empty string", path=f"{path}.{name}")
    return value


def _require_list(value: Any, name: str, *, path: str = "$") -> list[Any]:
    if not isinstance(value, list):
        raise PilotFeedbackError("TYPE_INVALID", f"{name} must be a list", path=f"{path}.{name}")
    return value


def _ensure_within_workspace(workspace: Path, candidate: Path, *, code: str = "PATH_OUTSIDE_WORKSPACE") -> Path:
    root = workspace.resolve()
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except ValueError as exc:
        raise PilotFeedbackError(code, "path must remain inside the explicit workspace", path=str(candidate)) from exc
    return resolved


def _workspace_config(workspace: Path) -> dict[str, Any]:
    return _read_json(workspace / "Work" / "workspace.json", code="WORKSPACE_JSON_INVALID")


def _evaluation_root(workspace: Path) -> Path:
    _workspace_config(workspace)
    return workspace / "Work" / "Evaluation"


def _package_path(workspace: Path, pack_id: str, version: str) -> Path:
    _require_id(pack_id, "pack_id")
    _require_nonempty_string(version, "version")
    return _evaluation_root(workspace) / "test-packages" / pack_id / version / "test_package.json"


def _evaluation_path(workspace: Path, evaluation_id: str) -> Path:
    _require_id(evaluation_id, "evaluation_id")
    return _evaluation_root(workspace) / "sessions" / evaluation_id / "evaluation.json"


def _validate_card(card: Any, index: int) -> None:
    path = f"$.cards[{index}]"
    if not isinstance(card, dict):
        raise PilotFeedbackError("TYPE_INVALID", "card must be an object", path=path)
    _require_id(card.get("card_id"), "card_id", path=path)
    for name in ("primary_role", "question", "expected_delivery"):
        _require_nonempty_string(card.get(name), name, path=path)
    for name in ("allowed_sources", "expected_key_facts", "forbidden_conclusions", "acceptance_rules"):
        values = _require_list(card.get(name), name, path=path)
        if not values:
            raise PilotFeedbackError("FIELD_REQUIRED", f"{name} must not be empty", path=f"{path}.{name}")


def validate_test_package(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise PilotFeedbackError("JSON_OBJECT_REQUIRED", "test package must be an object")
    if document.get("schema_version") != "pilot_test_package.v1":
        raise PilotFeedbackError("TEST_PACKAGE_SCHEMA_INVALID", "schema_version must be pilot_test_package.v1", path="$.schema_version")
    _require_id(document.get("pack_id"), "pack_id")
    _require_nonempty_string(document.get("version"), "version")
    _require_nonempty_string(document.get("title"), "title")
    cards = _require_list(document.get("cards"), "cards")
    if not cards:
        raise PilotFeedbackError("FIELD_REQUIRED", "cards must not be empty", path="$.cards")
    card_ids: set[str] = set()
    for index, card in enumerate(cards):
        _validate_card(card, index)
        card_id = card["card_id"]
        if card_id in card_ids:
            raise PilotFeedbackError("CARD_ID_DUPLICATE", f"duplicate card_id: {card_id}", path=f"$.cards[{index}].card_id")
        card_ids.add(card_id)
    return {"schema_version": "pilot_feedback_validation.v1", "status": "passed", "pack_id": document["pack_id"], "version": document["version"], "card_count": len(cards), "errors": []}


def load_test_package(workspace: Path, *, pack_id: str, version: str) -> dict[str, Any]:
    document = _read_json(_package_path(workspace, pack_id, version), code="TEST_PACKAGE_JSON_INVALID")
    validate_test_package(document)
    if document["pack_id"] != pack_id or document["version"] != version:
        raise PilotFeedbackError("TEST_PACKAGE_REFERENCE_MISMATCH", "test package identity does not match its path")
    return document


def import_test_package(*, workspace: Path, package_path: Path) -> dict[str, Any]:
    # Real packages can only enter an explicit customer workspace; no repository discovery exists here.
    document = _read_json(package_path, code="TEST_PACKAGE_JSON_INVALID")
    validated = validate_test_package(document)
    destination = _package_path(workspace, document["pack_id"], document["version"])
    _ensure_within_workspace(workspace, destination)
    _write_json(destination, document, overwrite=False)
    return {
        "schema_version": "pilot_feedback_result.v1",
        "status": "test_package_imported",
        "test_package_path": str(destination.resolve()),
        "pack_id": validated["pack_id"],
        "version": validated["version"],
        "card_count": validated["card_count"],
        "errors": [],
    }


def _validate_test_pack_ref(value: Any) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise PilotFeedbackError("TYPE_INVALID", "test_pack_ref must be an object", path="$.test_pack_ref")
    return _require_id(value.get("pack_id"), "pack_id", path="$.test_pack_ref"), _require_nonempty_string(value.get("version"), "version", path="$.test_pack_ref")


def _version_ref(value: Any, *, id_key: str, version_key: str, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {id_key, version_key}:
        raise PilotFeedbackError("REFERENCE_INVALID", f"{field} must contain only {id_key} and {version_key}", path=f"$.{field}")
    return {
        id_key: _require_id(value.get(id_key), id_key, path=f"$.{field}"),
        version_key: _require_nonempty_string(value.get(version_key), version_key, path=f"$.{field}"),
    }


def _workspace_references(workspace: Path, config: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    pack_ref = _version_ref(config.get("pack_ref"), id_key="pack_id", version_key="pack_version", field="workspace.pack_ref")
    pointer = config.get("current_bridge_path") or config.get("bridge_reference_path")
    if not isinstance(pointer, str) or not pointer or Path(pointer).is_absolute():
        raise PilotFeedbackError("BRIDGE_REFERENCE_MISSING", "workspace has no explicit Bridge reference")
    bridge = _read_json(_ensure_within_workspace(workspace, workspace / pointer), code="BRIDGE_JSON_INVALID")
    if bridge.get("company_id") != config.get("company_id"):
        raise PilotFeedbackError("BRIDGE_COMPANY_MISMATCH", "Bridge belongs to a different company")
    return pack_ref, {
        "bridge_id": _require_id(bridge.get("bridge_id"), "bridge_id", path="$.bridge_ref"),
        "bridge_version": _require_nonempty_string(bridge.get("bridge_version"), "bridge_version", path="$.bridge_ref"),
    }


def start_evaluation(
    *, workspace: Path, evaluation_id: str, product_version: str, pack_ref: Any,
    bridge_ref: Any, casebook_version: str, test_pack_ref: dict[str, Any],
) -> dict[str, Any]:
    config = _workspace_config(workspace)
    _require_id(evaluation_id, "evaluation_id")
    _require_nonempty_string(product_version, "product_version")
    _require_nonempty_string(casebook_version, "casebook_version")
    expected_pack_ref, expected_bridge_ref = _workspace_references(workspace, config)
    if _version_ref(pack_ref, id_key="pack_id", version_key="pack_version", field="pack_ref") != expected_pack_ref:
        raise PilotFeedbackError("PACK_REFERENCE_MISMATCH", "pack_ref must match the current workspace Pack")
    if _version_ref(bridge_ref, id_key="bridge_id", version_key="bridge_version", field="bridge_ref") != expected_bridge_ref:
        raise PilotFeedbackError("BRIDGE_REFERENCE_MISMATCH", "bridge_ref must match the explicit workspace Bridge")
    package_id, version = _validate_test_pack_ref(test_pack_ref)
    package = load_test_package(workspace, pack_id=package_id, version=version)
    path = _evaluation_path(workspace, evaluation_id)
    if path.exists():
        raise PilotFeedbackError("EVALUATION_EXISTS", f"evaluation already exists: {evaluation_id}")
    company_id = _require_id(config.get("company_id"), "company_id", path="$.workspace")
    cards = [{
        "card_id": card["card_id"], "status": "pending", "duration_seconds": None,
        "matched_case_ids": [], "acceptance": None, "score": None, "feedback": None,
        "error_codes": [], "redacted_log": None, "reviewed_by": None, "reviewed_at": None,
    } for card in package["cards"]]
    evaluation = {
        "schema_version": "pilot_evaluation.v1", "evaluation_id": evaluation_id, "company_id": company_id,
        "product_version": product_version, "pack_ref": expected_pack_ref, "bridge_ref": expected_bridge_ref,
        "casebook_version": casebook_version, "test_pack_ref": {"pack_id": package_id, "version": version},
        "status": "in_progress", "started_at": _now(), "cards": cards,
    }
    _write_json(path, evaluation, overwrite=False)
    return {"schema_version": "pilot_feedback_result.v1", "status": "evaluation_started", "evaluation_id": evaluation_id, "evaluation_path": str(path.resolve()), "errors": []}


def load_evaluation(workspace: Path, *, evaluation_id: str) -> dict[str, Any]:
    document = _read_json(_evaluation_path(workspace, evaluation_id), code="EVALUATION_JSON_INVALID")
    if document.get("schema_version") != "pilot_evaluation.v1":
        raise PilotFeedbackError("EVALUATION_SCHEMA_INVALID", "schema_version must be pilot_evaluation.v1")
    if document.get("evaluation_id") != evaluation_id:
        raise PilotFeedbackError("EVALUATION_REFERENCE_MISMATCH", "evaluation identity does not match its path")
    for name in ("company_id", "product_version", "casebook_version", "started_at"):
        _require_nonempty_string(document.get(name), name)
    _version_ref(document.get("pack_ref"), id_key="pack_id", version_key="pack_version", field="pack_ref")
    _version_ref(document.get("bridge_ref"), id_key="bridge_id", version_key="bridge_version", field="bridge_ref")
    _validate_test_pack_ref(document.get("test_pack_ref"))
    if document.get("status") not in {"in_progress", "completed"}:
        raise PilotFeedbackError("EVALUATION_STATUS_INVALID", "evaluation status is invalid", path="$.status")
    cards = _require_list(document.get("cards"), "cards")
    if not cards:
        raise PilotFeedbackError("FIELD_REQUIRED", "evaluation cards must not be empty", path="$.cards")
    return document


def record_card(
    *, workspace: Path, evaluation_id: str, card_id: str, status: str, duration_seconds: float,
    matched_case_ids: list[str], acceptance: Any, score: Any, feedback: str, error_codes: list[str], redacted_log: str, reviewed_by: str,
) -> dict[str, Any]:
    evaluation = load_evaluation(workspace, evaluation_id=evaluation_id)
    if evaluation["status"] != "in_progress":
        raise PilotFeedbackError("EVALUATION_NOT_IN_PROGRESS", "completed evaluations cannot be edited")
    _require_id(card_id, "card_id")
    if status not in CARD_TERMINAL_STATUSES:
        raise PilotFeedbackError("CARD_STATUS_INVALID", "card status must be terminal", path="$.status")
    if not isinstance(duration_seconds, (int, float)) or isinstance(duration_seconds, bool) or duration_seconds < 0:
        raise PilotFeedbackError("DURATION_INVALID", "duration_seconds must be a non-negative number")
    if not isinstance(matched_case_ids, list) or not all(isinstance(item, str) and ID_PATTERN.fullmatch(item) for item in matched_case_ids):
        raise PilotFeedbackError("MATCHED_CASE_IDS_INVALID", "matched_case_ids must contain only stable case identifiers")
    if not isinstance(error_codes, list) or not all(isinstance(item, str) and item for item in error_codes):
        raise PilotFeedbackError("ERROR_CODES_INVALID", "error_codes must contain non-empty strings")
    _require_nonempty_string(feedback, "feedback")
    _require_nonempty_string(redacted_log, "redacted_log")
    reviewed_by = _require_nonempty_string(reviewed_by, "reviewed_by")
    records = {item.get("card_id"): item for item in evaluation.get("cards", []) if isinstance(item, dict)}
    record = records.get(card_id)
    if record is None:
        raise PilotFeedbackError("CARD_NOT_IN_TEST_PACKAGE", f"card is not in this evaluation: {card_id}")
    if record["status"] != "pending":
        raise PilotFeedbackError("CARD_ALREADY_RECORDED", f"card is already terminal: {card_id}")
    record.update({"status": status, "duration_seconds": duration_seconds, "matched_case_ids": matched_case_ids,
                   "acceptance": acceptance, "score": score, "feedback": feedback, "error_codes": error_codes,
                   "redacted_log": redacted_log, "reviewed_by": reviewed_by, "reviewed_at": _now()})
    _write_json(_evaluation_path(workspace, evaluation_id), evaluation)
    return {"schema_version": "pilot_feedback_result.v1", "status": "card_recorded", "evaluation_id": evaluation_id, "card_id": card_id, "errors": []}


def complete_evaluation(*, workspace: Path, evaluation_id: str) -> dict[str, Any]:
    evaluation = load_evaluation(workspace, evaluation_id=evaluation_id)
    if evaluation["status"] != "in_progress":
        raise PilotFeedbackError("EVALUATION_NOT_IN_PROGRESS", "evaluation is not in progress")
    pending = [card.get("card_id") for card in evaluation.get("cards", []) if card.get("status") not in CARD_TERMINAL_STATUSES]
    if pending:
        raise PilotFeedbackError("EVALUATION_CARDS_PENDING", "all cards must have a terminal result", path="$.cards")
    evaluation["status"] = "completed"
    evaluation["completed_at"] = _now()
    _write_json(_evaluation_path(workspace, evaluation_id), evaluation)
    return {"schema_version": "pilot_feedback_result.v1", "status": "evaluation_completed", "evaluation_id": evaluation_id, "errors": []}


def _attachment_source(workspace: Path, source: Path) -> Path:
    source = _ensure_within_workspace(workspace, source)
    if source.is_symlink() or not source.is_file():
        raise PilotFeedbackError("EVIDENCE_SOURCE_INVALID", "evidence source must be a regular file")
    relative = source.relative_to(workspace.resolve())
    if relative.parts[:2] in {("Input", "Data"), ("Work", "Runs")} or source.suffix.lower() in ATTACHMENT_DENIED_SUFFIXES:
        raise PilotFeedbackError("EVIDENCE_SOURCE_FORBIDDEN", "customer data, database, Parquet, and runs evidence cannot be attached")
    return source


def attach_evidence(*, workspace: Path, evaluation_id: str, evidence_id: str, source_path: Path) -> dict[str, Any]:
    evaluation = load_evaluation(workspace, evaluation_id=evaluation_id)
    if evaluation["status"] != "in_progress":
        raise PilotFeedbackError("EVALUATION_NOT_IN_PROGRESS", "cannot attach evidence after completion")
    _require_id(evidence_id, "evidence_id")
    source = _attachment_source(workspace, source_path)
    destination_dir = _evaluation_path(workspace, evaluation_id).parent / "evidence"
    if any(destination_dir.glob(f"{evidence_id}-*")):
        raise PilotFeedbackError("EVIDENCE_ID_EXISTS", f"evidence already exists: {evidence_id}")
    safe_name = Path(source.name).name
    destination = destination_dir / f"{evidence_id}-{safe_name}"
    destination_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return {"schema_version": "pilot_feedback_result.v1", "status": "evidence_attached", "evaluation_id": evaluation_id,
            "evidence_id": evidence_id, "path": str(destination.resolve()), "sha256": _sha256(destination), "errors": []}


def _feedback_document(evaluation: dict[str, Any]) -> dict[str, Any]:
    cards = []
    for card in evaluation["cards"]:
        exported = {key: card[key] for key in ("card_id", "status", "duration_seconds", "score", "feedback", "error_codes")}
        exported["acceptance"] = _acceptance_summary(card["acceptance"])
        exported["matched_case_ids"] = [hashlib.sha256(case_id.encode("utf-8")).hexdigest() for case_id in card["matched_case_ids"]]
        cards.append(exported)
    return {"schema_version": "pilot_feedback.v1", "product_version": evaluation["product_version"],
            "pack_ref": _version_reference(evaluation["pack_ref"], ("pack_id", "pack_version", "version")),
            "bridge_ref": _version_reference(evaluation["bridge_ref"], ("bridge_id", "bridge_version", "version")), "casebook_version": evaluation["casebook_version"],
            "test_pack_ref": evaluation["test_pack_ref"], "cards": cards}


def _acceptance_summary(value: Any) -> bool | None:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, dict) and isinstance(value.get("accepted"), bool):
        return value["accepted"]
    return None


def _version_reference(value: Any, allowed_keys: tuple[str, ...]) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if key in allowed_keys and isinstance(item, str)}


def _validate_feedback_document(document: Any) -> None:
    allowed = {"schema_version", "product_version", "pack_ref", "bridge_ref", "casebook_version", "test_pack_ref", "cards"}
    if not isinstance(document, dict) or set(document) != allowed or document.get("schema_version") != "pilot_feedback.v1":
        raise PilotFeedbackError("FEEDBACK_JSON_INVALID", "feedback document schema is invalid")
    _require_nonempty_string(document.get("product_version"), "product_version")
    _require_nonempty_string(document.get("casebook_version"), "casebook_version")
    _version_ref(document.get("pack_ref"), id_key="pack_id", version_key="pack_version", field="pack_ref")
    _version_ref(document.get("bridge_ref"), id_key="bridge_id", version_key="bridge_version", field="bridge_ref")
    _validate_test_pack_ref(document.get("test_pack_ref"))
    cards = _require_list(document.get("cards"), "cards")
    for index, card in enumerate(cards):
        fields = {"card_id", "status", "duration_seconds", "score", "feedback", "error_codes", "acceptance", "matched_case_ids"}
        if not isinstance(card, dict) or set(card) != fields:
            raise PilotFeedbackError("FEEDBACK_JSON_INVALID", "feedback card contains unsupported fields", path=f"$.cards[{index}]")
        _require_id(card.get("card_id"), "card_id", path=f"$.cards[{index}]")
        if card.get("status") not in CARD_TERMINAL_STATUSES:
            raise PilotFeedbackError("FEEDBACK_JSON_INVALID", "feedback card status is invalid", path=f"$.cards[{index}].status")
        if not isinstance(card.get("duration_seconds"), (int, float)) or isinstance(card.get("duration_seconds"), bool) or card["duration_seconds"] < 0:
            raise PilotFeedbackError("FEEDBACK_JSON_INVALID", "feedback card duration is invalid", path=f"$.cards[{index}].duration_seconds")
        if card.get("score") is not None and (not isinstance(card["score"], (int, float)) or isinstance(card["score"], bool)):
            raise PilotFeedbackError("FEEDBACK_JSON_INVALID", "feedback card score is invalid", path=f"$.cards[{index}].score")
        if not isinstance(card.get("feedback"), str) or not isinstance(card.get("acceptance"), (bool, type(None))):
            raise PilotFeedbackError("FEEDBACK_JSON_INVALID", "feedback card content is invalid", path=f"$.cards[{index}]")
        if not isinstance(card.get("error_codes"), list) or not all(isinstance(item, str) and item for item in card["error_codes"]):
            raise PilotFeedbackError("FEEDBACK_JSON_INVALID", "feedback card errors are invalid", path=f"$.cards[{index}].error_codes")
        if not isinstance(card.get("matched_case_ids"), list) or not all(isinstance(item, str) and SHA256_PATTERN.fullmatch(item) for item in card["matched_case_ids"]):
            raise PilotFeedbackError("FEEDBACK_JSON_INVALID", "feedback case identifiers must be SHA-256 values", path=f"$.cards[{index}].matched_case_ids")


def _zip_write(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, content)


def export_feedback(*, workspace: Path, evaluation_id: str, feedback_id: str, export_type: str, evidence_ids: list[str] | None = None) -> dict[str, Any]:
    evaluation = load_evaluation(workspace, evaluation_id=evaluation_id)
    if evaluation["status"] != "completed":
        raise PilotFeedbackError("EVALUATION_NOT_COMPLETED", "only completed evaluations may be exported")
    _require_id(feedback_id, "feedback_id")
    if export_type not in {"metrics-only", "evidence-approved"}:
        raise PilotFeedbackError("EXPORT_TYPE_INVALID", "export_type must be metrics-only or evidence-approved")
    requested = evidence_ids or []
    if export_type == "metrics-only" and requested:
        raise PilotFeedbackError("METRICS_ONLY_EVIDENCE_FORBIDDEN", "metrics-only exports cannot contain evidence")
    if len(set(requested)) != len(requested) or not all(isinstance(item, str) and ID_PATTERN.fullmatch(item) for item in requested):
        raise PilotFeedbackError("EVIDENCE_IDS_INVALID", "evidence IDs must be unique stable identifiers")
    session_root = _evaluation_path(workspace, evaluation_id).parent
    attachments: list[tuple[str, Path]] = []
    for evidence_id in requested:
        candidates = list((session_root / "evidence").glob(f"{evidence_id}-*"))
        if len(candidates) != 1 or not candidates[0].is_file():
            raise PilotFeedbackError("EVIDENCE_NOT_ATTACHED", f"no explicitly attached evidence: {evidence_id}")
        attachments.append((evidence_id, candidates[0]))
    feedback = _feedback_document(evaluation)
    feedback_bytes = (json.dumps(feedback, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    entries = [{"path": "feedback.json", "sha256": hashlib.sha256(feedback_bytes).hexdigest()}]
    for evidence_id, attachment in attachments:
        entries.append({"path": f"evidence/{evidence_id}-{attachment.name.split('-', 1)[1]}", "sha256": _sha256(attachment), "evidence_id": evidence_id})
    manifest = {"schema_version": "pilot_feedback_manifest.v1", "feedback_id": feedback_id, "evaluation_id": evaluation_id,
                "export_type": export_type, "entries": entries}
    destination = _evaluation_root(workspace) / "exports" / f"{feedback_id}.zip"
    if destination.exists():
        raise PilotFeedbackError("OUTPUT_EXISTS", f"feedback export already exists: {feedback_id}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    with zipfile.ZipFile(temporary, "w") as archive:
        _zip_write(archive, "manifest.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        _zip_write(archive, "feedback.json", feedback_bytes)
        for _, attachment in attachments:
            _zip_write(archive, f"evidence/{attachment.name}", attachment.read_bytes())
    os.replace(temporary, destination)
    return {"schema_version": "pilot_feedback_result.v1", "status": "feedback_exported", "feedback_id": feedback_id,
            "export_type": export_type, "path": str(destination.resolve()), "errors": []}


def verify_feedback(*, feedback_path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(feedback_path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) < {"manifest.json", "feedback.json"}:
                raise PilotFeedbackError("FEEDBACK_ZIP_INVALID", "feedback ZIP must contain unique manifest.json and feedback.json")
            manifest = json.loads(archive.read("manifest.json"))
            feedback = json.loads(archive.read("feedback.json"))
            if not isinstance(manifest, dict) or manifest.get("schema_version") != "pilot_feedback_manifest.v1":
                raise PilotFeedbackError("FEEDBACK_MANIFEST_INVALID", "feedback manifest schema is invalid")
            if manifest.get("export_type") not in {"metrics-only", "evidence-approved"}:
                raise PilotFeedbackError("FEEDBACK_MANIFEST_INVALID", "feedback manifest export type is invalid")
            entries = manifest.get("entries")
            if not isinstance(entries, list) or not entries:
                raise PilotFeedbackError("FEEDBACK_MANIFEST_INVALID", "feedback manifest entries are invalid")
            listed = set()
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not SHA256_PATTERN.fullmatch(str(entry.get("sha256"))):
                    raise PilotFeedbackError("FEEDBACK_MANIFEST_INVALID", "feedback manifest entry is invalid")
                name = entry["path"]
                if name in listed or name not in names or name == "manifest.json" or not (name == "feedback.json" or name.startswith("evidence/")):
                    raise PilotFeedbackError("FEEDBACK_MANIFEST_INVALID", "feedback manifest entry path is invalid")
                if name.startswith("evidence/"):
                    evidence_id = entry.get("evidence_id")
                    basename = Path(name).name
                    if not isinstance(evidence_id, str) or not ID_PATTERN.fullmatch(evidence_id) or not basename.startswith(evidence_id + "-") or Path(basename).suffix.lower() in ATTACHMENT_DENIED_SUFFIXES:
                        raise PilotFeedbackError("FEEDBACK_MANIFEST_INVALID", "approved evidence path or type is invalid")
                if hashlib.sha256(archive.read(name)).hexdigest() != entry["sha256"]:
                    raise PilotFeedbackError("FEEDBACK_HASH_MISMATCH", f"feedback entry hash differs: {name}")
                listed.add(name)
            if set(names) != {"manifest.json", *listed}:
                raise PilotFeedbackError("FEEDBACK_ZIP_INVALID", "feedback ZIP contains unlisted entries")
            if manifest["export_type"] == "metrics-only" and any(name.startswith("evidence/") for name in names):
                raise PilotFeedbackError("FEEDBACK_ZIP_INVALID", "metrics-only ZIP cannot contain evidence")
            _validate_feedback_document(feedback)
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise PilotFeedbackError("FEEDBACK_ZIP_INVALID", str(exc)) from exc
    return {"schema_version": "pilot_feedback_validation.v1", "status": "passed", "feedback_id": manifest.get("feedback_id"),
            "export_type": manifest["export_type"], "entry_count": len(manifest["entries"]), "errors": []}
