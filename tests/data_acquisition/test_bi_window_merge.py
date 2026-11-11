"""Unit checks for BI rolling-window merge (orders ID + cash date window)."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb
import openpyxl

from data_acquisition.jobs.bi_window_merge import (
    excel_serial_to_date,
    find_landing_parquet,
    merge_cash,
    merge_exports_with_prior,
    merge_orders,
    rolling_start_date,
    resolve_prior_landing_dir,
)
from workspace_modeling.bridge_alignment.workspace import init_workspace, sync_data


def _excel_serial(d: date) -> float:
    return float((d - date(1899, 12, 30)).days)


def _write_xlsx(path: Path, headers: list[str], rows: list[list], sheet_name: str = "Sheet1") -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)
    wb.close()


def _read_xlsx_records(path: Path) -> list[dict[str, object]]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        iterator = ws.iter_rows(values_only=True)
        headers = next(iterator)
        return [dict(zip(headers, row)) for row in iterator]
    finally:
        wb.close()


def _write_parquet(path: Path, headers: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    cols_sql = ", ".join(f'"{h}" VARCHAR' for h in headers)
    con.execute(f"CREATE TABLE t ({cols_sql})")
    for row in rows:
        placeholders = ", ".join("?" for _ in row)
        con.execute(f"INSERT INTO t VALUES ({placeholders})", [None if v is None else str(v) for v in row])
    con.execute(f"COPY t TO '{path.as_posix()}' (FORMAT PARQUET)")
    con.close()


class RollingStartTests(unittest.TestCase):
    def test_six_calendar_months(self) -> None:
        self.assertEqual(rolling_start_date(date(2026, 9, 16)), "2026-03-16")
        self.assertEqual(rolling_start_date(date(2026, 3, 31)), "2025-09-30")


class ExcelSerialTests(unittest.TestCase):
    def test_known_serial(self) -> None:
        self.assertEqual(excel_serial_to_date(45809.0), date(2025, 6, 1))
        self.assertEqual(excel_serial_to_date("45809.0"), date(2025, 6, 1))


class MergeOrdersTests(unittest.TestCase):
    def test_duplicate_order_keeps_first_source_row_across_period_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior, export = root / "prior.parquet", root / "fresh.xlsx"
            headers = ["ID", "分配时间", "主被动"]
            _write_parquet(prior, headers, [
                ["history", "2025-06-01", "被动"],
                ["history", "2025-05-31", "被动"],
                ["updated", "2025-06-01", "被动"],
            ])
            _write_xlsx(export, headers, [
                ["updated", "2026-06-01", "主动"],
                ["updated", "2026-05-31", "被动"],
            ])
            _, _, rows, _ = merge_orders(
                export_xlsx=export, prior_parquet=prior, start=date(2026, 4, 24))
            by_id = {row["ID"]: row for row in rows}
            self.assertEqual(len(rows), 2)
            self.assertEqual(by_id["history"]["分配时间"], "2025-06-01")
            self.assertEqual(by_id["updated"]["分配时间"], "2026-06-01")
            self.assertEqual(by_id["updated"]["主被动"], "主动")

    def test_outside_kept_and_near_overrides_id(self) -> None:
        start = date(2026, 3, 16)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior = root / "orders.parquet"
            export = root / "orders.xlsx"
            export_headers = ["资源录入人", "团队", "ID", "分配时间", "姓名"]
            _write_parquet(
                prior,
                ["source_id", "snapshot_id", "ID", "分配时间", "姓名", "资源录入人", "录入来源", "预计到访时间"],
                [
                    ["src", "snap", "A", str(_excel_serial(date(2026, 1, 1))), "old-A", "entry-old-A", "legacy-A", "2026-01-02"],  # outside
                    ["src", "snap", "B", str(_excel_serial(date(2026, 4, 1))), "old-B", "entry-old-B", "legacy-B", "2026-04-02"],  # inside prior (dropped)
                    ["src", "snap", "C", str(_excel_serial(date(2025, 12, 1))), "old-C", "entry-old-C", "legacy-C", "2025-12-02"],  # outside
                ],
            )
            _write_xlsx(
                export,
                export_headers,
                [
                    ["entry-new-B", "new-team-B", "B", _excel_serial(date(2026, 4, 2)), "new-B"],
                    ["entry-new-D", "new-team-D", "D", _excel_serial(date(2026, 5, 1)), "new-D"],
                    ["entry-new-A", "new-team-A", "A", _excel_serial(date(2026, 3, 20)), "new-A"],  # same ID as outside → near wins
                ],
                sheet_name="工单明细导出用表",
            )
            sheet, cols, rows, stats = merge_orders(export_xlsx=export, prior_parquet=prior, start=start)
            self.assertEqual(sheet, "工单明细导出用表")
            self.assertEqual(cols, export_headers)
            self.assertNotIn("source_id", cols)
            self.assertNotIn("snapshot_id", cols)
            self.assertNotIn("录入来源", cols)
            self.assertNotIn("预计到访时间", cols)
            self.assertTrue(all(set(row) == set(export_headers) for row in rows))
            self.assertGreater(stats["merged_rows"], stats["export_rows"])
            by_id = {str(r["ID"]): r for r in rows}
            self.assertEqual(by_id["A"]["姓名"], "new-A")  # near override
            self.assertEqual(by_id["A"]["资源录入人"], "entry-new-A")
            self.assertEqual(by_id["C"]["姓名"], "old-C")  # outside kept
            self.assertEqual(by_id["C"]["资源录入人"], "entry-old-C")
            self.assertEqual(by_id["B"]["姓名"], "new-B")
            self.assertEqual(by_id["B"]["资源录入人"], "entry-new-B")
            self.assertEqual(by_id["D"]["姓名"], "new-D")
            outside_dates = [
                excel_serial_to_date(r["分配时间"])
                for r in rows
                if excel_serial_to_date(r["分配时间"]) is not None
                and excel_serial_to_date(r["分配时间"]) < start
            ]
            self.assertTrue(outside_dates)
            self.assertEqual(stats["outside_rows"], 2)

    def test_full_history_window_uses_export_schema_and_replaces_prior_rows(self) -> None:
        start = date(2025, 3, 1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior = root / "orders.parquet"
            export = root / "orders.xlsx"
            export_headers = ["团队", "资源录入人", "ID", "分配时间", "活动名称"]
            _write_parquet(
                prior,
                ["source_id", "snapshot_id", "ID", "分配时间", "团队", "录入来源"],
                [
                    ["src", "snap", "old-1", str(_excel_serial(date(2026, 5, 1))), "旧团队", "legacy-1"],
                    ["src", "snap", "same-id", str(_excel_serial(date(2026, 8, 1))), "旧团队", "legacy-2"],
                ],
            )
            _write_xlsx(
                export,
                export_headers,
                [
                    ["新团队", "新录入人", "same-id", _excel_serial(date(2026, 8, 2)), "新活动"],
                    ["新团队", "新录入人2", "new-id", _excel_serial(date(2025, 3, 1)), "新活动2"],
                ],
                sheet_name="工单明细导出用表",
            )

            _, columns, rows, stats = merge_orders(
                export_xlsx=export, prior_parquet=prior, start=start,
            )

            self.assertEqual(columns, export_headers)
            self.assertEqual(stats["outside_rows"], 0)
            self.assertEqual(stats["merged_rows"], stats["export_rows"])
            self.assertEqual({row["ID"] for row in rows}, {"same-id", "new-id"})
            updated = next(row for row in rows if row["ID"] == "same-id")
            self.assertEqual(updated["团队"], "新团队")
            self.assertEqual(updated["活动名称"], "新活动")
            self.assertTrue(all("录入来源" not in row for row in rows))

    def test_closed_window_rejects_unparseable_or_out_of_range_fresh_dates(self) -> None:
        for invalid_date in ("不是日期", "2026-11-03", "2026-11-05", None):
            with self.subTest(invalid_date=invalid_date), tempfile.TemporaryDirectory() as tmp:
                export = Path(tmp) / "orders.xlsx"
                _write_xlsx(export, ["ID", "分配时间"], [["A", invalid_date]])
                with self.assertRaisesRegex(ValueError, "fresh order export row 1"):
                    merge_orders(
                        export_xlsx=export,
                        prior_parquet=None,
                        start=date(2026, 11, 4),
                        end=date(2026, 11, 4),
                    )


class MergeCashTests(unittest.TestCase):
    def test_window_replace_keeps_duplicate_outside(self) -> None:
        start = date(2026, 3, 16)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior = root / "cash.parquet"
            export = root / "cash.xlsx"
            # Soft key note: 工单ID+业务日期+学员编号+现金收入+业务类型 (not unique)
            dup = ["WO1", str(_excel_serial(date(2026, 1, 10))), "S1", "100", "报名"]
            _write_parquet(
                prior,
                ["source_row_number", "工单ID", "业务日期", "学员编号", "现金收入", "业务类型"],
                [
                    ["1", *dup],
                    ["2", *dup],  # duplicate outside rows
                    ["3", "WO2", str(_excel_serial(date(2026, 4, 1))), "S2", "200", "报名"],  # inside prior
                ],
            )
            _write_xlsx(
                export,
                ["工单ID", "业务日期", "学员编号", "现金收入", "业务类型"],
                [
                    ["WO2", _excel_serial(date(2026, 4, 2)), "S2", "250", "报名"],
                    ["WO3", _excel_serial(date(2026, 5, 1)), "S3", "300", "报名"],
                ],
                sheet_name="现金明细表",
            )
            sheet, cols, rows, stats = merge_cash(export_xlsx=export, prior_parquet=prior, start=start)
            self.assertEqual(sheet, "现金明细表")
            self.assertEqual(cols, ["工单ID", "业务日期", "学员编号", "现金收入", "业务类型"])
            self.assertNotIn("source_row_number", cols)
            self.assertGreater(stats["merged_rows"], stats["export_rows"])
            self.assertEqual(stats["outside_rows"], 2)
            self.assertEqual(stats["merged_rows"], 4)  # 2 outside dup + 2 near
            # prior inside window row must not remain
            cash_vals = [str(r.get("现金收入")) for r in rows]
            self.assertNotIn("200", cash_vals)
            self.assertIn("250", cash_vals)
            dates = [excel_serial_to_date(r["业务日期"]) for r in rows]
            self.assertTrue(any(d is not None and d < start for d in dates))

    def test_missing_explicit_prior_parquet_is_an_error_for_both_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing.parquet"
            orders = root / "orders.xlsx"
            cash = root / "cash.xlsx"
            _write_xlsx(orders, ["ID", "分配时间"], [["A", "2026-01-01"]])
            _write_xlsx(cash, ["工单ID", "业务日期"], [["A", "2026-01-01"]])
            with self.assertRaises(duckdb.IOException):
                merge_orders(export_xlsx=orders, prior_parquet=missing, start=date(2026, 3, 1))
            with self.assertRaises(duckdb.IOException):
                merge_cash(export_xlsx=cash, prior_parquet=missing, start=date(2026, 3, 1))


class PriorSnapshotLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = Path("workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json").resolve()

    def _workspace(
        self,
        root: Path,
        *,
        orders_rows: list[list] | None = None,
        cash_rows: list[list] | None = None,
    ) -> Path:
        init_workspace(
            root=root,
            company_id="company_bi_lookup",
            business_port="operations",
            pack_path=self.pack,
        )
        for source_id, name, sheet, headers, rows in (
            (
                "br_work_orders", "orders.xlsx", "工单明细导出用表",
                ["ID", "分配时间", "姓名"],
                orders_rows if orders_rows is not None else [["A", "2026-01-01", "100"]],
            ),
            (
                "br_cash", "cash.xlsx", "现金明细表",
                ["工单ID", "业务日期", "现金收入"],
                cash_rows if cash_rows is not None else [["A", "2026-01-01", "100"]],
            ),
        ):
            slot = root / "Input" / "Data" / source_id
            slot.mkdir(parents=True)
            _write_xlsx(slot / name, headers, rows, sheet_name=sheet)
        sync_data(root=root, snapshot_id="snapshot_bi_lookup_01")
        return root

    def test_daily_order_window_keeps_old_orders_and_cash_uses_six_month_start(self) -> None:
        cash_start = rolling_start_date(date(2026, 11, 5))
        self.assertEqual(cash_start, "2026-05-05")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self._workspace(
                root / "workspace",
                orders_rows=[
                    ["before", "2026-11-03", "old-before"],
                    ["same-id", "2026-11-04", "old-same"],
                    ["after", "2026-11-05", "old-after"],
                ],
                cash_rows=[
                    ["cash-outside", "2026-05-04", "40"],
                    ["cash-inside", "2026-05-05", "50"],
                ],
            )
            orders_export = root / "fresh-orders.xlsx"
            cash_export = root / "fresh-cash.xlsx"
            _write_xlsx(
                orders_export,
                ["ID", "分配时间", "姓名"],
                [
                    ["same-id", "2026-11-04", "fresh-same"],
                    ["new-id", "2026-11-04", "fresh-new"],
                ],
                sheet_name="工单明细导出用表",
            )
            _write_xlsx(
                cash_export,
                ["工单ID", "业务日期", "现金收入"],
                [["cash-fresh", "2026-11-04", "60"]],
                sheet_name="现金明细表",
            )

            result = merge_exports_with_prior(
                workspace=workspace,
                orders_xlsx=orders_export,
                cash_xlsx=cash_export,
                start_date=cash_start,
                orders_start_date="2026-11-04",
                orders_end_date="2026-11-04",
                output_dir=root / "merged",
            )

            orders = _read_xlsx_records(result["orders_path"])
            orders_by_id = {row["ID"]: row for row in orders}
            self.assertEqual(set(orders_by_id), {"before", "same-id", "after", "new-id"})
            self.assertEqual(orders_by_id["same-id"]["姓名"], "fresh-same")
            self.assertEqual(orders_by_id["before"]["姓名"], "old-before")
            self.assertEqual(orders_by_id["after"]["姓名"], "old-after")
            self.assertEqual(orders_by_id["new-id"]["姓名"], "fresh-new")

            cash = _read_xlsx_records(result["cash_path"])
            self.assertEqual({row["工单ID"] for row in cash}, {"cash-outside", "cash-fresh"})
            self.assertEqual(result["start_date"], cash_start)

    def test_max_assignment_date_uses_merged_rows_after_window_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self._workspace(
                root / "workspace",
                orders_rows=[
                    ["same-id", "2026-11-04", "old-max-in-window"],
                    ["outside", "2026-11-01", "old-outside"],
                ],
                cash_rows=[["cash", "2026-11-04", "10"]],
            )
            orders_export = root / "fresh-orders.xlsx"
            cash_export = root / "fresh-cash.xlsx"
            _write_xlsx(
                orders_export,
                ["ID", "分配时间", "姓名"],
                [["same-id", "2026-11-03", "fresh-earlier"]],
                sheet_name="工单明细导出用表",
            )
            _write_xlsx(
                cash_export,
                ["工单ID", "业务日期", "现金收入"],
                [["cash-fresh", "2026-11-03", "20"]],
                sheet_name="现金明细表",
            )

            result = merge_exports_with_prior(
                workspace=workspace,
                orders_xlsx=orders_export,
                cash_xlsx=cash_export,
                start_date="2026-05-05",
                orders_start_date="2026-11-03",
                orders_end_date="2026-11-04",
                output_dir=root / "merged",
            )

            self.assertEqual(result["orders_max_assignment_date"], "2026-11-03")

    def test_max_assignment_date_is_none_when_merged_orders_have_no_valid_dates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self._workspace(
                root / "workspace",
                orders_rows=[["prior-undated", "not-a-date", "old"]],
                cash_rows=[["cash", "2026-11-03", "10"]],
            )
            orders_export = root / "fresh-orders.xlsx"
            cash_export = root / "fresh-cash.xlsx"
            _write_xlsx(
                orders_export,
                ["ID", "分配时间", "姓名"],
                [["fresh-undated", None, "fresh"]],
                sheet_name="工单明细导出用表",
            )
            _write_xlsx(
                cash_export,
                ["工单ID", "业务日期", "现金收入"],
                [["cash-fresh", "2026-11-03", "20"]],
                sheet_name="现金明细表",
            )

            result = merge_exports_with_prior(
                workspace=workspace,
                orders_xlsx=orders_export,
                cash_xlsx=cash_export,
                start_date="2026-05-05",
                output_dir=root / "merged",
            )

            self.assertIsNone(result["orders_max_assignment_date"])

    def test_current_snapshot_uses_declared_artifact_and_reports_missing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace(Path(directory) / "workspace")
            landing = resolve_prior_landing_dir(workspace)
            self.assertIsNotNone(landing)
            manifest_path = landing.parent / "snapshot_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            orders_table = next(
                sheet["target_table"]
                for source in manifest["sources"]
                if source["source_id"] == "br_work_orders"
                for sheet in source["sheets"]
            )
            expected = landing / f"{orders_table}.parquet"
            (landing / "br_work_orders__not_declared.parquet").write_bytes(b"decoy")
            self.assertEqual(expected, find_landing_parquet(landing, "br_work_orders"))

            cash_source = next(source for source in manifest["sources"] if source["source_id"] == "br_cash")
            manifest["sources"].remove(cash_source)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "br_cash source"):
                find_landing_parquet(landing, "br_cash")

    def test_current_snapshot_with_missing_manifest_or_landing_is_not_first_import(self) -> None:
        for missing in ("manifest", "landing"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                workspace = self._workspace(Path(directory) / "workspace")
                landing = resolve_prior_landing_dir(workspace)
                if missing == "manifest":
                    (landing.parent / "snapshot_manifest.json").unlink()
                    message = "manifest is missing"
                else:
                    import shutil
                    shutil.rmtree(landing)
                    message = "landing directory is missing"
                with self.assertRaisesRegex(RuntimeError, message):
                    resolve_prior_landing_dir(workspace)


if __name__ == "__main__":
    unittest.main()
