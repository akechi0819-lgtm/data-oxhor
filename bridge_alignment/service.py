from __future__ import annotations

import csv
import hashlib
import importlib
import json
import re
from pathlib import Path
from typing import Any, Protocol

from business_pack.service import load_pack, validate_pack
from company_bridge.service import (
    BridgeError,
    build_bridge,
    load_bridge,
    validate_bridge,
    validate_candidate_set,
)
from data_foundation.connectors.xlsx import XlsxReadError, inspect_workbook, sha256_file
from data_foundation.query.service import describe_warehouse, execute_query


SESSION_ID = re.compile(r"^session_[a-z0-9][a-z0-9_-]{2,55}$")
SUPPORTED_EVIDENCE = {".csv", ".json", ".jsonl", ".md", ".txt", ".xlsx", ".xlsm", ".yaml", ".yml"}
SKIP_DIRECTORIES = {".git", ".venv", "__pycache__", "node_modules"}


class CandidateAdapter(Protocol):
    def propose(self, model_input: dict[str, Any]) -> dict[str, Any]: ...


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


def _write_json(path: Path, document: dict[str, Any], *, overwrite: bool = True) -> None:
    if path.exists() and not overwrite:
        raise AlignmentError("OUTPUT_EXISTS", f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AlignmentError("FILE_NOT_FOUND", str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise AlignmentError("JSON_INVALID", str(exc)) from exc
    if not isinstance(value, dict):
        raise AlignmentError("TYPE_INVALID", f"JSON object required: {path}")
    return value


def _session_paths(session_dir: Path) -> dict[str, Path]:
    return {
        "state": session_dir / "session.json",
        "description": session_dir / "snapshot_description.json",
        "quality": session_dir / "snapshot_quality.json",
        "profile": session_dir / "profile.json",
        "model_input": session_dir / "model_input.json",
        "candidates": session_dir / "model_candidates.json",
        "questions": session_dir / "questions.json",
        "decisions": session_dir / "decisions.jsonl",
    }


def _artifacts(paths: dict[str, Path], names: tuple[str, ...]) -> dict[str, str]:
    return {name: str(paths[name].resolve()) for name in names if paths[name].exists()}


def _set_state(paths: dict[str, Path], status: str) -> dict[str, Any]:
    state = _load_json(paths["state"])
    state["status"] = status
    _write_json(paths["state"], state)
    return state


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _query_inline(
    *, warehouse: Path, snapshot_id: str, sql: str, run_id: str, output_root: Path, max_rows: int
) -> dict[str, Any]:
    result = execute_query(
        warehouse=warehouse,
        snapshot_id=snapshot_id,
        sql=sql,
        run_id=run_id,
        output_root=output_root,
        max_rows=max_rows,
        max_result_bytes=4_000_000,
        inline_bytes=4_000_000,
    )
    payload = result.get("result")
    if not isinstance(payload, dict):
        raise AlignmentError("PROFILE_QUERY_INVALID", "profile query did not return inline rows")
    return payload


def _row_dicts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(zip(payload["columns"], row)) for row in payload["rows"]]


def _header_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for position, row in enumerate(rows, 1):
        labels = []
        for key, value in row.items():
            if not key.startswith("column_") or not isinstance(value, str) or not value.strip():
                continue
            labels.append({"column": key, "label": value.strip()[:160]})
        if len(labels) < 2:
            continue
        score = round(min(0.55 + len(labels) * 0.05 - (position - 1) * 0.04, 0.99), 4)
        candidates.append({"sample_position": position, "score": score, "labels": labels})
    return sorted(candidates, key=lambda item: (-item["score"], item["sample_position"]))[:5]


def _profile_snapshot(
    *, warehouse: Path, snapshot_id: str, session_id: str, company_id: str,
    pack_ref: dict[str, str], session_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    description = describe_warehouse(warehouse=warehouse, snapshot_id=snapshot_id)
    run_id = "run_" + hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:20]
    sheets = _row_dicts(_query_inline(
        warehouse=warehouse,
        snapshot_id=snapshot_id,
        sql=("SELECT source_id, sheet_name, target_table, meaningful_rows, landing_rows "
             "FROM ingest.sheets ORDER BY source_id, sheet_name"),
        run_id=run_id,
        output_root=session_dir,
        max_rows=1000,
    ))
    quality_result = execute_query(
        warehouse=warehouse,
        snapshot_id=snapshot_id,
        sql="SELECT * FROM quality.issues ORDER BY source_id, sheet_name LIMIT 1000",
        run_id=run_id,
        output_root=session_dir,
        max_rows=1000,
        max_result_bytes=4_000_000,
        inline_bytes=4_000_000,
    )
    relations_by_name = {
        f"{item['schema']}.{item['name']}": item
        for item in description["relations"]
        if item["schema"] == "landing"
    }
    sheet_by_relation = {f"landing.{item['target_table']}": item for item in sheets}
    relations = []
    for relation_name, relation_description in sorted(relations_by_name.items()):
        schema, name = relation_name.split(".", 1)
        sample = _row_dicts(_query_inline(
            warehouse=warehouse,
            snapshot_id=snapshot_id,
            sql=f"SELECT * FROM {_quote(schema)}.{_quote(name)} ORDER BY source_row_number LIMIT 20",
            run_id=run_id,
            output_root=session_dir,
            max_rows=20,
        ))
        sheet = sheet_by_relation.get(relation_name, {})
        relations.append({
            "relation": relation_name,
            "source_id": sheet.get("source_id"),
            "sheet_name": sheet.get("sheet_name"),
            "columns": relation_description["columns"],
            "sample_rows": sample,
            "header_candidates": _header_candidates(sample),
        })
    profile = {
        "schema_version": "bridge_alignment_profile.v1",
        "session_id": session_id,
        "company_id": company_id,
        "snapshot_id": snapshot_id,
        "pack_ref": pack_ref,
        "relations": relations,
        "supplemental_evidence": [],
        "enterprise_decisions": [],
    }
    return profile, description, quality_result


def _enterprise_decisions(existing_bridge: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = []
    for category in ("overrides", "enum_mappings", "normalization_rules"):
        for item in existing_bridge.get(category, []):
            parameters = item.get("parameters")
            semantic_parameters = None
            if isinstance(parameters, dict):
                semantic_parameters = {
                    key: value
                    for key, value in parameters.items()
                    if "field" not in key and not key.endswith("_aliases")
                }
            decisions.append({
                "category": category,
                "target_type": item.get("target_type"),
                "target_id": item.get("target_id"),
                "operation": item.get("operation"),
                "parameters": semantic_parameters,
                "source_value": item.get("source_value"),
                "normalized_value": item.get("normalized_value"),
                "target_taxonomy_id": item.get("target_taxonomy_id"),
                "target_member_id": item.get("target_member_id"),
                "key": item.get("key"),
                "value": item.get("value"),
            })
    return decisions


def _pack_summary(pack: dict[str, Any]) -> dict[str, Any]:
    sections = {
        "concepts": "concept_id",
        "dimensions": "dimension_id",
        "metrics": "metric_id",
    }
    return {
        section: [
            {key: item[key], "name": item["name"], "definition": item.get("definition"),
             **({"formula_semantics": item.get("formula_semantics")} if section == "metrics" else {})}
            for item in pack.get(section, [])
        ]
        for section, key in sections.items()
    }


def _load_decisions(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    decisions = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AlignmentError("DECISIONS_INVALID", f"invalid decision at line {line_number}") from exc
        if not isinstance(value, dict):
            raise AlignmentError("DECISIONS_INVALID", f"decision line {line_number} must be an object")
        decisions.append(value)
    return decisions


def _model_input(state: dict[str, Any], profile: dict[str, Any], pack: dict[str, Any], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "bridge_alignment_model_input.v1",
        "session_id": state["session_id"],
        "company_id": state["company_id"],
        "snapshot_id": state["snapshot_id"],
        "pack_ref": state["pack_ref"],
        "pack_summary": _pack_summary(pack),
        "profile": profile,
        "confirmed_decisions": decisions,
        "instructions": {
            "reuse_enterprise_decisions_only_for_same_company": True,
            "do_not_copy_existing_field_bindings": True,
            "all_candidates_are_proposed": True,
            "ask_only_material_ambiguities": True,
        },
    }


def start_session(
    *, workspace: Path, session_id: str, company_id: str, warehouse: Path,
    snapshot_id: str, pack_path: Path, existing_bridge_path: Path | None = None,
) -> dict[str, Any]:
    if not SESSION_ID.fullmatch(session_id):
        raise AlignmentError("SESSION_ID_INVALID", "session_id must match session_[a-z0-9][a-z0-9_-]{2,55}")
    resolved_workspace = workspace.resolve()
    resolved_project = Path(__file__).resolve().parents[1]
    if resolved_workspace == resolved_project or resolved_project in resolved_workspace.parents:
        raise AlignmentError("WORKSPACE_INSIDE_PROJECT", "workspace must be an explicit directory outside the project")
    session_dir = workspace / session_id
    if session_dir.exists():
        raise AlignmentError("SESSION_EXISTS", f"session already exists: {session_dir}")
    pack = load_pack(pack_path)
    pack_validation = validate_pack(pack)
    if pack_validation["status"] != "passed":
        raise AlignmentError("PACK_INVALID", "Pack failed validation")
    pack_ref = {"pack_id": pack["pack_id"], "pack_version": pack["pack_version"]}
    profile, description, quality = _profile_snapshot(
        warehouse=warehouse,
        snapshot_id=snapshot_id,
        session_id=session_id,
        company_id=company_id,
        pack_ref=pack_ref,
        session_dir=session_dir,
    )
    if existing_bridge_path is not None:
        existing_bridge = load_bridge(existing_bridge_path)
        existing_validation = validate_bridge(existing_bridge, pack=pack)
        if existing_validation["status"] != "passed":
            raise AlignmentError("EXISTING_BRIDGE_INVALID", "existing Bridge failed validation")
        if existing_bridge.get("company_id") != company_id:
            raise AlignmentError("EXISTING_BRIDGE_COMPANY_MISMATCH", "existing Bridge belongs to a different company")
        if existing_bridge.get("pack_ref") != pack_ref:
            raise AlignmentError("EXISTING_BRIDGE_PACK_MISMATCH", "existing Bridge uses a different Pack")
        profile["enterprise_decisions"] = _enterprise_decisions(existing_bridge)
    session_dir.mkdir(parents=True, exist_ok=False)
    paths = _session_paths(session_dir)
    state = {
        "schema_version": "bridge_alignment_session.v1",
        "status": "profiling_complete",
        "session_id": session_id,
        "company_id": company_id,
        "snapshot_id": snapshot_id,
        "warehouse": str(warehouse.resolve()),
        "pack_path": str(pack_path.resolve()),
        "pack_ref": pack_ref,
        "existing_bridge": str(existing_bridge_path.resolve()) if existing_bridge_path else None,
    }
    model_input = _model_input(state, profile, pack, [])
    questions = {
        "schema_version": "bridge_alignment_questions.v1",
        "session_id": session_id,
        "questions": [],
    }
    for name, document in (("state", state), ("description", description), ("quality", quality),
                           ("profile", profile), ("model_input", model_input), ("questions", questions)):
        _write_json(paths[name], document, overwrite=False)
    return {
        "schema_version": "bridge_alignment_result.v1",
        "status": "ready_for_model",
        "session_id": session_id,
        "artifacts": _artifacts(paths, ("state", "description", "quality", "profile", "model_input", "questions")),
        "pending_questions": [],
        "disabled_capabilities": [],
        "errors": [],
    }


def load_adapter(reference: str) -> CandidateAdapter:
    module_name, separator, attribute_name = reference.partition(":")
    if not separator or not module_name or not attribute_name:
        raise AlignmentError("ADAPTER_REFERENCE_INVALID", "adapter must use module:attribute")
    try:
        value = getattr(importlib.import_module(module_name), attribute_name)
        adapter = value() if isinstance(value, type) else value
    except (ImportError, AttributeError, TypeError) as exc:
        raise AlignmentError("ADAPTER_LOAD_FAILED", str(exc)) from exc
    if not callable(getattr(adapter, "propose", None)):
        raise AlignmentError("ADAPTER_INVALID", "adapter must implement propose(model_input)")
    return adapter


def _candidate_as_review(
    candidate: dict[str, Any], *, status: str, proposal: dict[str, Any] | None = None,
    decision_note: str | None = None, decision_by: str | None = None,
) -> dict[str, Any]:
    evidence = candidate["evidence"]
    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_type": candidate["candidate_type"],
        "source_locator": evidence[0]["locator"],
        "evidence_summary": "; ".join(item["summary"] for item in evidence),
        "proposed_mapping_or_rule": proposal if proposal is not None else candidate["proposed_mapping_or_rule"],
        "status": status,
        "evidence_refs": list(dict.fromkeys(item["locator"] for item in evidence)),
        **({"decision_note": decision_note} if decision_note else {}),
        **({"decision_by": decision_by} if decision_by else {}),
    }


def _validate_model_candidates(document: dict[str, Any], *, state: dict[str, Any], pack: dict[str, Any], description: dict[str, Any]) -> None:
    if document.get("schema_version") != "bridge_alignment_model_candidates.v1":
        raise AlignmentError("MODEL_OUTPUT_SCHEMA_INVALID", "unsupported model candidate schema")
    if document.get("session_id") != state["session_id"]:
        raise AlignmentError("MODEL_OUTPUT_SESSION_MISMATCH", "model output identifies another session")
    candidates = document.get("candidates")
    if not isinstance(candidates, list):
        raise AlignmentError("MODEL_OUTPUT_INVALID", "candidates must be an array")
    seen: set[str] = set()
    bridge_candidates = []
    option_candidates = []
    for index, candidate in enumerate(candidates):
        path = f"candidates[{index}]"
        if not isinstance(candidate, dict):
            raise AlignmentError("MODEL_OUTPUT_INVALID", "candidate must be an object", path=path)
        required = {"candidate_id", "candidate_type", "proposed_mapping_or_rule", "target", "confidence", "evidence", "alternative_explanations", "must_ask", "criticality", "capability_id", "question", "answer_options"}
        if set(candidate) != required:
            raise AlignmentError("MODEL_OUTPUT_FIELDS_INVALID", f"candidate fields must equal {sorted(required)}", path=path)
        candidate_id = candidate.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id in seen:
            raise AlignmentError("MODEL_OUTPUT_ID_INVALID", "candidate_id must be a unique string", path=f"{path}.candidate_id")
        seen.add(candidate_id)
        confidence = candidate.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise AlignmentError("MODEL_OUTPUT_CONFIDENCE_INVALID", "confidence must be between 0 and 1", path=f"{path}.confidence")
        if candidate.get("criticality") not in {"critical", "optional"} or not isinstance(candidate.get("must_ask"), bool):
            raise AlignmentError("MODEL_OUTPUT_QUESTION_INVALID", "criticality or must_ask is invalid", path=path)
        evidence = candidate.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(isinstance(item, dict) and set(item) == {"locator", "summary"} and isinstance(item["locator"], str) and item["locator"] and not Path(item["locator"]).is_absolute() and isinstance(item["summary"], str) and item["summary"].strip() for item in evidence):
            raise AlignmentError("MODEL_OUTPUT_EVIDENCE_INVALID", "evidence must contain relative locators and summaries", path=f"{path}.evidence")
        alternatives = candidate.get("alternative_explanations")
        if not isinstance(alternatives, list) or not all(isinstance(item, str) and item.strip() for item in alternatives):
            raise AlignmentError("MODEL_OUTPUT_ALTERNATIVES_INVALID", "alternative_explanations must be strings", path=f"{path}.alternative_explanations")
        question = candidate.get("question")
        options = candidate.get("answer_options")
        needs_question = candidate["must_ask"] or candidate["criticality"] == "critical"
        if needs_question and (not isinstance(question, str) or not question.strip()):
            raise AlignmentError("MODEL_OUTPUT_QUESTION_REQUIRED", "material ambiguity requires a question", path=f"{path}.question")
        if question is not None:
            if not isinstance(options, list) or len(options) < 2:
                raise AlignmentError("MODEL_OUTPUT_OPTIONS_INVALID", "questions require at least two options", path=f"{path}.answer_options")
            option_ids = set()
            for option in options:
                if not isinstance(option, dict) or set(option) != {"option_id", "label", "resulting_status", "proposal"}:
                    raise AlignmentError("MODEL_OUTPUT_OPTIONS_INVALID", "option fields are invalid", path=f"{path}.answer_options")
                if option["option_id"] in option_ids or option["resulting_status"] not in {"confirmed", "unresolved"} or not isinstance(option["proposal"], dict):
                    raise AlignmentError("MODEL_OUTPUT_OPTIONS_INVALID", "option identity, status, or proposal is invalid", path=f"{path}.answer_options")
                option_ids.add(option["option_id"])
                option_candidate = _candidate_as_review(candidate, status="proposed", proposal=option["proposal"])
                option_candidate["candidate_id"] = "cand_" + hashlib.sha256(
                    f"{candidate_id}|{option['option_id']}".encode("utf-8")
                ).hexdigest()[:20]
                option_candidates.append(option_candidate)
        bridge_candidates.append(_candidate_as_review(candidate, status="proposed"))
    candidate_set = {
        "schema_version": "company_bridge_candidates.v1",
        "candidate_set_role": "historical_scan",
        "candidate_set_id": f"candidates_{state['session_id'][8:]}",
        "company_id": state["company_id"],
        "pack_ref": state["pack_ref"],
        "candidates": bridge_candidates,
        "rejections": [],
        "summary": {"candidate_count": len(bridge_candidates), "rejection_count": 0},
    }
    validation = validate_candidate_set(candidate_set, pack=pack, description=description)
    if validation["status"] != "passed":
        error = validation["errors"][0]
        raise AlignmentError("MODEL_PROPOSAL_INVALID", error["message"], path=error["path"])
    if option_candidates:
        option_set = {
            **candidate_set,
            "candidates": option_candidates,
            "summary": {"candidate_count": len(option_candidates), "rejection_count": 0},
        }
        option_validation = validate_candidate_set(option_set, pack=pack, description=description)
        if option_validation["status"] != "passed":
            error = option_validation["errors"][0]
            raise AlignmentError("MODEL_OPTION_PROPOSAL_INVALID", error["message"], path=error["path"])


def _question_id(candidate_id: str) -> str:
    return "question_" + hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:20]


def _build_questions(session_id: str, candidates: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    decided = {item["candidate_id"] for item in decisions}
    questions = []
    for candidate in candidates:
        if candidate["candidate_id"] in decided or candidate.get("question") is None:
            continue
        questions.append({
            "question_id": _question_id(candidate["candidate_id"]),
            "candidate_id": candidate["candidate_id"],
            "prompt": candidate["question"],
            "criticality": candidate["criticality"],
            "why_it_matters": candidate["evidence"][0]["summary"],
            "options": candidate["answer_options"],
            "status": "pending",
        })
    return {"schema_version": "bridge_alignment_questions.v1", "session_id": session_id, "questions": questions}


def _disabled_capabilities(decisions: list[dict[str, Any]]) -> list[str]:
    return sorted({item["capability_id"] for item in decisions if item["resulting_status"] == "unresolved"})


def propose_candidates(*, session_dir: Path, adapter: CandidateAdapter) -> dict[str, Any]:
    paths = _session_paths(session_dir)
    state = _load_json(paths["state"])
    profile = _load_json(paths["profile"])
    description = _load_json(paths["description"])
    pack = load_pack(Path(state["pack_path"]))
    decisions = _load_decisions(paths["decisions"])
    model_input = _model_input(state, profile, pack, decisions)
    _write_json(paths["model_input"], model_input)
    try:
        document = adapter.propose(model_input)
    except Exception as exc:
        raise AlignmentError("ADAPTER_FAILED", str(exc)) from exc
    if not isinstance(document, dict):
        raise AlignmentError("MODEL_OUTPUT_INVALID", "adapter must return a JSON object")
    _validate_model_candidates(document, state=state, pack=pack, description=description)
    questions = _build_questions(state["session_id"], document["candidates"], decisions)
    _write_json(paths["candidates"], document)
    _write_json(paths["questions"], questions)
    pending = questions["questions"]
    _set_state(paths, "awaiting_confirmation" if pending else "ready_to_finalize")
    return {
        "schema_version": "bridge_alignment_result.v1",
        "status": "awaiting_confirmation" if pending else "ready_to_finalize",
        "session_id": state["session_id"],
        "artifacts": _artifacts(paths, ("model_input", "candidates", "questions", "decisions")),
        "pending_questions": pending,
        "disabled_capabilities": _disabled_capabilities(decisions),
        "errors": [],
    }


def _select_option(question: dict[str, Any], answer: str) -> dict[str, Any]:
    normalized = answer.strip().casefold()
    exact = [item for item in question["options"] if normalized in {str(item["option_id"]).casefold(), str(item["label"]).casefold()}]
    if len(exact) == 1:
        return exact[0]
    contained = [item for item in question["options"] if str(item["option_id"]).casefold() in normalized or str(item["label"]).casefold() in normalized]
    if len(contained) == 1:
        return contained[0]
    raise AlignmentError("ANSWER_AMBIGUOUS", "answer must identify exactly one option")


def answer_question(
    *, session_dir: Path, question_id: str, answer: str, confirmed_by: str,
) -> dict[str, Any]:
    if not answer.strip() or not confirmed_by.strip():
        raise AlignmentError("ANSWER_INVALID", "answer and confirmed_by must be non-empty")
    paths = _session_paths(session_dir)
    state = _load_json(paths["state"])
    candidates_document = _load_json(paths["candidates"])
    questions_document = _load_json(paths["questions"])
    decisions = _load_decisions(paths["decisions"])
    if any(item["question_id"] == question_id for item in decisions):
        raise AlignmentError("DECISION_EXISTS", "this question already has a decision")
    question = next((item for item in questions_document["questions"] if item["question_id"] == question_id), None)
    if question is None:
        raise AlignmentError("QUESTION_NOT_FOUND", "pending question does not exist")
    candidate = next(item for item in candidates_document["candidates"] if item["candidate_id"] == question["candidate_id"])
    option = _select_option(question, answer)
    decision = {
        "decision_id": "decision_" + hashlib.sha256(f"{question_id}|{option['option_id']}|{confirmed_by}".encode("utf-8")).hexdigest()[:20],
        "question_id": question_id,
        "candidate_id": candidate["candidate_id"],
        "selected_option_id": option["option_id"],
        "answer_text": answer,
        "resulting_status": option["resulting_status"],
        "proposal": option["proposal"],
        "confirmed_by": confirmed_by,
        "criticality": candidate["criticality"],
        "capability_id": candidate["capability_id"],
        "candidate": candidate,
    }
    paths["decisions"].parent.mkdir(parents=True, exist_ok=True)
    with paths["decisions"].open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(decision, ensure_ascii=False, sort_keys=True) + "\n")
    decisions.append(decision)
    questions = _build_questions(state["session_id"], candidates_document["candidates"], decisions)
    _write_json(paths["questions"], questions)
    _set_state(paths, "awaiting_confirmation" if questions["questions"] else "ready_to_finalize")
    return {
        "schema_version": "bridge_alignment_result.v1",
        "status": "awaiting_confirmation" if questions["questions"] else "ready_to_finalize",
        "session_id": state["session_id"],
        "artifacts": _artifacts(paths, ("decisions", "questions")),
        "pending_questions": questions["questions"],
        "disabled_capabilities": _disabled_capabilities(decisions),
        "errors": [],
    }


def _read_text_excerpt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")[:2000]
    except OSError:
        return ""


def _scan_evidence(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        raise AlignmentError("EVIDENCE_DIRECTORY_NOT_FOUND", "evidence path must be a readable directory")
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in SUPPORTED_EVIDENCE:
            continue
        relative_parts = path.relative_to(root).parts
        if any(part.startswith(".") or part in SKIP_DIRECTORIES for part in relative_parts):
            continue
        digest = sha256_file(path)
        entry: dict[str, Any] = {
            "locator": f"supplement/{path.relative_to(root).as_posix()}",
            "kind": path.suffix.lower().lstrip("."),
            "sha256": digest,
            "size_bytes": path.stat().st_size,
        }
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            try:
                inspection = inspect_workbook(path)
                entry["sheets"] = [{"name": item["name"], "header_candidates": item["header_candidates"]} for item in inspection["sheets"]]
            except XlsxReadError as exc:
                entry["read_error"] = str(exc)
        elif path.suffix.lower() == ".csv":
            try:
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    entry["headers"] = next(csv.reader(handle), [])[:120]
            except (OSError, csv.Error, UnicodeError) as exc:
                entry["read_error"] = str(exc)
        else:
            entry["excerpt"] = _read_text_excerpt(path)
        entries.append(entry)
    return entries


def add_evidence(*, session_dir: Path, evidence_root: Path, adapter: CandidateAdapter) -> dict[str, Any]:
    paths = _session_paths(session_dir)
    state = _load_json(paths["state"])
    profile = _load_json(paths["profile"])
    scanned = _scan_evidence(evidence_root)
    existing_hashes = {item["sha256"] for item in profile.get("supplemental_evidence", [])}
    added = [item for item in scanned if item["sha256"] not in existing_hashes]
    profile["supplemental_evidence"] = profile.get("supplemental_evidence", []) + added
    batch_id = hashlib.sha256(json.dumps(scanned, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:20]
    batch_path = session_dir / "evidence" / f"batch_{batch_id}.json"
    if not batch_path.exists():
        _write_json(batch_path, {"schema_version": "bridge_alignment_evidence_scan.v1", "entries": scanned}, overwrite=False)
    _write_json(paths["profile"], profile)
    result = propose_candidates(session_dir=session_dir, adapter=adapter)
    result["evidence"] = {"scanned_count": len(scanned), "added_count": len(added), "scan_artifact": str(batch_path.resolve())}
    result["session_id"] = state["session_id"]
    return result


def _unresolved_candidate(decision: dict[str, Any]) -> dict[str, Any]:
    original = decision["candidate"]
    proposal = original["proposed_mapping_or_rule"]
    target = original.get("target") or {}
    unresolved = {
        **({"source_id": proposal.get("source_id")} if proposal.get("source_id") else {}),
        **({"relation": proposal.get("relation")} if proposal.get("relation") else {}),
        **({"field_name": proposal.get("field_name")} if proposal.get("field_name") else {}),
        **({"blocked_target_type": target.get("target_type")} if target.get("target_type") else {}),
        **({"blocked_target_id": target.get("target_id")} if target.get("target_id") else {}),
        "reason": decision["answer_text"],
    }
    candidate = dict(original)
    candidate["candidate_type"] = "unresolved"
    return _candidate_as_review(
        candidate,
        status="unresolved",
        proposal=unresolved,
        decision_note=decision["answer_text"],
        decision_by=decision["confirmed_by"],
    )


def _pending_optional_decision(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "answer_text": "非关键候选未获客户确认；本次禁用对应分析能力。",
        "resulting_status": "unresolved",
        "proposal": candidate["proposed_mapping_or_rule"],
        "confirmed_by": "bridge_alignment_wizard",
        "criticality": "optional",
        "capability_id": candidate["capability_id"],
        "candidate": candidate,
        "question_id": _question_id(candidate["candidate_id"]),
        "candidate_id": candidate["candidate_id"],
    }


def finalize_session(
    *, session_dir: Path, bridge_id: str, bridge_version: str,
) -> dict[str, Any]:
    paths = _session_paths(session_dir)
    state = _load_json(paths["state"])
    description = _load_json(paths["description"])
    quality = _load_json(paths["quality"])
    pack = load_pack(Path(state["pack_path"]))
    decisions = _load_decisions(paths["decisions"])
    candidates_document = _load_json(paths["candidates"])
    questions = _build_questions(state["session_id"], candidates_document["candidates"], decisions)
    critical_unresolved = [item for item in decisions if item["criticality"] == "critical" and item["resulting_status"] == "unresolved"]
    pending_critical = [item for item in questions["questions"] if item["criticality"] == "critical"]
    if pending_critical:
        raise AlignmentError(
            "CRITICAL_QUESTIONS_PENDING",
            "critical confirmation questions remain unanswered",
            session_id=state["session_id"],
            pending_questions=pending_critical,
            disabled_capabilities=_disabled_capabilities(decisions),
        )
    if critical_unresolved:
        raise AlignmentError(
            "CRITICAL_AMBIGUITY_UNRESOLVED",
            "critical ambiguity cannot enter a completed Bridge",
            session_id=state["session_id"],
            disabled_capabilities=_disabled_capabilities(decisions),
        )
    decided_ids = {item["candidate_id"] for item in decisions}
    optional_decisions = [
        _pending_optional_decision(candidate)
        for candidate in candidates_document["candidates"]
        if candidate["candidate_id"] not in decided_ids and candidate["criticality"] == "optional"
    ]
    effective_decisions = decisions + optional_decisions
    reviewed_candidates = []
    for decision in effective_decisions:
        if decision["resulting_status"] == "unresolved":
            reviewed_candidates.append(_unresolved_candidate(decision))
        else:
            reviewed_candidates.append(_candidate_as_review(
                decision["candidate"],
                status="confirmed",
                proposal=decision["proposal"],
                decision_note=decision["answer_text"],
                decision_by=decision["confirmed_by"],
            ))
    review = {
        "schema_version": "company_bridge_candidates.v1",
        "candidate_set_role": "confirmed_review",
        "candidate_set_id": f"review_{state['session_id'][8:]}",
        "company_id": state["company_id"],
        "pack_ref": state["pack_ref"],
        "candidates": reviewed_candidates,
        "rejections": [],
        "summary": {"candidate_count": len(reviewed_candidates), "rejection_count": 0},
    }
    validation = validate_candidate_set(review, pack=pack, description=description, require_role="confirmed_review")
    if validation["status"] != "passed":
        error = validation["errors"][0]
        raise AlignmentError("CONFIRMED_REVIEW_INVALID", error["message"], path=error["path"])
    bridge = build_bridge(
        candidates=review,
        pack=pack,
        description=description,
        quality=quality,
        bridge_id=bridge_id,
        bridge_version=bridge_version,
        company_id=state["company_id"],
    )
    bridge_validation = validate_bridge(bridge, pack=pack, description=description, quality=quality)
    if bridge_validation["status"] != "passed":
        raise BridgeError("BRIDGE_VALIDATION_FAILED", "Bridge failed Snapshot compatibility", bridge_validation["errors"])
    final_dir = session_dir / "final"
    review_path = final_dir / "confirmed_review.json"
    bridge_path = final_dir / "company_bridge.v1.json"
    validation_path = final_dir / "validation.json"
    for target in (review_path, bridge_path, validation_path):
        if target.exists():
            raise AlignmentError("OUTPUT_EXISTS", f"final artifact already exists: {target}")
    _write_json(review_path, review, overwrite=False)
    _write_json(bridge_path, bridge, overwrite=False)
    _write_json(validation_path, bridge_validation, overwrite=False)
    _set_state(paths, "completed")
    return {
        "schema_version": "bridge_alignment_result.v1",
        "status": "completed",
        "session_id": state["session_id"],
        "artifacts": {
            "confirmed_review": str(review_path.resolve()),
            "bridge": str(bridge_path.resolve()),
            "validation": str(validation_path.resolve()),
        },
        "pending_questions": questions["questions"],
        "disabled_capabilities": _disabled_capabilities(effective_decisions),
        "errors": [],
    }
