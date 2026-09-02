from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from business_pack.service import load_pack, validate_pack


BRIDGE_SCHEMA_VERSION = "company_bridge.v1"
CANDIDATE_SCHEMA_VERSION = "company_bridge_candidates.v1"
VALID_CANDIDATE_TYPES = (
    "source_contract",
    "field_mapping",
    "enum_mapping",
    "normalization_rule",
    "override",
    "unresolved",
)
VALID_STATUSES = ("proposed", "confirmed", "rejected", "unresolved")
VALID_CANDIDATE_SET_ROLES = ("historical_scan", "confirmed_review")
BRIDGE_CATEGORIES = (
    "source_contracts",
    "field_mappings",
    "enum_mappings",
    "normalization_rules",
    "overrides",
    "unresolved",
)
CATEGORY_FOR_TYPE = dict(zip(VALID_CANDIDATE_TYPES, BRIDGE_CATEGORIES))
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,95}$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SNAPSHOT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,95}$")

COMMON_CANDIDATE_FIELDS = {
    "candidate_id",
    "candidate_type",
    "source_locator",
    "evidence_summary",
    "proposed_mapping_or_rule",
    "status",
    "evidence_refs",
    "decision_note",
    "decision_by",
}
REJECTION_FIELDS = {"source_locator", "reason_code", "reason", "evidence_refs"}
POLLUTION_KEYS = {
    "analysis_conclusion",
    "analysis_result",
    "historical_conclusion",
    "improvement_suggestion",
    "recommendation",
    "raw_content",
    "raw_report",
    "report_text",
    "single_period_finding",
    "weekly_anomaly",
}
PROPOSAL_FIELDS = {
    "source_contract": {
        "source_id",
        "filename",
        "sheet_name",
        "relation",
        "field_names",
        "source_kind",
        "header_labels",
        "evidence",
    },
    "field_mapping": {
        "source_id",
        "relation",
        "field_name",
        "target_type",
        "target_id",
        "mapping_role",
        "header_label",
        "evidence",
    },
    "enum_mapping": {
        "source_id",
        "relation",
        "field_name",
        "source_value",
        "target_taxonomy_id",
        "target_member_id",
    },
    "normalization_rule": {
        "source_id",
        "relation",
        "field_name",
        "operation",
        "parameters",
        "target_type",
        "target_id",
        "header_label",
        "evidence",
    },
    "override": {
        "target_type",
        "target_id",
        "key",
        "value",
        "reason",
    },
    "unresolved": {
        "source_id",
        "relation",
        "field_name",
        "blocked_target_type",
        "blocked_target_id",
        "reason",
    },
}
NORMALIZATION_OPERATIONS = {
    "trim_text",
    "normalize_whitespace",
    "parse_date",
    "parse_amount",
    "absolute_amount",
    "apply_sign_by_enum",
    "map_enum",
}
TARGET_TYPES = {"concept", "dimension", "metric", "taxonomy"}
REJECTION_CODES = {
    "ANALYSIS_REPORT",
    "PACK_CONTENT",
    "SKILL_CONTENT",
    "SINGLE_ANALYSIS_CONCLUSION",
    "UNCLASSIFIED_CONTENT",
    "UNSUPPORTED_BINARY",
}


