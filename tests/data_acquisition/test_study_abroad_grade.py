"""Grade-based channel resolution uses only explicit BI Snapshot evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard_product.management.study_abroad_grade import (
    load_grade_evidence,
    resolve_grade_rows,
    stage_from_values,
)


def _grade_row(resource_id, work_order_id, **values):
    return {
        "resource_id": resource_id,
        "alternate_resource_id": None,
        "work_order_id": work_order_id,
        "grade_attr": None,
        "corrected_grade": None,
        "current_grade": None,
        "grade_name": None,
        **values,
    }


def _bi_workspace(root: Path, *, company_id="company_grade_test") -> tuple[Path, Path, bytes]:
    snapshot_id = "snapshot_grade_test_20261008"
    warehouse = root / "Work/Runs/run_grade_test/data/snapshots" / snapshot_id / "warehouse.duckdb"
    warehouse.parent.mkdir(parents=True)
    warehouse.touch()
    header_columns = [
        {"technical_name": "资源id", "original_name": "资源id"},
        {"technical_name": "资源-资源ID", "original_name": "资源-资源ID"},
        {"technical_name": "ID", "original_name": "ID"},
        {"technical_name": "年级属性", "original_name": "年级属性"},
        {"technical_name": "年级校正", "original_name": "年级校正"},
        {"technical_name": "目前年级", "original_name": "目前年级"},
        {"technical_name": "年级名称", "original_name": "年级名称"},
    ]
    manifest = {
        "schema_version": "warehouse_snapshot.v2",
        "snapshot_id": snapshot_id,
        "sources": [
            {
                "source_id": "br_cash",
                "sheets": [{"name": "cash", "target_table": "br_cash__sheet_fixture", "header_columns": []}],
            },
            {
                "source_id": "br_work_orders",
                "sheets": [{
                    "name": "orders",
                    "target_table": "br_work_orders__sheet_grade_fixture",
                    "header_columns": header_columns,
                }],
            },
        ],
        "artifacts": [{"path": "warehouse.duckdb", "sha256": "0" * 64, "size_bytes": 0}],
    }
    manifest_path = warehouse.parent / "snapshot_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    workspace_config_path = root / "Work/workspace.json"
    workspace_config_path.parent.mkdir(parents=True, exist_ok=True)
    workspace_config_path.write_text(json.dumps({
        "company_id": company_id,
        "current_snapshot_id": snapshot_id,
        "current_warehouse_path": warehouse.relative_to(root).as_posix(),
    }), encoding="utf-8")
    return workspace_config_path, warehouse, manifest_path.read_bytes()


class GradeStageTests(unittest.TestCase):
    def test_recognizes_college_and_middle_school_values(self):
        self.assertEqual("college", stage_from_values("大学"))
        self.assertEqual("college", stage_from_values("本科"))
        self.assertEqual("college", stage_from_values("大专"))
        self.assertEqual("college", stage_from_values("研究生及以上"))
        self.assertEqual("college", stage_from_values("大一"))
        self.assertEqual("middle", stage_from_values("初中"))
        self.assertEqual("middle", stage_from_values("高中"))
        self.assertEqual("middle", stage_from_values("10年级（高一）"))
        self.assertEqual("middle", stage_from_values("7年级（初一）"))

    def test_unknown_and_lower_school_values_do_not_map(self):
        for value in ("小学", "青少", "大学以下", "未知", "未确认", None):
            with self.subTest(value=value):
                self.assertIsNone(stage_from_values(value))

    def test_conflicting_fields_do_not_choose_a_stage(self):
        self.assertIsNone(stage_from_values("本科", "高中"))


class GradeResolutionTests(unittest.TestCase):
    def test_maps_each_requested_resource_and_ignores_unknown_values(self):
        rows = [
            _grade_row("100", "wo-college", grade_attr="本科"),
            _grade_row(None, "wo-middle", alternate_resource_id="200.0", corrected_grade="10年级（高一）"),
            _grade_row("300", "wo-primary", grade_name="小学六年级"),
            _grade_row("400", "wo-unknown", grade_attr="未确认"),
        ]

        result = resolve_grade_rows(rows, ["100", "200", "300", "400", "500"])

        self.assertEqual({
            "100": {"second_channel": "高校活动", "status": "resolved", "work_order_ids": ["wo-college"]},
            "200": {"second_channel": "中学活动", "status": "resolved", "work_order_ids": ["wo-middle"]},
            "300": {"second_channel": None, "status": "grade_missing", "work_order_ids": ["wo-primary"]},
            "400": {"second_channel": None, "status": "grade_missing", "work_order_ids": ["wo-unknown"]},
            "500": {"second_channel": None, "status": "grade_missing", "work_order_ids": []},
        }, result)

    def test_conflict_across_fields_and_work_orders_is_not_guessed(self):
        rows = [
            _grade_row("100", "wo-1", grade_attr="大学"),
            _grade_row(None, "wo-2", alternate_resource_id="100.0", corrected_grade="高一"),
            _grade_row("200", "wo-3", grade_attr="大学", grade_name="高中"),
        ]

        result = resolve_grade_rows(rows, ["100", "200"])

        self.assertEqual({
            "100": {"second_channel": None, "status": "grade_conflict", "work_order_ids": ["wo-1", "wo-2"]},
            "200": {"second_channel": None, "status": "grade_conflict", "work_order_ids": ["wo-3"]},
        }, result)

    def test_rejects_invalid_or_empty_resource_id_requests(self):
        with self.assertRaises(ValueError):
            resolve_grade_rows([], [])
        with self.assertRaises(ValueError):
            resolve_grade_rows([], ["resource-abc"])


class LoadGradeEvidenceTests(unittest.TestCase):
    def test_queries_only_the_explicit_bi_snapshot_and_preserves_pointer_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            config_path, warehouse, manifest_bytes = _bi_workspace(workspace)
            original_config = config_path.read_bytes()
            result_rows = [
                [12, "100", "100.0", "wo-1", "大学", "本科", "大一", "大一", None, None, None, None, None],
                [13, "200", None, "wo-2", "高中", "10年级（高一）", "高一", "高一", None, None, None, None, None],
            ]
            result_data = {
                "columns": [
                    "source_row_number", "resource_id", "alternate_resource_id", "work_order_id",
                    "grade_attr", "corrected_grade", "current_grade", "grade_name",
                    "assignment_date", "activity_name", "student_school", "current_school", "intended_school",
                ],
                "rows": result_rows,
            }
            response = {
                "schema_version": "controlled_query_result.v2",
                "status": "passed",
                "run_id": "run_grade_test_001",
                "snapshot_id": "snapshot_grade_test_20261008",
                "receipt": {"evidence_id": "evidence_grade_test"},
            }
            receipt = {
                "run_id": response["run_id"],
                "snapshot_id": response["snapshot_id"],
                "referenced_source_ids": ["br_work_orders"],
                "referenced_relations": ["landing.br_work_orders__sheet_grade_fixture"],
                "snapshot_ref": {
                    "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                    "warehouse_sha256": "0" * 64,
                },
            }
            with (
                patch("dashboard_product.management.study_abroad_grade.execute_query", return_value=response) as query,
                patch("dashboard_product.management.study_abroad_grade.read_query_result", return_value=result_data) as read_result,
                patch("dashboard_product.management.study_abroad_grade.resolve_file", return_value=workspace / "receipt.json"),
                patch("dashboard_product.management.study_abroad_grade.verify_receipt", return_value=(receipt, result_data)),
            ):
                evidence = load_grade_evidence(
                    workspace=workspace,
                    resource_ids=["100", "200"],
                    run_id="run_grade_test_001",
                    expected_company_id="company_grade_test",
                )

            kwargs = query.call_args.kwargs
            self.assertEqual(warehouse.resolve(), kwargs["warehouse"])
            self.assertEqual("snapshot_grade_test_20261008", kwargs["snapshot_id"])
            self.assertEqual("run_grade_test_001", kwargs["run_id"])
            self.assertEqual((workspace / "Output/StudyAbroad").resolve(), kwargs["output_root"])
            self.assertIn('FROM landing."br_work_orders__sheet_grade_fixture"', kwargs["sql"])
            self.assertIn('"资源id"', kwargs["sql"])
            self.assertIn('"资源-资源ID"', kwargs["sql"])
            self.assertNotIn("活动名称", kwargs["sql"])
            self.assertNotIn("学生学校名称", kwargs["sql"])
            self.assertNotIn("姓名", kwargs["sql"])
            self.assertNotIn("电话号码", kwargs["sql"])
            self.assertIn("100", kwargs["parameters"])
            self.assertIn("200", kwargs["parameters"])
            self.assertNotIn("999", kwargs["parameters"])
            read_result.assert_called_once_with(response, output_root=(workspace / "Output/StudyAbroad").resolve())
            self.assertEqual(original_config, config_path.read_bytes())
            self.assertEqual(hashlib.sha256(original_config).hexdigest(), evidence["bi_workspace_sha256"])
            self.assertEqual("snapshot_grade_test_20261008", evidence["bi_snapshot_id"])
            self.assertEqual("高校活动", evidence["resolution"]["100"]["second_channel"])
            self.assertEqual("中学活动", evidence["resolution"]["200"]["second_channel"])

    def test_company_mismatch_stops_before_query(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            config_path, _, _ = _bi_workspace(workspace)
            original_config = config_path.read_bytes()
            with patch("dashboard_product.management.study_abroad_grade.execute_query") as query:
                with self.assertRaisesRegex(ValueError, "company_id"):
                    load_grade_evidence(
                        workspace=workspace,
                        resource_ids=["100"],
                        run_id="run_grade_test_002",
                        expected_company_id="other_company",
                    )
            query.assert_not_called()
            self.assertEqual(original_config, config_path.read_bytes())

    def test_response_snapshot_must_match_explicit_current_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            config_path, _, _ = _bi_workspace(workspace)
            original_config = config_path.read_bytes()
            response = {
                "schema_version": "controlled_query_result.v2",
                "status": "passed",
                "run_id": "run_grade_test_003",
                "snapshot_id": "snapshot_other",
                "receipt": {"evidence_id": "evidence_grade_test"},
            }
            with patch("dashboard_product.management.study_abroad_grade.execute_query", return_value=response):
                with self.assertRaisesRegex(ValueError, "Snapshot或run身份"):
                    load_grade_evidence(
                        workspace=workspace,
                        resource_ids=["100"],
                        run_id="run_grade_test_003",
                        expected_company_id="company_grade_test",
                    )
            self.assertEqual(original_config, config_path.read_bytes())

    def test_detects_workspace_pointer_change_during_controlled_query(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            config_path, _, _ = _bi_workspace(workspace)
            response = {
                "schema_version": "controlled_query_result.v2",
                "status": "passed",
                "run_id": "run_grade_test_004",
                "snapshot_id": "snapshot_grade_test_20261008",
                "receipt": {"evidence_id": "evidence_grade_test"},
            }

            def move_pointer(**_kwargs):
                updated = json.loads(config_path.read_bytes())
                updated["current_snapshot_id"] = "snapshot_other"
                config_path.write_text(json.dumps(updated), encoding="utf-8")
                return response

            with patch("dashboard_product.management.study_abroad_grade.execute_query", side_effect=move_pointer):
                with self.assertRaisesRegex(ValueError, "workspace指针字节发生变化"):
                    load_grade_evidence(
                        workspace=workspace,
                        resource_ids=["100"],
                        run_id="run_grade_test_004",
                        expected_company_id="company_grade_test",
                    )


if __name__ == "__main__":
    unittest.main()
