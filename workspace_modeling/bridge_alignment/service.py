from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from typing import Any, Protocol

from workspace_modeling.business_pack.service import load_pack
from workspace_modeling.company_bridge.service import build_bridge, load_bridge, validate_bridge, validate_candidate_set

from workspace_modeling.bridge_alignment.profile import copy_reference_files, profile_snapshot, scan_reference_files
from workspace_modeling.bridge_alignment.workspace import AlignmentError, load_workspace, write_json


SESSION_ID = re.compile(r"^session_[a-z0-9][a-z0-9_-]{2,55}$")


class CandidateAdapter(Protocol):
    def propose(self, model_input: dict[str, Any]) -> dict[str, Any]: ...


def _pack_summary(pack: dict[str, Any]) -> dict[str, Any]:
    sections = {"concepts": "concept_id", "dimensions": "dimension_id", "metrics": "metric_id"}
    return {
        section: [
            {key: item[key], "name": item["name"], "definition": item.get("definition")}
            for item in pack.get(section, [])
        ]
        for section, key in sections.items()
    }


def _enterprise_decisions(bridge: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = []
    for category in ("overrides", "enum_mappings", "normalization_rules"):
        for item in bridge.get(category, []):
            parameters = item.get("parameters")
            if isinstance(parameters, dict):
                parameters = {key: value for key, value in parameters.items() if "field" not in key and not key.endswith("_aliases")}
            decisions.append({
                "category": category,
                "target_type": item.get("target_type"),
                "target_id": item.get("target_id"),
                "operation": item.get("operation"),
                "parameters": parameters,
                "source_value": item.get("source_value"),
                "normalized_value": item.get("normalized_value"),
                "key": item.get("key"),
                "value": item.get("value"),
            })
    return decisions


def _session_path(paths: dict[str, Path], session_id: str) -> Path:
    return paths["sessions"] / session_id / "session.json"


def _mutable_current_session(paths: dict[str, Path], config: dict[str, Any], session_id: str) -> tuple[Path, dict[str, Any]]:
    session_path = _session_path(paths, session_id)
    session = load_json(session_path)
    if session.get("status") == "completed":
        raise AlignmentError("SESSION_COMPLETED", "completed sessions are read-only")
    if session.get("snapshot_id") != config.get("current_snapshot_id"):
        raise AlignmentError("SESSION_STALE", "session does not belong to the current Snapshot")
    return session_path, session


def start_session(*, root: Path, session_id: str) -> dict[str, Any]:
    paths, config = load_workspace(root)
    if not SESSION_ID.fullmatch(session_id):
        raise AlignmentError("SESSION_ID_INVALID", "session_id is invalid")
    if not config.get("current_snapshot_id") or not config.get("current_warehouse_path"):
        raise AlignmentError("CURRENT_SNAPSHOT_MISSING", "run sync-data before starting alignment")
    session_path = _session_path(paths, session_id)
    if session_path.exists():
        raise AlignmentError("SESSION_EXISTS", "session already exists")
    pack = load_pack(root / config["pack_path"])
    warehouse = root / config["current_warehouse_path"]
    profile, description, quality = profile_snapshot(
        warehouse=warehouse,
        snapshot_id=config["current_snapshot_id"],
        company_id=config["company_id"],
        pack_ref=config["pack_ref"],
    )
    profile["supplemental_evidence"] = scan_reference_files(paths["input_reference"])
    if config.get("bridge_reference_path"):
        bridge = load_bridge(root / config["bridge_reference_path"])
        profile["enterprise_decisions"] = _enterprise_decisions(bridge)
    session = {
        "schema_version": "bridge_alignment_session.v1",
        "session_id": session_id,
        "status": "ready_for_model",
        "snapshot_id": config["current_snapshot_id"],
        "business_port": config.get("business_port", "general"),
        "profile": profile,
        "snapshot_description": description,
        "snapshot_quality": quality,
        "model_candidates": [],
        "questions": [],
        "decisions": [],
    }
    write_json(session_path, session, overwrite=False)
    return _result(root, session)


def load_adapter(reference: str) -> CandidateAdapter:
    module_name, separator, attribute_name = reference.partition(":")
    if not separator:
        raise AlignmentError("ADAPTER_REFERENCE_INVALID", "adapter must use module:attribute")
    try:
        value = getattr(importlib.import_module(module_name), attribute_name)
        adapter = value() if isinstance(value, type) else value
    except (ImportError, AttributeError, TypeError) as exc:
        raise AlignmentError("ADAPTER_LOAD_FAILED", str(exc)) from exc
    if not callable(getattr(adapter, "propose", None)):
        raise AlignmentError("ADAPTER_INVALID", "adapter must implement propose(model_input)")
    return adapter


def _model_input(config: dict[str, Any], session: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "bridge_alignment_model_input.v1",
        "company_id": config["company_id"],
        "snapshot_id": session["snapshot_id"],
        "pack_ref": config["pack_ref"],
        "pack_summary": _pack_summary(pack),
        "profile": session["profile"],
        "confirmed_decisions": session["decisions"],
    }


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _candidate_key(candidate: dict[str, Any]) -> str:
    proposal = candidate["proposed_mapping_or_rule"]
    target = candidate["target"]
    parts = [
        candidate["candidate_type"], proposal.get("source_id"), proposal.get("relation"),
        proposal.get("field_name"), proposal.get("source_value"), target.get("target_type"),
        target.get("target_id"), candidate["capability_id"],
    ]
    key = "cand_" + "_".join(filter(None, (_slug(item) for item in parts)))
    return key[:95].rstrip("_")


def _as_review(candidate: dict[str, Any], status: str, proposal: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "candidate_id": candidate["candidate_key"],
        "candidate_type": candidate["candidate_type"],
        "source_locator": candidate["evidence"][0]["locator"],
        "evidence_summary": "; ".join(item["summary"] for item in candidate["evidence"]),
        "proposed_mapping_or_rule": proposal or candidate["proposed_mapping_or_rule"],
        "status": status,
        "evidence_refs": list(dict.fromkeys(item["locator"] for item in candidate["evidence"])),
    }


def _validate_model_output(document: Any, *, config: dict[str, Any], session: dict[str, Any], pack: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(document, dict) or document.get("schema_version") != "bridge_alignment_model_candidates.v1":
        raise AlignmentError("MODEL_OUTPUT_INVALID", "adapter returned an unsupported document")
    candidates = document.get("candidates")
    if not isinstance(candidates, list):
        raise AlignmentError("MODEL_OUTPUT_INVALID", "candidates must be an array")
    prepared = []
    for index, item in enumerate(candidates):
        if not isinstance(item, dict):
            raise AlignmentError("MODEL_OUTPUT_INVALID", "candidate must be an object")
        required = {"candidate_type", "proposed_mapping_or_rule", "target", "confidence", "evidence", "alternative_explanations", "must_ask", "criticality", "capability_id", "question", "answer_options"}
        if set(item) != required:
            raise AlignmentError("MODEL_OUTPUT_FIELDS_INVALID", f"candidate {index} fields are invalid")
        if isinstance(item["confidence"], bool) or not isinstance(item["confidence"], (int, float)) or not 0 <= item["confidence"] <= 1:
            raise AlignmentError("MODEL_OUTPUT_CONFIDENCE_INVALID", "confidence must be between 0 and 1")
        if item["criticality"] not in {"critical", "optional"} or not isinstance(item["must_ask"], bool):
            raise AlignmentError("MODEL_OUTPUT_QUESTION_INVALID", "criticality or must_ask is invalid")
        if (
            not isinstance(item["evidence"], list)
            or not item["evidence"]
            or not all(
                isinstance(evidence, dict)
                and set(evidence) == {"locator", "summary"}
                and isinstance(evidence["locator"], str)
                and evidence["locator"]
                and not Path(evidence["locator"]).is_absolute()
                and isinstance(evidence["summary"], str)
                and evidence["summary"].strip()
                for evidence in item["evidence"]
            )
        ):
            raise AlignmentError("MODEL_OUTPUT_EVIDENCE_INVALID", "evidence is required")
        if (item["must_ask"] or item["criticality"] == "critical") and not item["question"]:
            raise AlignmentError("MODEL_OUTPUT_QUESTION_REQUIRED", "material ambiguity requires a question")
        if item["question"] is not None and (not isinstance(item["answer_options"], list) or len(item["answer_options"]) < 2):
            raise AlignmentError("MODEL_OUTPUT_OPTIONS_INVALID", "questions require at least two options")
        prepared_item = {**item, "candidate_key": _candidate_key(item)}
        prepared.append(prepared_item)
    keys = [item["candidate_key"] for item in prepared]
    if len(keys) != len(set(keys)):
        raise AlignmentError("CANDIDATE_KEY_CONFLICT", "model candidates share the same semantic identity")
    review_items = [_as_review(item, "proposed") for item in prepared]
    candidate_set = {
        "schema_version": "company_bridge_candidates.v1",
        "candidate_set_role": "historical_scan",
        "candidate_set_id": f"candidates_{session['session_id'][8:]}",
        "company_id": config["company_id"],
        "pack_ref": config["pack_ref"],
        "candidates": review_items,
        "rejections": [],
        "summary": {"candidate_count": len(review_items), "rejection_count": 0},
    }
    validation = validate_candidate_set(candidate_set, pack=pack, description=session["snapshot_description"])
    if validation["status"] != "passed":
        error = validation["errors"][0]
        raise AlignmentError("MODEL_PROPOSAL_INVALID", error["message"], path=error["path"])
    option_items = []
    for candidate_index, item in enumerate(prepared):
        option_ids = set()
        for option_index, option in enumerate(item["answer_options"]):
            if (
                not isinstance(option, dict)
                or set(option) != {"option_id", "label", "resulting_status", "proposal"}
                or not isinstance(option["option_id"], str)
                or not option["option_id"]
                or option["option_id"] in option_ids
                or not isinstance(option["label"], str)
                or not option["label"].strip()
                or option["resulting_status"] not in {"confirmed", "unresolved"}
                or not isinstance(option["proposal"], dict)
            ):
                raise AlignmentError("MODEL_OUTPUT_OPTIONS_INVALID", "answer option is invalid")
            option_ids.add(option["option_id"])
            option_item = _as_review(item, "proposed", option["proposal"])
            option_item["candidate_id"] = f"cand_option_{candidate_index}_{option_index}"
            option_items.append(option_item)
    if option_items:
        option_set = {
            **candidate_set,
            "candidates": option_items,
            "summary": {"candidate_count": len(option_items), "rejection_count": 0},
        }
        option_validation = validate_candidate_set(option_set, pack=pack, description=session["snapshot_description"])
        if option_validation["status"] != "passed":
            error = option_validation["errors"][0]
            raise AlignmentError("MODEL_OPTION_PROPOSAL_INVALID", error["message"], path=error["path"])
    return prepared


def _refresh_questions(session: dict[str, Any]) -> None:
    decided = {item["candidate_key"] for item in session["decisions"]}
    session["questions"] = [
        {
            "candidate_key": item["candidate_key"],
            "prompt": item["question"],
            "criticality": item["criticality"],
            "why_it_matters": item["evidence"][0]["summary"],
            "options": item["answer_options"],
        }
        for item in session["model_candidates"]
        if item["candidate_key"] not in decided and item["question"] is not None
    ]
    session["status"] = "awaiting_confirmation" if session["questions"] else "ready_to_finalize"


def propose_candidates(*, root: Path, session_id: str, adapter: CandidateAdapter) -> dict[str, Any]:
    paths, config = load_workspace(root)
    session_path, session = _mutable_current_session(paths, config, session_id)
    pack = load_pack(root / config["pack_path"])
    try:
        document = adapter.propose(_model_input(config, session, pack))
    except Exception as exc:
        raise AlignmentError("ADAPTER_FAILED", str(exc)) from exc
    session["model_candidates"] = _validate_model_output(document, config=config, session=session, pack=pack)
    _refresh_questions(session)
    write_json(session_path, session)
    return _result(root, session)


def answer_question(
    *, root: Path, session_id: str, candidate_key: str, option_id: str,
    answer_text: str, confirmed_by: str,
) -> dict[str, Any]:
    paths, config = load_workspace(root)
    session_path, session = _mutable_current_session(paths, config, session_id)
    if any(item["candidate_key"] == candidate_key for item in session["decisions"]):
        raise AlignmentError("DECISION_EXISTS", "this semantic candidate already has a decision")
    candidate = next((item for item in session["model_candidates"] if item["candidate_key"] == candidate_key), None)
    if candidate is None:
        raise AlignmentError("QUESTION_NOT_FOUND", "candidate does not exist")
    option = next((item for item in candidate["answer_options"] if item["option_id"] == option_id), None)
    if option is None:
        raise AlignmentError("OPTION_NOT_FOUND", "option does not exist")
    if not answer_text.strip() or not confirmed_by.strip():
        raise AlignmentError("ANSWER_INVALID", "answer_text and confirmed_by must be non-empty")
    session["decisions"].append({
        "candidate_key": candidate_key,
        "selected_option_id": option_id,
        "answer_text": answer_text,
        "resulting_status": option["resulting_status"],
        "proposal": option["proposal"],
        "confirmed_by": confirmed_by,
        "criticality": candidate["criticality"],
        "capability_id": candidate["capability_id"],
        "candidate": candidate,
    })
    _refresh_questions(session)
    write_json(session_path, session)
    return _result(root, session)


def add_evidence(*, root: Path, session_id: str, evidence_root: Path, adapter: CandidateAdapter) -> dict[str, Any]:
    paths, config = load_workspace(root)
    session_path, session = _mutable_current_session(paths, config, session_id)
    updated = copy_reference_files(evidence_root, paths["input_reference"])
    session["profile"]["supplemental_evidence"] = scan_reference_files(paths["input_reference"])
    write_json(session_path, session)
    result = propose_candidates(root=root, session_id=session_id, adapter=adapter)
    result["updated_reference_files"] = updated
    return result


def _unresolved(decision: dict[str, Any]) -> dict[str, Any]:
    candidate = decision["candidate"]
    proposal = candidate["proposed_mapping_or_rule"]
    target = candidate["target"]
    unresolved = {
        **({"source_id": proposal.get("source_id")} if proposal.get("source_id") else {}),
        **({"relation": proposal.get("relation")} if proposal.get("relation") else {}),
        **({"field_name": proposal.get("field_name")} if proposal.get("field_name") else {}),
        **({"blocked_target_type": target.get("target_type")} if target.get("target_type") else {}),
        **({"blocked_target_id": target.get("target_id")} if target.get("target_id") else {}),
        "reason": decision["answer_text"],
    }
    item = _as_review({**candidate, "candidate_type": "unresolved"}, "unresolved", unresolved)
    item["decision_note"] = decision["answer_text"]
    item["decision_by"] = decision["confirmed_by"]
    return item


def finalize_session(*, root: Path, session_id: str, bridge_id: str, bridge_version: str) -> dict[str, Any]:
    paths, config = load_workspace(root)
    session_path, session = _mutable_current_session(paths, config, session_id)
    if not session["model_candidates"]:
        raise AlignmentError("CANDIDATES_MISSING", "run propose before finalizing the Bridge", session_id=session_id)
    pending_critical = [item for item in session["questions"] if item["criticality"] == "critical"]
    if pending_critical:
        raise AlignmentError("CRITICAL_QUESTIONS_PENDING", "critical questions remain unanswered", session_id=session_id, pending_questions=pending_critical)
    critical_unresolved = [item for item in session["decisions"] if item["criticality"] == "critical" and item["resulting_status"] == "unresolved"]
    if critical_unresolved:
        raise AlignmentError("CRITICAL_AMBIGUITY_UNRESOLVED", "critical ambiguity cannot complete the Bridge", session_id=session_id)
    decided = {item["candidate_key"] for item in session["decisions"]}
    implicit_unresolved = [
        {
            "candidate_key": item["candidate_key"], "answer_text": "非关键候选未确认，禁用对应能力。",
            "resulting_status": "unresolved", "confirmed_by": "system_disabled",
            "criticality": "optional", "capability_id": item["capability_id"], "candidate": item,
        }
        for item in session["model_candidates"] if item["candidate_key"] not in decided
    ]
    decisions = session["decisions"] + implicit_unresolved
    reviewed = []
    for decision in decisions:
        if decision["resulting_status"] == "unresolved":
            reviewed.append(_unresolved(decision))
        else:
            item = _as_review(decision["candidate"], "confirmed", decision["proposal"])
            item["decision_note"] = decision["answer_text"]
            item["decision_by"] = decision["confirmed_by"]
            reviewed.append(item)
    review = {
        "schema_version": "company_bridge_candidates.v1", "candidate_set_role": "confirmed_review",
        "candidate_set_id": f"review_{session_id[8:]}", "company_id": config["company_id"],
        "pack_ref": config["pack_ref"], "candidates": reviewed, "rejections": [],
        "summary": {"candidate_count": len(reviewed), "rejection_count": 0},
    }
    pack = load_pack(root / config["pack_path"])
    validation = validate_candidate_set(review, pack=pack, description=session["snapshot_description"], require_role="confirmed_review")
    if validation["status"] != "passed":
        error = validation["errors"][0]
        raise AlignmentError("CONFIRMED_REVIEW_INVALID", error["message"], path=error["path"])
    bridge = build_bridge(
        candidates=review, pack=pack, description=session["snapshot_description"], quality=session["snapshot_quality"],
        bridge_id=bridge_id, bridge_version=bridge_version, company_id=config["company_id"],
    )
    bridge_validation = validate_bridge(bridge, pack=pack, description=session["snapshot_description"], quality=session["snapshot_quality"])
    output = paths["output_bridge"] / bridge_version
    if output.exists():
        raise AlignmentError("OUTPUT_EXISTS", "Bridge version output already exists")
    output.mkdir(parents=True)
    write_json(output / "confirmed_review.json", review, overwrite=False)
    write_json(output / "company_bridge.v1.json", bridge, overwrite=False)
    write_json(output / "validation.json", bridge_validation, overwrite=False)
    paths["bridge_reference"].parent.mkdir(parents=True, exist_ok=True)
    write_json(paths["bridge_reference"], bridge)
    config["bridge_reference_path"] = "Work/Bridge/reference.json"
    write_json(paths["config"], config)
    session["status"] = "completed"
    write_json(session_path, session)
    return {
        "schema_version": "bridge_alignment_result.v1", "status": "completed", "session_id": session_id,
        "artifacts": {"confirmed_review": str((output / "confirmed_review.json").resolve()), "bridge": str((output / "company_bridge.v1.json").resolve()), "validation": str((output / "validation.json").resolve())},
        "pending_questions": [],
        "disabled_capabilities": sorted({item["capability_id"] for item in decisions if item["resulting_status"] == "unresolved"}),
        "errors": [],
    }


def _result(root: Path, session: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "bridge_alignment_result.v1", "status": session["status"],
        "session_id": session["session_id"],
        "session_path": str((root / "Work" / "Sessions" / session["session_id"] / "session.json").resolve()),
        "pending_questions": session["questions"],
        "disabled_capabilities": sorted({item["capability_id"] for item in session["decisions"] if item["resulting_status"] == "unresolved"}),
        "errors": [],
    }


def load_json(path: Path) -> dict[str, Any]:
    from workspace_modeling.bridge_alignment.workspace import load_json as workspace_load_json
    return workspace_load_json(path)
