from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,95}$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SECTIONS = {
    "concepts": "concept_id",
    "dimensions": "dimension_id",
    "metrics": "metric_id",
    "taxonomies": "taxonomy_id",
    "journeys": "journey_id",
    "funnels": "funnel_id",
    "playbooks": "playbook_id",
    "references": "reference_id",
}


class PackError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def default_pack_path() -> Path:
    return Path(__file__).parent / "packs" / "education_training_operations_cn" / "pack.json"


def _problem(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _string_list(
    value: Any,
    *,
    path: str,
    errors: list[dict[str, str]],
) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        errors.append(_problem("TYPE_INVALID", path, "must be an array of strings"))
        return []
    return value


def _require_text(
    entry: dict[str, Any],
    field: str,
    *,
    path: str,
    errors: list[dict[str, str]],
) -> None:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(_problem("FIELD_REQUIRED", f"{path}.{field}", "must be a non-empty string"))


def _index_sections(
    document: dict[str, Any], errors: list[dict[str, str]]
) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, set[str]]]:
    indexes: dict[str, dict[str, dict[str, Any]]] = {}
    journey_stages: dict[str, set[str]] = {}
    for section, id_field in SECTIONS.items():
        entries = document.get(section)
        if not isinstance(entries, list):
            errors.append(_problem("TYPE_INVALID", section, "must be an array"))
            indexes[section] = {}
            continue
        index: dict[str, dict[str, Any]] = {}
        for position, entry in enumerate(entries):
            path = f"{section}[{position}]"
            if not isinstance(entry, dict):
                errors.append(_problem("TYPE_INVALID", path, "must be an object"))
                continue
            identifier = entry.get(id_field)
            if not isinstance(identifier, str) or not ID_PATTERN.fullmatch(identifier):
                errors.append(_problem("ID_INVALID", f"{path}.{id_field}", "must be a stable lowercase identifier"))
                continue
            if identifier in index:
                errors.append(_problem("ID_DUPLICATE", f"{path}.{id_field}", f"duplicate identifier: {identifier}"))
                continue
            if not isinstance(entry.get("name"), str) or not entry["name"].strip():
                errors.append(_problem("FIELD_REQUIRED", f"{path}.name", "must be a non-empty string"))
            index[identifier] = entry
        indexes[section] = index

    for journey_id, journey in indexes.get("journeys", {}).items():
        stages = journey.get("stages")
        if not isinstance(stages, list):
            errors.append(_problem("TYPE_INVALID", f"journeys.{journey_id}.stages", "must be an array"))
            continue
        stage_ids: set[str] = set()
        for position, stage in enumerate(stages):
            path = f"journeys.{journey_id}.stages[{position}]"
            if not isinstance(stage, dict):
                errors.append(_problem("TYPE_INVALID", path, "must be an object"))
                continue
            stage_id = stage.get("stage_id")
            if not isinstance(stage_id, str) or not ID_PATTERN.fullmatch(stage_id):
                errors.append(_problem("ID_INVALID", f"{path}.stage_id", "must be a stable lowercase identifier"))
                continue
            if stage_id in stage_ids:
                errors.append(_problem("ID_DUPLICATE", f"{path}.stage_id", f"duplicate stage: {stage_id}"))
            stage_ids.add(stage_id)
        journey_stages[journey_id] = stage_ids
    return indexes, journey_stages