class BridgeError(ValueError):
    def __init__(self, code: str, message: str, errors: list[dict[str, str]] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.errors = errors or [{"code": code, "path": "$", "message": message}]


def default_candidate_path() -> Path:
    return Path("company_bridge_candidates.json")


def _problem(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _id(value: Any) -> bool:
    return isinstance(value, str) and bool(ID_PATTERN.fullmatch(value))


def _version(value: Any) -> bool:
    return isinstance(value, str) and bool(VERSION_PATTERN.fullmatch(value))


def _locator(value: Any) -> bool:
    if not _text(value):
        return False
    raw = str(value)
    if raw.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", raw) or "://" in raw:
        return False
    try:
        parts = PurePosixPath(raw.replace("\\", "/")).parts
    except ValueError:
        return False
    return bool(parts) and ".." not in parts


def _json_value(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return False
    return True


def _find_pollution(value: Any, path: str, errors: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in POLLUTION_KEYS:
                errors.append(_problem("POLLUTION_CONTENT", f"{path}.{key}", "historical analysis content is not Bridge data"))
            _find_pollution(child, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _find_pollution(child, f"{path}[{index}]", errors)


def _validate_pack_ref(value: Any, path: str, errors: list[dict[str, str]]) -> None:
    if not isinstance(value, dict):
        errors.append(_problem("TYPE_INVALID", path, "must be an object"))
        return
    if set(value) != {"pack_id", "pack_version"}:
        errors.append(_problem("FIELDS_INVALID", path, "must contain only pack_id and pack_version"))
    if not _id(value.get("pack_id")):
        errors.append(_problem("ID_INVALID", f"{path}.pack_id", "must be a stable lowercase identifier"))
    if not _version(value.get("pack_version")):
        errors.append(_problem("VERSION_INVALID", f"{path}.pack_version", "must use MAJOR.MINOR.PATCH"))


def _validate_locator_list(value: Any, path: str, errors: list[dict[str, str]]) -> None:
    if not isinstance(value, list) or not value or not all(_locator(item) for item in value):
        errors.append(_problem("LOCATOR_INVALID", path, "must be a non-empty array of relative locators"))


def _validate_source_shape(
    proposal: dict[str, Any],
    *,
    path: str,
    errors: list[dict[str, str]],
    description: dict[str, Any] | None,
    require_relation: bool,
) -> None:
    source_id = proposal.get("source_id")
    if not _id(source_id):
        errors.append(_problem("ID_INVALID", f"{path}.source_id", "must be a stable lowercase identifier"))
    relation = proposal.get("relation")
    if require_relation and not _relation_name(relation):
        errors.append(_problem("SOURCE_REFERENCE_INVALID", f"{path}.relation", "must use schema.relation form"))
    if relation is not None and not _relation_name(relation):
        errors.append(_problem("SOURCE_REFERENCE_INVALID", f"{path}.relation", "must use schema.relation form"))
    if description is not None and _relation_name(relation):
        columns = _description_columns(description)
        if relation not in columns:
            errors.append(_problem("SOURCE_REFERENCE_UNKNOWN", f"{path}.relation", f"unknown Snapshot relation: {relation}"))
        field_name = proposal.get("field_name")
        field_names = proposal.get("field_names")
        if _text(field_name) and relation in columns and field_name not in columns[relation]:
            errors.append(_problem("SOURCE_FIELD_UNKNOWN", f"{path}.field_name", f"unknown field in {relation}: {field_name}"))
        if isinstance(field_names, list) and relation in columns:
            for index, name in enumerate(field_names):
                if name not in columns[relation]:
                    errors.append(_problem("SOURCE_FIELD_UNKNOWN", f"{path}.field_names[{index}]", f"unknown field in {relation}: {name}"))


def _relation_name(value: Any) -> bool:
    return _text(value) and bool(re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*\.[^\s.]+", value))


def _description_columns(description: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for relation in description.get("relations", []):
        if not isinstance(relation, dict):
            continue
        schema = relation.get("schema")
        name = relation.get("name")
        if not _text(schema) or not _text(name):
            continue
        fields = {
            item.get("name")
            for item in relation.get("columns", [])
            if isinstance(item, dict) and _text(item.get("name"))
        }
        result[f"{schema}.{name}"] = fields
    return result


def _pack_indexes(pack: dict[str, Any]) -> dict[str, set[str]]:
    return {
        "concept": {item["concept_id"] for item in pack.get("concepts", []) if isinstance(item, dict) and _text(item.get("concept_id"))},
        "dimension": {item["dimension_id"] for item in pack.get("dimensions", []) if isinstance(item, dict) and _text(item.get("dimension_id"))},
        "metric": {item["metric_id"] for item in pack.get("metrics", []) if isinstance(item, dict) and _text(item.get("metric_id"))},
        "taxonomy": {item["taxonomy_id"] for item in pack.get("taxonomies", []) if isinstance(item, dict) and _text(item.get("taxonomy_id"))},
    }


def _pack_members(pack: dict[str, Any]) -> dict[str, set[str]]:
    return {
        item["taxonomy_id"]: {
            member["member_id"]
            for member in item.get("members", [])
            if isinstance(member, dict) and _text(member.get("member_id"))
        }
        for item in pack.get("taxonomies", [])
        if isinstance(item, dict) and _text(item.get("taxonomy_id"))
    }


def _validate_target(
    target_type: Any,
    target_id: Any,
    *,
    path: str,
    errors: list[dict[str, str]],
    pack: dict[str, Any] | None,
    allowed: set[str] | None = None,
) -> None:
    if target_type not in (allowed or TARGET_TYPES):
        errors.append(_problem("TARGET_TYPE_INVALID", f"{path}.target_type", "target type is not allowed"))
        return
    if not _text(target_id):
        errors.append(_problem("TARGET_ID_INVALID", f"{path}.target_id", "target id must be a non-empty string"))
        return
    if pack is not None and target_id not in _pack_indexes(pack).get(target_type, set()):
        errors.append(_problem("REFERENCE_UNKNOWN", f"{path}.target_id", f"unknown Pack {target_type}: {target_id}"))


def _validate_proposal(
    candidate_type: str,
    proposal: Any,
    *,
    path: str,
    errors: list[dict[str, str]],
    pack: dict[str, Any] | None,
    description: dict[str, Any] | None,
) -> None:
    if not isinstance(proposal, dict):
        errors.append(_problem("TYPE_INVALID", path, "must be an object"))
        return
    _find_pollution(proposal, path, errors)
    allowed = PROPOSAL_FIELDS[candidate_type]
    unknown = set(proposal) - allowed
    for key in sorted(unknown):
        errors.append(_problem("FIELD_UNKNOWN", f"{path}.{key}", "field is not part of the versioned proposal contract"))

    def required(field: str) -> None:
        if field not in proposal:
            errors.append(_problem("FIELD_REQUIRED", f"{path}.{field}", "field is required"))

    if candidate_type == "source_contract":
        required("source_id")
        if "filename" not in proposal and "relation" not in proposal:
            errors.append(_problem("FIELD_REQUIRED", path, "source_contract requires filename or relation"))
        _validate_source_shape(proposal, path=path, errors=errors, description=description, require_relation=False)
        if "filename" in proposal and not _text(proposal["filename"]):
            errors.append(_problem("FIELD_INVALID", f"{path}.filename", "must be a non-empty filename"))
        if "sheet_name" in proposal and not _text(proposal["sheet_name"]):
            errors.append(_problem("FIELD_INVALID", f"{path}.sheet_name", "must be a non-empty string"))
        if "field_names" in proposal and (
            not isinstance(proposal["field_names"], list)
            or not proposal["field_names"]
            or not all(_text(item) for item in proposal["field_names"])
        ):
            errors.append(_problem("TYPE_INVALID", f"{path}.field_names", "must be a non-empty array of strings"))
    elif candidate_type == "field_mapping":
        for field in ("source_id", "relation", "field_name", "target_type", "target_id"):
            required(field)
        _validate_source_shape(proposal, path=path, errors=errors, description=description, require_relation=True)
        _validate_target(proposal.get("target_type"), proposal.get("target_id"), path=path, errors=errors, pack=pack, allowed={"concept", "dimension"})
        if "mapping_role" in proposal and not _text(proposal["mapping_role"]):
            errors.append(_problem("FIELD_INVALID", f"{path}.mapping_role", "must be a non-empty string"))
    elif candidate_type == "enum_mapping":
        for field in ("source_id", "relation", "field_name", "source_value", "target_taxonomy_id", "target_member_id"):
            required(field)
        _validate_source_shape(proposal, path=path, errors=errors, description=description, require_relation=True)
        taxonomy_id = proposal.get("target_taxonomy_id")
        member_id = proposal.get("target_member_id")
        if not _text(taxonomy_id):
            errors.append(_problem("TARGET_ID_INVALID", f"{path}.target_taxonomy_id", "must be a non-empty string"))
        if not _text(member_id):
            errors.append(_problem("TARGET_ID_INVALID", f"{path}.target_member_id", "must be a non-empty string"))
        if pack is not None:
            indexes = _pack_indexes(pack)
            if taxonomy_id not in indexes["taxonomy"]:
                errors.append(_problem("REFERENCE_UNKNOWN", f"{path}.target_taxonomy_id", f"unknown Pack taxonomy: {taxonomy_id}"))
            elif member_id not in _pack_members(pack).get(taxonomy_id, set()):
                errors.append(_problem("REFERENCE_UNKNOWN", f"{path}.target_member_id", f"unknown member in {taxonomy_id}: {member_id}"))
        if not _json_value(proposal.get("source_value")):
            errors.append(_problem("TYPE_INVALID", f"{path}.source_value", "must be JSON-serializable"))
    elif candidate_type == "normalization_rule":
        for field in ("source_id", "relation", "field_name", "operation"):
            required(field)
        _validate_source_shape(proposal, path=path, errors=errors, description=description, require_relation=True)
        if proposal.get("operation") not in NORMALIZATION_OPERATIONS:
            errors.append(_problem("NORMALIZATION_OPERATION_INVALID", f"{path}.operation", "operation is not allowed"))
        if "parameters" in proposal and not isinstance(proposal["parameters"], dict):
            errors.append(_problem("TYPE_INVALID", f"{path}.parameters", "must be an object"))
        if "target_type" in proposal or "target_id" in proposal:
            _validate_target(proposal.get("target_type"), proposal.get("target_id"), path=path, errors=errors, pack=pack, allowed={"concept", "dimension"})
    elif candidate_type == "override":
        for field in ("target_type", "target_id", "key", "value", "reason"):
            required(field)
        _validate_target(proposal.get("target_type"), proposal.get("target_id"), path=path, errors=errors, pack=pack)
        for field in ("key", "reason"):
            if field in proposal and not _text(proposal[field]):
                errors.append(_problem("FIELD_INVALID", f"{path}.{field}", "must be a non-empty string"))
        if "value" in proposal and not _json_value(proposal["value"]):
            errors.append(_problem("TYPE_INVALID", f"{path}.value", "must be JSON-serializable"))
    elif candidate_type == "unresolved":
        required("reason")
        if not _text(proposal.get("reason")):
            errors.append(_problem("FIELD_INVALID", f"{path}.reason", "must be a non-empty string"))
        if "source_id" in proposal and not _id(proposal["source_id"]):
            errors.append(_problem("ID_INVALID", f"{path}.source_id", "must be a stable lowercase identifier"))
        if "relation" in proposal or "field_name" in proposal:
            _validate_source_shape(proposal, path=path, errors=errors, description=description, require_relation=False)
        if "blocked_target_type" in proposal or "blocked_target_id" in proposal:
            _validate_target(
                proposal.get("blocked_target_type"),
                proposal.get("blocked_target_id"),
                path=path.replace("proposed_mapping_or_rule", "blocked_target"),
                errors=errors,
                pack=pack,
            )


def _validate_candidate(
    candidate: Any,
    *,
    index: int,
    errors: list[dict[str, str]],
    pack: dict[str, Any] | None,
    description: dict[str, Any] | None,
    role: str,
) -> None:
    path = f"candidates[{index}]"
    if not isinstance(candidate, dict):
        errors.append(_problem("TYPE_INVALID", path, "must be an object"))
        return
    _find_pollution(candidate, path, errors)
    unknown = set(candidate) - COMMON_CANDIDATE_FIELDS
    for key in sorted(unknown):
        errors.append(_problem("FIELD_UNKNOWN", f"{path}.{key}", "field is not part of the versioned candidate contract"))
    for field in ("candidate_id", "candidate_type", "source_locator", "evidence_summary", "proposed_mapping_or_rule", "status", "evidence_refs"):
        if field not in candidate:
            errors.append(_problem("FIELD_REQUIRED", f"{path}.{field}", "field is required"))
    if not _id(candidate.get("candidate_id")):
        errors.append(_problem("ID_INVALID", f"{path}.candidate_id", "must be a stable lowercase identifier"))
    if candidate.get("candidate_type") not in VALID_CANDIDATE_TYPES:
        errors.append(_problem("CANDIDATE_TYPE_INVALID", f"{path}.candidate_type", "candidate type is not allowed"))
    elif candidate.get("candidate_type") in PROPOSAL_FIELDS:
        _validate_proposal(
            candidate["candidate_type"],
            candidate.get("proposed_mapping_or_rule"),
            path=f"{path}.proposed_mapping_or_rule",
            errors=errors,
            pack=pack,
            description=description,
        )
    if not _locator(candidate.get("source_locator")):
        errors.append(_problem("LOCATOR_INVALID", f"{path}.source_locator", "must be a relative locator"))
    if not _text(candidate.get("evidence_summary")):
        errors.append(_problem("FIELD_INVALID", f"{path}.evidence_summary", "must be a non-empty string"))
    if candidate.get("status") not in VALID_STATUSES:
        errors.append(_problem("STATUS_INVALID", f"{path}.status", "candidate status is not allowed"))
    if role == "confirmed_review" and candidate.get("status") not in {"confirmed", "unresolved"}:
        errors.append(_problem("CANDIDATE_NOT_CONFIRMED", f"{path}.status", "confirmed_review accepts only confirmed or unresolved decisions"))
    _validate_locator_list(candidate.get("evidence_refs"), f"{path}.evidence_refs", errors)
    if "decision_note" in candidate and not _text(candidate["decision_note"]):
        errors.append(_problem("FIELD_INVALID", f"{path}.decision_note", "must be a non-empty string"))
    if "decision_by" in candidate and not _text(candidate["decision_by"]):
        errors.append(_problem("FIELD_INVALID", f"{path}.decision_by", "must be a non-empty string"))
    if candidate.get("status") in {"rejected", "unresolved"} and not _text(candidate.get("decision_note")):
        errors.append(_problem("DECISION_NOTE_REQUIRED", f"{path}.decision_note", "rejected and unresolved decisions require a reason"))


def _validate_description(document: Any, errors: list[dict[str, str]]) -> None:
    if not isinstance(document, dict):
        errors.append(_problem("TYPE_INVALID", "snapshot_description", "must be a JSON object"))
        return
    if document.get("schema_version") != "warehouse_description.v1":
        errors.append(_problem("SCHEMA_UNSUPPORTED", "snapshot_description.schema_version", "expected warehouse_description.v1"))
    if document.get("status") != "passed":
        errors.append(_problem("SNAPSHOT_NOT_PASSED", "snapshot_description.status", "Snapshot description must be passed"))
    if not _text(document.get("snapshot_id")) or not SNAPSHOT_ID_PATTERN.fullmatch(document.get("snapshot_id", "")):
        errors.append(_problem("SNAPSHOT_ID_INVALID", "snapshot_description.snapshot_id", "must be an explicit snapshot id"))
    relations = document.get("relations")
    if not isinstance(relations, list):
        errors.append(_problem("TYPE_INVALID", "snapshot_description.relations", "must be an array"))
        return
    seen: set[str] = set()
    for index, relation in enumerate(relations):
        path = f"snapshot_description.relations[{index}]"
        if not isinstance(relation, dict):
            errors.append(_problem("TYPE_INVALID", path, "must be an object"))
            continue
        schema = relation.get("schema")
        name = relation.get("name")
        if not _text(schema) or not _text(name):
            errors.append(_problem("FIELD_INVALID", path, "schema and name are required"))
            continue
        relation_name = f"{schema}.{name}"
        if relation_name in seen:
            errors.append(_problem("RELATION_DUPLICATE", path, f"duplicate relation: {relation_name}"))
        seen.add(relation_name)
        columns = relation.get("columns")
        if not isinstance(columns, list):
            errors.append(_problem("TYPE_INVALID", f"{path}.columns", "must be an array"))
            continue
        column_names: set[str] = set()
        for column_index, column in enumerate(columns):
            column_path = f"{path}.columns[{column_index}]"
            if not isinstance(column, dict) or not _text(column.get("name")) or not _text(column.get("type")):
                errors.append(_problem("FIELD_INVALID", column_path, "name and type are required"))
                continue
            if column["name"] in column_names:
                errors.append(_problem("FIELD_DUPLICATE", column_path, f"duplicate field: {column['name']}"))
            column_names.add(column["name"])


def _validate_quality(document: Any, errors: list[dict[str, str]], snapshot_id: str | None) -> int | None:
    if not isinstance(document, dict):
        errors.append(_problem("TYPE_INVALID", "snapshot_quality", "must be a JSON object"))
        return None
    if document.get("schema_version") != "controlled_query_result.v1":
        errors.append(_problem("SCHEMA_UNSUPPORTED", "snapshot_quality.schema_version", "expected controlled_query_result.v1"))
    if document.get("status") != "passed":
        errors.append(_problem("SNAPSHOT_QUALITY_NOT_PASSED", "snapshot_quality.status", "Snapshot quality result must be passed"))
    if document.get("snapshot_id") != snapshot_id:
        errors.append(_problem("SNAPSHOT_MISMATCH", "snapshot_quality.snapshot_id", "quality result must identify the described Snapshot"))
    if not isinstance(document.get("errors", []), list):
        errors.append(_problem("TYPE_INVALID", "snapshot_quality.errors", "must be an array"))
    result = document.get("result")
    if result is None:
        if document.get("artifact") is None and not isinstance(document.get("row_count"), int):
            errors.append(_problem("QUALITY_PAYLOAD_MISSING", "snapshot_quality", "quality result must contain inline rows or an artifact"))
        return document.get("row_count") if isinstance(document.get("row_count"), int) else None
    if not isinstance(result, dict) or not isinstance(result.get("columns"), list) or not isinstance(result.get("rows"), list):
        errors.append(_problem("TYPE_INVALID", "snapshot_quality.result", "must contain columns and rows arrays"))
        return None
    return len(result["rows"])


def _validate_common_identity(document: dict[str, Any], errors: list[dict[str, str]], *, bridge: bool) -> None:
    if document.get("schema_version") != (BRIDGE_SCHEMA_VERSION if bridge else CANDIDATE_SCHEMA_VERSION):
        errors.append(_problem("SCHEMA_UNSUPPORTED", "schema_version", "unsupported schema version"))
    for field in (("bridge_id", "company_id") if bridge else ("candidate_set_id", "company_id")):
        if not _id(document.get(field)):
            errors.append(_problem("ID_INVALID", field, "must be a stable lowercase identifier"))
    if bridge and not _version(document.get("bridge_version")):
        errors.append(_problem("VERSION_INVALID", "bridge_version", "must use MAJOR.MINOR.PATCH"))
    _validate_pack_ref(document.get("pack_ref"), "pack_ref", errors)


def validate_candidate_set(
    document: Any,
    *,
    pack: dict[str, Any] | None = None,
    description: dict[str, Any] | None = None,
    require_role: str | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    if not isinstance(document, dict):
        errors.append(_problem("TYPE_INVALID", "$", "candidate set must be a JSON object"))
        return {"schema_version": CANDIDATE_SCHEMA_VERSION, "status": "failed", "errors": errors}
    allowed = {"schema_version", "candidate_set_role", "candidate_set_id", "company_id", "pack_ref", "candidates", "rejections", "summary"}
    for key in sorted(set(document) - allowed):
        errors.append(_problem("FIELD_UNKNOWN", key, "field is not part of the versioned candidate set"))
    _validate_common_identity(document, errors, bridge=False)
    role = document.get("candidate_set_role")
    if role not in VALID_CANDIDATE_SET_ROLES:
        errors.append(_problem("CANDIDATE_SET_ROLE_INVALID", "candidate_set_role", "candidate set role is not allowed"))
    elif require_role is not None and role != require_role:
        errors.append(_problem("CANDIDATE_SET_ROLE_INVALID", "candidate_set_role", f"expected {require_role}"))
    if pack is not None:
        pack_validation = validate_pack(pack)
        if pack_validation["status"] != "passed":
            errors.append(_problem("PACK_INVALID", "pack_ref", "referenced Pack is invalid"))
        elif document.get("pack_ref") != {"pack_id": pack["pack_id"], "pack_version": pack["pack_version"]}:
            errors.append(_problem("PACK_MISMATCH", "pack_ref", "candidate Pack reference does not match supplied Pack"))
    candidates = document.get("candidates")
    if not isinstance(candidates, list):
        errors.append(_problem("TYPE_INVALID", "candidates", "must be an array"))
        candidates = []
    candidate_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        _validate_candidate(candidate, index=index, errors=errors, pack=pack, description=description, role=role or "historical_scan")
        if isinstance(candidate, dict) and _id(candidate.get("candidate_id")):
            candidate_id = candidate["candidate_id"]
            if candidate_id in candidate_ids:
                errors.append(_problem("CANDIDATE_DUPLICATE", f"candidates[{index}].candidate_id", f"duplicate candidate: {candidate_id}"))
            candidate_ids.add(candidate_id)
    rejections = document.get("rejections")
    if not isinstance(rejections, list):
        errors.append(_problem("TYPE_INVALID", "rejections", "must be an array"))
        rejections = []
    for index, rejection in enumerate(rejections):
        path = f"rejections[{index}]"
        if not isinstance(rejection, dict):
            errors.append(_problem("TYPE_INVALID", path, "must be an object"))
            continue
        for key in sorted(set(rejection) - REJECTION_FIELDS):
            errors.append(_problem("FIELD_UNKNOWN", f"{path}.{key}", "field is not part of the rejection contract"))
        if not _locator(rejection.get("source_locator")):
            errors.append(_problem("LOCATOR_INVALID", f"{path}.source_locator", "must be a relative locator"))
        if rejection.get("reason_code") not in REJECTION_CODES:
            errors.append(_problem("REJECTION_CODE_INVALID", f"{path}.reason_code", "rejection code is not allowed"))
        if not _text(rejection.get("reason")):
            errors.append(_problem("FIELD_INVALID", f"{path}.reason", "must be a non-empty string"))
        _validate_locator_list(rejection.get("evidence_refs"), f"{path}.evidence_refs", errors)
    summary = document.get("summary")
    if not isinstance(summary, dict):
        errors.append(_problem("TYPE_INVALID", "summary", "must be an object"))
    else:
        for field, expected in (("candidate_count", len(candidates)), ("rejection_count", len(rejections))):
            if summary.get(field) != expected:
                errors.append(_problem("SUMMARY_MISMATCH", f"summary.{field}", f"must equal {expected}"))
    return {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "status": "failed" if errors else "passed",
        "candidate_set_id": document.get("candidate_set_id"),
        "candidate_count": len(candidates),
        "rejection_count": len(rejections),
        "errors": errors,
    }


def _validate_snapshot_inputs(
    description: dict[str, Any] | None,
    quality: dict[str, Any] | None,
) -> tuple[list[dict[str, str]], str | None]:
    """Validate an optional Snapshot compatibility context without owning it in Bridge."""
    errors: list[dict[str, str]] = []
    if (description is None) != (quality is None):
        errors.append(_problem(
            "SNAPSHOT_INPUT_INCOMPLETE",
            "snapshot",
            "snapshot description and quality must be supplied together",
        ))
        return errors, None
    if description is None:
        return errors, None
    _validate_description(description, errors)
    snapshot_id = description.get("snapshot_id")
    _validate_quality(quality, errors, snapshot_id)
    return errors, snapshot_id


def _mapping_key(category: str, item: dict[str, Any]) -> tuple[Any, ...] | None:
    if category in {"field_mappings", "normalization_rules"}:
        if not all(_text(item.get(field)) for field in ("relation", "field_name")):
            return None
        if category == "field_mappings":
            return (category, item["relation"], item["field_name"])
        parameters = item.get("parameters")
        source_value = parameters.get("source_value") if isinstance(parameters, dict) else None
        context = {}
        if isinstance(parameters, dict):
            context = {
                key: value
                for key, value in parameters.items()
                if key not in {"source_value", "normalized_value", "display_value"}
            }
        source_key = source_value if source_value is not None else context
        return (
            category,
            item["relation"],
            item["field_name"],
            item.get("operation"),
            json.dumps(source_key, ensure_ascii=False, sort_keys=True),
            json.dumps(context, ensure_ascii=False, sort_keys=True),
        )
    if category == "enum_mappings":
        if not all(_text(item.get(field)) for field in ("relation", "field_name")) or "source_value" not in item:
            return None
        return (category, item["relation"], item["field_name"], json.dumps(item["source_value"], ensure_ascii=False, sort_keys=True))
    if category == "overrides":
        if not all(_text(item.get(field)) for field in ("target_type", "target_id", "key")):
            return None
        return (category, item["target_type"], item["target_id"], item["key"])
    if category == "source_contracts":
        if not _text(item.get("source_id")):
            return None
        return (category, item["source_id"], item.get("relation"), item.get("filename"), item.get("sheet_name"))
    if category == "unresolved":
        if not _text(item.get("source_locator")):
            return None
        return (category, item["source_locator"], item.get("blocked_target_type"), item.get("blocked_target_id"))
    return None


def _validate_bridge_items(
    document: dict[str, Any],
    *,
    errors: list[dict[str, str]],
    pack: dict[str, Any] | None,
    description: dict[str, Any] | None,
) -> list[str]:
    ids: list[str] = []
    seen_ids: set[str] = set()
    seen_mappings: dict[tuple[Any, ...], str] = {}
    for category in BRIDGE_CATEGORIES:
        entries = document.get(category)
        if not isinstance(entries, list):
            errors.append(_problem("TYPE_INVALID", category, "must be an array"))
            continue
        candidate_type = next(key for key, value in CATEGORY_FOR_TYPE.items() if value == category)
        for index, item in enumerate(entries):
            path = f"{category}[{index}]"
            if not isinstance(item, dict):
                errors.append(_problem("TYPE_INVALID", path, "must be an object"))
                continue
            _find_pollution(item, path, errors)
            proposal_fields = PROPOSAL_FIELDS[candidate_type]
            allowed = {"candidate_id", "source_locator", "evidence_summary", "evidence_refs", "status", "header_label", "evidence"} | proposal_fields
            for key in sorted(set(item) - allowed):
                errors.append(_problem("FIELD_UNKNOWN", f"{path}.{key}", "field is not part of the formal Bridge category"))
            candidate_id = item.get("candidate_id")
            if not _id(candidate_id):
                errors.append(_problem("ID_INVALID", f"{path}.candidate_id", "must be a stable lowercase identifier"))
            elif candidate_id in seen_ids:
                errors.append(_problem("CANDIDATE_DUPLICATE", f"{path}.candidate_id", f"duplicate candidate: {candidate_id}"))
            else:
                seen_ids.add(candidate_id)
                ids.append(candidate_id)
            if not _locator(item.get("source_locator")):
                errors.append(_problem("LOCATOR_INVALID", f"{path}.source_locator", "must be a relative locator"))
            if not _text(item.get("evidence_summary")):
                errors.append(_problem("FIELD_INVALID", f"{path}.evidence_summary", "must be a non-empty string"))
            _validate_locator_list(item.get("evidence_refs"), f"{path}.evidence_refs", errors)
            expected_status = "unresolved" if category == "unresolved" else "confirmed"
            if item.get("status") != expected_status:
                errors.append(_problem("STATUS_INVALID", f"{path}.status", f"{category} items must have status {expected_status}"))
            proposal = {key: item[key] for key in proposal_fields if key in item}
            _validate_proposal(candidate_type, proposal, path=path, errors=errors, pack=pack, description=description)
            mapping_key = _mapping_key(category, item)
            if mapping_key is not None:
                prior = seen_mappings.get(mapping_key)
                if prior is not None:
                    code = "MAPPING_DUPLICATE" if prior == candidate_id else "MAPPING_CONFLICT"
                    errors.append(_problem(code, path, f"mapping key already used by {prior}"))
                else:
                    seen_mappings[mapping_key] = candidate_id
    return ids


def validate_bridge(
    document: Any,
    *,
    pack: dict[str, Any] | None = None,
    description: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    if not isinstance(document, dict):
        errors.append(_problem("TYPE_INVALID", "$", "Bridge must be a JSON object"))
        return {"schema_version": BRIDGE_SCHEMA_VERSION, "status": "failed", "errors": errors}
    _find_pollution(document, "$", errors)
    allowed = {
        "schema_version",
        "bridge_id",
        "bridge_version",
        "company_id",
        "pack_ref",
        "generated_from_candidate_ids",
        *BRIDGE_CATEGORIES,
    }
    for key in sorted(set(document) - allowed):
        errors.append(_problem("FIELD_UNKNOWN", key, "field is not part of company_bridge.v1"))
    _validate_common_identity(document, errors, bridge=True)
    if pack is not None:
        pack_validation = validate_pack(pack)
        if pack_validation["status"] != "passed":
            errors.append(_problem("PACK_INVALID", "pack_ref", "referenced Pack is invalid"))
        elif document.get("pack_ref") != {"pack_id": pack["pack_id"], "pack_version": pack["pack_version"]}:
            errors.append(_problem("PACK_MISMATCH", "pack_ref", "Bridge Pack reference does not match supplied Pack"))
    snapshot_errors, snapshot_id = _validate_snapshot_inputs(description, quality)
    errors.extend(snapshot_errors)
    ids = _validate_bridge_items(document, errors=errors, pack=pack, description=description)
    generated = document.get("generated_from_candidate_ids")
    if not isinstance(generated, list) or not all(_id(item) for item in generated) or len(set(generated)) != len(generated):
        errors.append(_problem("CANDIDATE_REFERENCE_INVALID", "generated_from_candidate_ids", "must be a unique array of candidate ids"))
    elif generated != ids:
        errors.append(_problem("CANDIDATE_REFERENCE_MISMATCH", "generated_from_candidate_ids", "must match formal category item order"))
    return {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "status": "failed" if errors else "passed",
        "bridge_id": document.get("bridge_id"),
        "bridge_version": document.get("bridge_version"),
        "pack_ref": document.get("pack_ref"),
        "snapshot_id": snapshot_id,
        "counts": {category: len(document.get(category, [])) if isinstance(document.get(category), list) else 0 for category in BRIDGE_CATEGORIES},
        "errors": errors,
    }


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BridgeError("FILE_NOT_FOUND", str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise BridgeError("JSON_INVALID", str(exc)) from exc
    if not isinstance(value, dict):
        raise BridgeError("TYPE_INVALID", "JSON document must be an object")
    return value


def load_candidate_set(path: Path | None = None) -> dict[str, Any]:
    return load_json(path or default_candidate_path())


def load_bridge(path: Path) -> dict[str, Any]:
    return load_json(path)


def build_bridge(
    *,
    candidates: dict[str, Any],
    pack: dict[str, Any],
    description: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    bridge_id: str,
    bridge_version: str,
    company_id: str,
) -> dict[str, Any]:
    candidate_validation = validate_candidate_set(
        candidates,
        pack=pack,
        description=description,
        require_role="confirmed_review",
    )
    if candidate_validation["status"] != "passed":
        raise BridgeError("CANDIDATES_INVALID", "confirmed candidate set is invalid", candidate_validation["errors"])
    pack_validation = validate_pack(pack)
    if pack_validation["status"] != "passed":
        raise BridgeError("PACK_INVALID", "Pack is invalid", pack_validation["errors"])
    snapshot_errors, _ = _validate_snapshot_inputs(description, quality)
    if snapshot_errors:
        raise BridgeError("SNAPSHOT_INPUT_INVALID", "Snapshot compatibility input is invalid", snapshot_errors)
    if not _id(bridge_id) or not _version(bridge_version) or not _id(company_id):
        raise BridgeError("BRIDGE_IDENTITY_INVALID", "bridge_id, bridge_version, and company_id are invalid")
    bridge: dict[str, Any] = {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "bridge_id": bridge_id,
        "bridge_version": bridge_version,
        "company_id": company_id,
        "pack_ref": {"pack_id": pack["pack_id"], "pack_version": pack["pack_version"]},
        "generated_from_candidate_ids": [],
        **{category: [] for category in BRIDGE_CATEGORIES},
    }
    for candidate in candidates["candidates"]:
        category = CATEGORY_FOR_TYPE[candidate["candidate_type"]]
        item = {
            "candidate_id": candidate["candidate_id"],
            "source_locator": candidate["source_locator"],
            "evidence_summary": candidate["evidence_summary"],
            "evidence_refs": candidate["evidence_refs"],
            "status": candidate["status"],
            **candidate["proposed_mapping_or_rule"],
        }
        bridge[category].append(item)
    bridge["generated_from_candidate_ids"] = [
        item["candidate_id"]
        for category in BRIDGE_CATEGORIES
        for item in bridge[category]
    ]
    validation = validate_bridge(bridge, pack=pack, description=description, quality=quality)
    if validation["status"] != "passed":
        raise BridgeError("BRIDGE_BUILD_INVALID", "generated Bridge failed its own contract validation", validation["errors"])
    return bridge
