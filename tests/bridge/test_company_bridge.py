from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from workspace_modeling.business_pack import load_pack
from workspace_modeling.company_bridge.service import (
    BRIDGE_CATEGORIES,
    BridgeError,
    build_bridge,
    validate_bridge,
    validate_candidate_set,
)
from interfaces.company_bridge import main


def snapshot_inputs() -> tuple[dict[str, object], dict[str, object]]:
    description = {
        "schema_version": "warehouse_description.v1",
        "status": "passed",
        "snapshot_id": "snapshot_bridge_test",
        "relations": [
            {
                "schema": "clean",
                "name": "transactions",
                "type": "BASE TABLE",
                "columns": [
                    {"name": "交易日期", "type": "VARCHAR"},
                    {"name": "金额", "type": "VARCHAR"},
                    {"name": "交易类型", "type": "VARCHAR"},
                    {"name": "渠道", "type": "VARCHAR"},
                    {"name": "校区", "type": "VARCHAR"},
                    {"name": "产品", "type": "VARCHAR"},
                    {"name": "学员", "type": "VARCHAR"},
                    {"name": "付款人", "type": "VARCHAR"},
                ],
            }
        ],
        "errors": [],
    }
    quality = {
        "schema_version": "snapshot_quality_profile.v1",
        "status": "passed",
        "run_id": "run_bridge_quality",
        "snapshot_id": "snapshot_bridge_test",
        "row_count": 0,
        "columns": ["issue_code", "severity"],
        "result": {"columns": ["issue_code", "severity"], "rows": []},
        "artifact": None,
        "errors": [],
    }
    return description, quality


def candidate(
    candidate_id: str,
    candidate_type: str,
    proposal: dict[str, object],
    *,
    status: str = "confirmed",
    source_locator: str = "data_dictionary/transactions.json#transactions",
    evidence_refs: list[str] | None = None,
    decision_note: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "candidate_id": candidate_id,
        "candidate_type": candidate_type,
        "source_locator": source_locator,
        "evidence_summary": "结构化证据指出该字段的企业口径候选。",
        "proposed_mapping_or_rule": proposal,
        "status": status,
        "evidence_refs": evidence_refs or [source_locator],
    }
    if decision_note is not None:
        result["decision_note"] = decision_note
    return result


def candidate_set(*candidates: dict[str, object], role: str = "confirmed_review") -> dict[str, object]:
    pack = load_pack()
    return {
        "schema_version": "company_bridge_candidates.v1",
        "candidate_set_role": role,
        "candidate_set_id": "review_bridge_test",
        "company_id": "company_acme",
        "pack_ref": {"pack_id": pack["pack_id"], "pack_version": pack["pack_version"]},
        "candidates": list(candidates),
        "rejections": [],
        "summary": {"candidate_count": len(candidates), "rejection_count": 0},
    }


def complete_candidates() -> dict[str, object]:
    return candidate_set(
        candidate(
            "cand_source_transactions",
            "source_contract",
            {
                "source_id": "transactions",
                "filename": "transactions.xlsx",
                "sheet_name": "交易明细",
                "relation": "clean.transactions",
                "field_names": ["交易日期", "金额", "交易类型", "校区", "产品", "学员", "付款人"],
                "source_kind": "transaction_ledger",
            },
        ),
        candidate(
            "cand_date_mapping",
            "field_mapping",
            {
                "source_id": "transactions",
                "relation": "clean.transactions",
                "field_name": "交易日期",
                "target_type": "dimension",
                "target_id": "time.cash_transaction_date",
                "mapping_role": "cash_transaction_date",
            },
        ),
        candidate(
            "cand_amount_mapping",
            "field_mapping",
            {
                "source_id": "transactions",
                "relation": "clean.transactions",
                "field_name": "金额",
                "target_type": "concept",
                "target_id": "cash.payment",
                "mapping_role": "cash_amount",
            },
        ),
        candidate(
            "cand_transaction_direction_inflow",
            "enum_mapping",
            {
                "source_id": "transactions",
                "relation": "clean.transactions",
                "field_name": "交易类型",
                "source_value": "收款",
                "target_taxonomy_id": "transaction.direction",
                "target_member_id": "inflow",
            },
        ),
        candidate(
            "cand_amount_normalization",
            "normalization_rule",
            {
                "source_id": "transactions",
                "relation": "clean.transactions",
                "field_name": "金额",
                "operation": "parse_amount",
                "parameters": {"currency": "CNY"},
                "target_type": "concept",
                "target_id": "cash.payment",
            },
        ),
        candidate(
            "cand_net_cash_override",
            "override",
            {
                "target_type": "metric",
                "target_id": "cash.net_cash",
                "key": "refund_amount_sign",
                "value": "positive_outflow",
                "reason": "企业退款源字段按正数表达流出金额。",
            },
        ),
        candidate(
            "cand_payer_unresolved",
            "unresolved",
            {
                "source_id": "transactions",
                "relation": "clean.transactions",
                "field_name": "付款人",
                "blocked_target_type": "concept",
                "blocked_target_id": "customer.payer",
                "reason": "历史字段同时可能表示联系人或实际付款主体，待企业确认。",
            },
            status="unresolved",
            decision_note="确认保留为阻断项，不得当作付款人数口径。",
        ),
    )


class CompanyBridgeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = load_pack()
        self.description, self.quality = snapshot_inputs()

    def test_confirmed_review_builds_only_the_six_formal_categories(self) -> None:
        bridge = build_bridge(
            candidates=complete_candidates(),
            pack=self.pack,
            description=self.description,
            quality=self.quality,
            bridge_id="bridge_company_acme",
            bridge_version="1.0.0",
            company_id="company_acme",
        )

        self.assertEqual("company_bridge.v1", bridge["schema_version"])
        self.assertEqual(set(BRIDGE_CATEGORIES), set(bridge) - {
            "schema_version",
            "bridge_id",
            "bridge_version",
            "company_id",
            "pack_ref",
            "generated_from_candidate_ids",
        })
        self.assertEqual("passed", validate_bridge(bridge, pack=self.pack, description=self.description, quality=self.quality)["status"])
        self.assertNotIn("candidates", bridge)
        self.assertEqual(1, len(bridge["unresolved"]))
        self.assertEqual("unresolved", bridge["unresolved"][0]["status"])

    def test_formal_bridge_can_be_built_without_a_data_snapshot(self) -> None:
        bridge = build_bridge(
            candidates=complete_candidates(),
            pack=self.pack,
            bridge_id="bridge_company_acme",
            bridge_version="1.0.0",
            company_id="company_acme",
        )
        self.assertNotIn("snapshot_ref", bridge)
        self.assertEqual("passed", validate_bridge(bridge, pack=self.pack)["status"])

    def test_ordinal_field_names_are_rejected(self) -> None:
        candidates = complete_candidates()
        candidates["candidates"][1]["proposed_mapping_or_rule"]["field_name"] = "column_6"
        result = validate_candidate_set(candidates, pack=self.pack)
        self.assertEqual("failed", result["status"])
        self.assertIn("ORDINAL_FIELD_FORBIDDEN", {error["code"] for error in result["errors"]})

    def test_formal_entry_requires_a_reviewed_candidate_set(self) -> None:
        proposed = complete_candidates()
        proposed["candidate_set_role"] = "historical_scan"
        with self.assertRaises(BridgeError) as context:
            build_bridge(
                candidates=proposed,
                pack=self.pack,
                description=self.description,
                quality=self.quality,
                bridge_id="bridge_company_acme",
                bridge_version="1.0.0",
                company_id="company_acme",
            )
        self.assertEqual("CANDIDATES_INVALID", context.exception.code)
        self.assertIn("CANDIDATE_SET_ROLE_INVALID", {item["code"] for item in context.exception.errors})

    def test_proposed_rejected_and_unresolved_status_semantics_are_explicit(self) -> None:
        proposed = candidate_set(
            candidate(
                "cand_proposed_date",
                "field_mapping",
                {
                    "source_id": "transactions",
                    "relation": "clean.transactions",
                    "field_name": "交易日期",
                    "target_type": "dimension",
                    "target_id": "time.cash_transaction_date",
                },
                status="proposed",
            ),
            role="confirmed_review",
        )
        result = validate_candidate_set(proposed, pack=self.pack, description=self.description)
        self.assertEqual("failed", result["status"])
        self.assertIn("CANDIDATE_NOT_CONFIRMED", {error["code"] for error in result["errors"]})

        unresolved = candidate_set(
            candidate(
                "cand_unresolved_date",
                "unresolved",
                {"reason": "日期角色未确认。"},
                status="unresolved",
                decision_note="确认阻断。",
            ),
            role="confirmed_review",
        )
        self.assertEqual("passed", validate_candidate_set(unresolved, pack=self.pack, description=self.description)["status"])

        rejected = candidate_set(
            candidate(
                "cand_rejected_date",
                "field_mapping",
                {
                    "source_id": "transactions",
                    "relation": "clean.transactions",
                    "field_name": "交易日期",
                    "target_type": "dimension",
                    "target_id": "time.cash_transaction_date",
                },
                status="rejected",
                decision_note="企业确认该字段是报告日期，不是现金交易日期。",
            ),
            role="historical_scan",
        )
        self.assertEqual("passed", validate_candidate_set(rejected, pack=self.pack, description=self.description)["status"])

        rejected_without_note = copy.deepcopy(rejected)
        rejected_without_note["candidates"][0].pop("decision_note")
        invalid = validate_candidate_set(rejected_without_note, pack=self.pack, description=self.description)
        self.assertIn("DECISION_NOTE_REQUIRED", {error["code"] for error in invalid["errors"]})

    def test_pack_reference_and_dangling_target_are_rejected(self) -> None:
        invalid = complete_candidates()
        invalid["pack_ref"] = {"pack_id": "another_pack", "pack_version": "1.0.0"}
        invalid["candidates"][1]["proposed_mapping_or_rule"]["target_id"] = "concept.missing"
        result = validate_candidate_set(invalid, pack=self.pack, description=self.description)
        codes = {error["code"] for error in result["errors"]}
        self.assertIn("PACK_MISMATCH", codes)
        self.assertIn("REFERENCE_UNKNOWN", codes)

    def test_duplicate_field_mapping_is_rejected_at_build(self) -> None:
        invalid = complete_candidates()
        duplicate = copy.deepcopy(invalid["candidates"][1])
        duplicate["candidate_id"] = "cand_date_mapping_other"
        duplicate["proposed_mapping_or_rule"]["target_id"] = "time.contract_date"
        invalid["candidates"].append(duplicate)
        invalid["summary"]["candidate_count"] += 1
        with self.assertRaises(BridgeError) as context:
            build_bridge(
                candidates=invalid,
                pack=self.pack,
                description=self.description,
                quality=self.quality,
                bridge_id="bridge_company_acme",
                bridge_version="1.0.0",
                company_id="company_acme",
            )
        self.assertIn("MAPPING_CONFLICT", {item["code"] for item in context.exception.errors})

    def test_normalization_mapping_can_disambiguate_same_value_by_source_context(self) -> None:
        candidates = complete_candidates()
        candidates["candidates"].extend(
            [
                candidate(
                    "cand_channel_grouped",
                    "normalization_rule",
                    {
                        "source_id": "transactions",
                        "relation": "clean.transactions",
                        "field_name": "渠道",
                        "operation": "map_enum",
                        "parameters": {
                            "active_passive": "被动",
                            "channel_l1": "集团投放",
                            "source_value": "腾讯广告",
                            "normalized_value": "集团投放",
                        },
                        "target_type": "dimension",
                        "target_id": "acquisition.channel",
                    },
                ),
                candidate(
                    "cand_channel_tmk",
                    "normalization_rule",
                    {
                        "source_id": "transactions",
                        "relation": "clean.transactions",
                        "field_name": "渠道",
                        "operation": "map_enum",
                        "parameters": {
                            "active_passive": "被动",
                            "channel_l1": "TMK激活-平台",
                            "source_value": "腾讯广告",
                            "normalized_value": "TMK",
                        },
                        "target_type": "dimension",
                        "target_id": "acquisition.channel",
                    },
                ),
            ]
        )
        candidates["summary"]["candidate_count"] += 2
        bridge = build_bridge(
            candidates=candidates,
            pack=self.pack,
            description=self.description,
            quality=self.quality,
            bridge_id="bridge_company_acme",
            bridge_version="1.0.0",
            company_id="company_acme",
        )
        self.assertEqual("passed", validate_bridge(bridge, pack=self.pack, description=self.description, quality=self.quality)["status"])

    def test_build_normalizes_candidate_trace_order_after_input_is_shuffled(self) -> None:
        shuffled = complete_candidates()
        shuffled["candidates"] = list(reversed(shuffled["candidates"]))
        bridge = build_bridge(
            candidates=shuffled,
            pack=self.pack,
            description=self.description,
            quality=self.quality,
            bridge_id="bridge_company_acme",
            bridge_version="1.0.0",
            company_id="company_acme",
        )
        self.assertEqual("passed", validate_bridge(bridge, pack=self.pack, description=self.description, quality=self.quality)["status"])
        self.assertEqual(
            [item["candidate_id"] for category in BRIDGE_CATEGORIES for item in bridge[category]],
            bridge["generated_from_candidate_ids"],
        )

    def test_pollution_and_unknown_formal_content_are_rejected(self) -> None:
        polluted = complete_candidates()
        polluted["candidates"][0]["proposed_mapping_or_rule"]["analysis_conclusion"] = "某周退款异常"
        result = validate_candidate_set(polluted, pack=self.pack, description=self.description)
        codes = {error["code"] for error in result["errors"]}
        self.assertIn("POLLUTION_CONTENT", codes)
        self.assertIn("FIELD_UNKNOWN", codes)

        bridge = build_bridge(
            candidates=complete_candidates(),
            pack=self.pack,
            description=self.description,
            quality=self.quality,
            bridge_id="bridge_company_acme",
            bridge_version="1.0.0",
            company_id="company_acme",
        )
        bridge["historical_report"] = {"weekly_anomaly": "退款上升"}
        invalid = validate_bridge(bridge, pack=self.pack, description=self.description, quality=self.quality)
        self.assertIn("FIELD_UNKNOWN", {error["code"] for error in invalid["errors"]})
        self.assertIn("POLLUTION_CONTENT", {error["code"] for error in invalid["errors"]})

    def test_snapshot_compatibility_is_optional_and_bound_when_supplied(self) -> None:
        bridge = build_bridge(
            candidates=complete_candidates(),
            pack=self.pack,
            description=self.description,
            quality=self.quality,
            bridge_id="bridge_company_acme",
            bridge_version="1.0.0",
            company_id="company_acme",
        )
        self.assertNotIn("snapshot_ref", bridge)
        self.assertEqual("passed", validate_bridge(bridge, pack=self.pack)["status"])
        self.assertEqual(
            "snapshot_bridge_test",
            validate_bridge(bridge, pack=self.pack, description=self.description, quality=self.quality)["snapshot_id"],
        )
        bad_quality = copy.deepcopy(self.quality)
        bad_quality["snapshot_id"] = "snapshot_other"
        invalid = validate_bridge(bridge, pack=self.pack, description=self.description, quality=bad_quality)
        self.assertIn("SNAPSHOT_MISMATCH", {error["code"] for error in invalid["errors"]})

    def test_snapshot_description_and_quality_must_be_paired(self) -> None:
        with self.assertRaises(BridgeError) as context:
            build_bridge(
                candidates=complete_candidates(),
                pack=self.pack,
                description=self.description,
                bridge_id="bridge_company_acme",
                bridge_version="1.0.0",
                company_id="company_acme",
            )
        self.assertEqual("SNAPSHOT_INPUT_INVALID", context.exception.code)

    def test_cli_build_and_validate_emit_structured_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidates_path = root / "confirmed_candidates.json"
            pack_path = root / "pack.json"
            description_path = root / "description.json"
            quality_path = root / "run_bridge_quality" / "quality.json"
            quality_path.parent.mkdir()
            bridge_path = root / "bridge.json"
            candidates_path.write_text(json.dumps(complete_candidates(), ensure_ascii=False), encoding="utf-8")
            pack_path.write_text(json.dumps(self.pack, ensure_ascii=False), encoding="utf-8")
            description_path.write_text(json.dumps(self.description, ensure_ascii=False), encoding="utf-8")
            from tests.platform.test_query_service import warehouse
            from data_platform.query.service import execute_query
            db = root / "warehouse.duckdb"
            warehouse(db, "snapshot_bridge_test")
            quality_result = execute_query(warehouse=db, snapshot_id="snapshot_bridge_test", sql="SELECT * FROM quality.issues WHERE false", run_id="run_bridge_quality", output_root=root)
            quality_path = root / quality_result["run_id"] / quality_result["receipt"]["path"]
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "build",
                        "--candidates",
                        str(candidates_path),
                        "--pack",
                        str(pack_path),
                        "--snapshot-description",
                        str(description_path),
                        "--snapshot-quality",
                        str(quality_path),
                        "--bridge-id",
                        "bridge_company_acme",
                        "--bridge-version",
                        "1.0.0",
                        "--company-id",
                        "company_acme",
                        "--output",
                        str(bridge_path),
                    ]
                )
            self.assertEqual(0, exit_code)
            self.assertEqual("passed", json.loads(output.getvalue())["status"])
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "validate",
                        "--bridge",
                        str(bridge_path),
                        "--pack",
                        str(pack_path),
                        "--snapshot-description",
                        str(description_path),
                        "--snapshot-quality",
                        str(quality_path),
                    ]
                )
            self.assertEqual(0, exit_code)
            self.assertEqual("passed", json.loads(output.getvalue())["status"])


if __name__ == "__main__":
    unittest.main()