def _check_references(
    indexes: dict[str, dict[str, dict[str, Any]]],
    journey_stages: dict[str, set[str]],
    errors: list[dict[str, str]],
) -> None:
    concept_ids = set(indexes.get("concepts", {}))
    dimension_ids = set(indexes.get("dimensions", {}))
    metric_ids = set(indexes.get("metrics", {}))
    journey_ids = set(indexes.get("journeys", {}))
    taxonomy_ids = set(indexes.get("taxonomies", {}))
    used_taxonomy_ids: set[str] = set()

    def require_known(values: list[str], known: set[str], path: str, kind: str) -> None:
        for value in values:
            if value not in known:
                errors.append(_problem("REFERENCE_UNKNOWN", path, f"unknown {kind}: {value}"))

    for concept_id, concept in indexes.get("concepts", {}).items():
        _require_text(concept, "definition", path=f"concepts.{concept_id}", errors=errors)
        values = _string_list(concept.get("related_concept_ids", []), path=f"concepts.{concept_id}.related_concept_ids", errors=errors)
        require_known(values, concept_ids, f"concepts.{concept_id}.related_concept_ids", "concept")

    for dimension_id, dimension in indexes.get("dimensions", {}).items():
        path = f"dimensions.{dimension_id}"
        _require_text(dimension, "definition", path=path, errors=errors)
        taxonomy_id = dimension.get("taxonomy_id")
        if taxonomy_id is not None and taxonomy_id not in taxonomy_ids:
            errors.append(_problem("REFERENCE_UNKNOWN", f"{path}.taxonomy_id", f"unknown taxonomy: {taxonomy_id}"))
        elif isinstance(taxonomy_id, str):
            used_taxonomy_ids.add(taxonomy_id)

    for metric_id, metric in indexes.get("metrics", {}).items():
        path = f"metrics.{metric_id}"
        for field in ("definition", "formula_semantics", "unit"):
            _require_text(metric, field, path=path, errors=errors)
        time_dimensions = _string_list(metric.get("time_dimension_ids"), path=f"{path}.time_dimension_ids", errors=errors)
        concepts = _string_list(metric.get("required_concept_ids", []), path=f"metrics.{metric_id}.required_concept_ids", errors=errors)
        dimensions = _string_list(metric.get("compatible_dimension_ids", []), path=f"metrics.{metric_id}.compatible_dimension_ids", errors=errors)
        dependencies = _string_list(metric.get("depends_on_metric_ids", []), path=f"metrics.{metric_id}.depends_on_metric_ids", errors=errors)
        if not time_dimensions:
            errors.append(_problem("FIELD_REQUIRED", f"{path}.time_dimension_ids", "must contain at least one time dimension"))
        require_known(time_dimensions, dimension_ids, f"{path}.time_dimension_ids", "dimension")
        for dimension_id in time_dimensions:
            if not dimension_id.startswith("time."):
                errors.append(_problem("REFERENCE_INVALID", f"{path}.time_dimension_ids", f"not a time dimension: {dimension_id}"))
        require_known(concepts, concept_ids, f"metrics.{metric_id}.required_concept_ids", "concept")
        require_known(dimensions, dimension_ids, f"metrics.{metric_id}.compatible_dimension_ids", "dimension")
        require_known(dependencies, metric_ids, f"metrics.{metric_id}.depends_on_metric_ids", "metric")
        if metric_id in dependencies:
            errors.append(_problem("REFERENCE_CYCLE", f"metrics.{metric_id}.depends_on_metric_ids", "metric cannot depend on itself"))

    for journey_id, journey in indexes.get("journeys", {}).items():
        _require_text(journey, "description", path=f"journeys.{journey_id}", errors=errors)
        stage_ids = journey_stages.get(journey_id, set())
        if not stage_ids:
            errors.append(_problem("FIELD_REQUIRED", f"journeys.{journey_id}.stages", "must contain at least one stage"))
        for position, stage in enumerate(journey.get("stages", [])):
            if not isinstance(stage, dict):
                continue
            concept_id = stage.get("concept_id")
            if concept_id not in concept_ids:
                errors.append(_problem("REFERENCE_UNKNOWN", f"journeys.{journey_id}.stages[{position}].concept_id", f"unknown concept: {concept_id}"))
            if not isinstance(stage.get("optional"), bool):
                errors.append(_problem("TYPE_INVALID", f"journeys.{journey_id}.stages[{position}].optional", "must be a boolean"))
        transitions = journey.get("transitions", [])
        if not isinstance(transitions, list):
            errors.append(_problem("TYPE_INVALID", f"journeys.{journey_id}.transitions", "must be an array"))
            continue
        for position, transition in enumerate(transitions):
            path = f"journeys.{journey_id}.transitions[{position}]"
            if not isinstance(transition, dict):
                errors.append(_problem("TYPE_INVALID", path, "must be an object"))
                continue
            for field in ("from_stage_id", "to_stage_id"):
                if transition.get(field) not in stage_ids:
                    errors.append(_problem("REFERENCE_UNKNOWN", f"{path}.{field}", f"unknown journey stage: {transition.get(field)}"))
            _require_text(transition, "kind", path=path, errors=errors)

    for funnel_id, funnel in indexes.get("funnels", {}).items():
        _require_text(funnel, "measurement", path=f"funnels.{funnel_id}", errors=errors)
        journey_id = funnel.get("journey_id")
        if journey_id not in journey_ids:
            errors.append(_problem("REFERENCE_UNKNOWN", f"funnels.{funnel_id}.journey_id", f"unknown journey: {journey_id}"))
            continue
        stages = _string_list(funnel.get("stage_ids", []), path=f"funnels.{funnel_id}.stage_ids", errors=errors)
        if not stages:
            errors.append(_problem("FIELD_REQUIRED", f"funnels.{funnel_id}.stage_ids", "must contain at least one stage"))
        require_known(stages, journey_stages.get(journey_id, set()), f"funnels.{funnel_id}.stage_ids", "journey stage")

    for playbook_id, playbook in indexes.get("playbooks", {}).items():
        _require_text(playbook, "use_when", path=f"playbooks.{playbook_id}", errors=errors)
        metrics = _string_list(playbook.get("metric_ids", []), path=f"playbooks.{playbook_id}.metric_ids", errors=errors)
        dimensions = _string_list(playbook.get("dimension_ids", []), path=f"playbooks.{playbook_id}.dimension_ids", errors=errors)
        require_known(metrics, metric_ids, f"playbooks.{playbook_id}.metric_ids", "metric")
        require_known(dimensions, dimension_ids, f"playbooks.{playbook_id}.dimension_ids", "dimension")
        hypotheses = playbook.get("hypotheses")
        if not isinstance(hypotheses, list) or not hypotheses:
            errors.append(_problem("FIELD_REQUIRED", f"playbooks.{playbook_id}.hypotheses", "must contain at least one diagnostic hypothesis"))
            continue
        seen: set[str] = set()
        for position, hypothesis in enumerate(hypotheses):
            path = f"playbooks.{playbook_id}.hypotheses[{position}]"
            if not isinstance(hypothesis, dict):
                errors.append(_problem("TYPE_INVALID", path, "must be an object"))
                continue
            for field in ("statement", "reason", "evidence_check"):
                _require_text(hypothesis, field, path=path, errors=errors)
            hypothesis_id = hypothesis.get("hypothesis_id")
            if not isinstance(hypothesis_id, str) or not ID_PATTERN.fullmatch(hypothesis_id):
                errors.append(_problem("ID_INVALID", f"{path}.hypothesis_id", "must be a stable lowercase identifier"))
            elif hypothesis_id in seen:
                errors.append(_problem("ID_DUPLICATE", f"{path}.hypothesis_id", f"duplicate hypothesis: {hypothesis_id}"))
            else:
                seen.add(hypothesis_id)

    for taxonomy_id, taxonomy in indexes.get("taxonomies", {}).items():
        if taxonomy_id not in used_taxonomy_ids:
            errors.append(_problem("REFERENCE_UNUSED", f"taxonomies.{taxonomy_id}", "taxonomy must be referenced by a dimension"))
        members = taxonomy.get("members")
        path = f"taxonomies.{taxonomy_id}.members"
        if not isinstance(members, list) or not members:
            errors.append(_problem("FIELD_REQUIRED", path, "must contain at least one member"))
            continue
        seen: set[str] = set()
        for position, member in enumerate(members):
            member_path = f"{path}[{position}]"
            if not isinstance(member, dict):
                errors.append(_problem("TYPE_INVALID", member_path, "must be an object"))
                continue
            member_id = member.get("member_id")
            if not isinstance(member_id, str) or not ID_PATTERN.fullmatch(member_id):
                errors.append(_problem("ID_INVALID", f"{member_path}.member_id", "must be a stable lowercase identifier"))
            elif member_id in seen:
                errors.append(_problem("ID_DUPLICATE", f"{member_path}.member_id", f"duplicate member: {member_id}"))
            else:
                seen.add(member_id)
            _require_text(member, "name", path=member_path, errors=errors)

    for reference_id, reference in indexes.get("references", {}).items():
        path = f"references.{reference_id}"
        _require_text(reference, "url", path=path, errors=errors)
        _require_text(reference, "note", path=path, errors=errors)


