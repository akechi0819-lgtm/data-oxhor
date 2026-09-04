from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import duckdb
from openpyxl import Workbook

from interfaces.data_platform import ingest_sources, inspect_sources


def write_schedule(path: Path) -> None:
    workbook = Workbook()
    schedule = workbook.active
    schedule.title = "排课流水"
    schedule.append(["2027 春季排课导出"])
    schedule.append([])
    schedule.append(["课次ID", "老师", "课程名称", "上课日期", "课时", "课时", "上课方式"])
    schedule.append([" S001 ", "教师甲", "雅思阅读", "2027/01/05", " 2 ", "120分钟", " 线下 "])
    schedule.append(["S002", "教师乙", "托福写作", "2027-01-06", "1.5", "90", "直播"])
    schedule.append(["   "])
    notes = workbook.create_sheet("说明")
    notes.append(["本页不是明细表"])
    workbook.create_sheet("空白页")
    workbook.save(path)


def write_priority_matrix(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "教师优先级"
    sheet.append(["项目", "科目", "阶段", "排序", "优先级（由高到低）", "备用教师"])
    sheet.append(["VIP", "雅思", "阅读", "优先级1", "教师甲", "教师乙"])
    sheet.append(["VIP", None, None, "职级", "T2", "T1"])
    sheet.append(["VIP", None, None, "预排课量", 120, 95])
    workbook.save(path)


def manifest_and_bindings(root: Path) -> tuple[Path, list[str]]:
    schedule = root / "跨部门排课导出.xlsx"
    priority = root / "师资矩阵.xlsx"
    write_schedule(schedule)
    write_priority_matrix(priority)
    sources = {
        "scheduling_export": {"filename": schedule.name, "sha256": hashlib.sha256(schedule.read_bytes()).hexdigest()},
        "teacher_rules": {"filename": priority.name, "sha256": hashlib.sha256(priority.read_bytes()).hexdigest()},
    }
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"sources": sources}, ensure_ascii=False), encoding="utf-8")
    return manifest, [f"scheduling_export={schedule}", f"teacher_rules={priority}"]


class ColdStartLandingTests(unittest.TestCase):
    def test_unknown_sources_land_every_sheet_without_a_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, bindings = manifest_and_bindings(root)
            inspected = inspect_sources(run_id="run_cold_start_inspect", manifest_path=manifest, source_values=bindings)
            self.assertEqual(inspected["schema_version"], "data_foundation_inspection.v2")
            schedule = next(source for source in inspected["sources"] if source["source_id"] == "scheduling_export")
            candidates = next(sheet for sheet in schedule["sheets"] if sheet["name"] == "排课流水")["header_candidates"]
            self.assertEqual(candidates[0]["row_number"], 3)

            output = root / "runs"
            result = ingest_sources(
                run_id="run_cold_start_ingest",
                snapshot_id="snapshot_cold_start",
                output_root=output,
                manifest_path=manifest,
                source_values=bindings,
            )
            self.assertEqual(result["schema_version"], "data_foundation_ingest.v2")
            self.assertEqual(result["status"], "passed")
            snapshot = output / "run_cold_start_ingest/data/snapshots/snapshot_cold_start"
            self.assertEqual(len(list((snapshot / "landing").glob("*.parquet"))), 4)
            document = json.loads((snapshot / "snapshot_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(document["schema_version"], "warehouse_snapshot.v2")

            with duckdb.connect(str(snapshot / "warehouse.duckdb"), read_only=True) as connection:
                schemas = {row[0] for row in connection.execute("SELECT schema_name FROM information_schema.schemata").fetchall()}
                self.assertTrue({"ingest", "landing", "quality", "queries"}.issubset(schemas))
                self.assertNotIn("semantic", schemas)
                self.assertNotIn("clean", schemas)
                mappings = dict(connection.execute("SELECT sheet_name, target_table FROM ingest.sheets").fetchall())
                schedule_table = mappings["排课流水"]
                priority_table = mappings["教师优先级"]
                blank_table = mappings["空白页"]
                schedule_rows = connection.execute(
                    f'SELECT source_row_number, "课次ID", "课时", "课时__2" FROM landing."{schedule_table}" ORDER BY source_row_number'
                ).fetchall()
                self.assertEqual(schedule_rows, [(4, " S001 ", " 2 ", "120分钟"), (5, "S002", "1.5", "90"), (6, "   ", None, None)])
                total_hours = connection.execute(
                    f'SELECT sum(TRY_CAST("课时" AS DOUBLE)) FROM landing."{schedule_table}"'
                ).fetchone()[0]
                self.assertEqual(total_hours, 3.5)
                matrix_rows = connection.execute(f'SELECT count(*) FROM landing."{priority_table}"').fetchone()[0]
                self.assertEqual(matrix_rows, 3)
                blank_rows = connection.execute(f'SELECT count(*) FROM landing."{blank_table}"').fetchone()[0]
                self.assertEqual(blank_rows, 0)
                issues = connection.execute("SELECT issue_code, sheet_name FROM quality.issues").fetchall()
                self.assertIn(("SHEET_EMPTY", "空白页"), issues)


if __name__ == "__main__":
    unittest.main()