def validate_pack(document: Any) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    if not isinstance(document, dict):
        errors.append(_problem("TYPE_INVALID", "$", "pack must be a JSON object"))
        return {"schema_version": "business_pack_validation.v1", "status": "failed", "errors": errors}

    required = ("schema_version", "pack_id", "pack_version", "name", *SECTIONS)
    for field in required:
        if field not in document:
            errors.append(_problem("FIELD_REQUIRED", field, "field is required"))
    if document.get("schema_version") != "business_pack.v1":
        errors.append(_problem("SCHEMA_UNSUPPORTED", "schema_version", "expected business_pack.v1"))
    if not isinstance(document.get("pack_id"), str) or not ID_PATTERN.fullmatch(document.get("pack_id", "")):
        errors.append(_problem("ID_INVALID", "pack_id", "must be a stable lowercase identifier"))
    if not isinstance(document.get("pack_version"), str) or not VERSION_PATTERN.fullmatch(document.get("pack_version", "")):
        errors.append(_problem("VERSION_INVALID", "pack_version", "must use MAJOR.MINOR.PATCH"))
    for field in ("name", "scope"):
        _require_text(document, field, path="$", errors=errors)

    indexes, journey_stages = _index_sections(document, errors)
    _check_references(indexes, journey_stages, errors)
    counts = {section: len(indexes.get(section, {})) for section in SECTIONS}
    return {
        "schema_version": "business_pack_validation.v1",
        "status": "failed" if errors else "passed",
        "pack_id": document.get("pack_id"),
        "pack_version": document.get("pack_version"),
        "counts": counts,
        "errors": errors,
    }


def load_pack(path: Path | None = None) -> dict[str, Any]:
    pack_path = path or default_pack_path()
    try:
        document = json.loads(pack_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PackError("PACK_NOT_FOUND", str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise PackError("PACK_JSON_INVALID", str(exc)) from exc
    validation = validate_pack(document)
    if validation["status"] != "passed":
        raise PackError("PACK_INVALID", json.dumps(validation["errors"], ensure_ascii=False))
    return document


def describe_pack(path: Path | None = None) -> dict[str, Any]:
    document = load_pack(path)
    inventory = {}
    for section, id_field in SECTIONS.items():
        inventory[section] = [
            {id_field: item[id_field], "name": item["name"]}
            for item in document[section]
        ]
    return {
        "schema_version": "business_pack_description.v1",
        "status": "passed",
        "pack_id": document["pack_id"],
        "pack_version": document["pack_version"],
        "name": document["name"],
        "scope": document.get("scope"),
        "inventory": inventory,
    }
