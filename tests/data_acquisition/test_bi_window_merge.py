"""Unit checks for BI rolling-window merge (orders ID + cash date window)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb
import openpyxl

from data_acquisition.jobs.bi_window_merge import (
    excel_serial_to_date,
    merge_cash,
    merge_orders,
    rolling_start_date,
)
from data_acquisition.jobs.work_order_cleaning import clean_work_order_rows, load_work_order_reference


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
    def test_outside_kept_and_near_overrides_id(self) -> None:
        start = date(2026, 3, 16)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior = root / "orders.parquet"
            export = root / "orders.xlsx"
            # meta columns should be stripped from output columns via business merge
            _write_parquet(
                prior,
                ["source_id", "snapshot_id", "ID", "分配时间", "姓名"],
                [
                    ["src", "snap", "A", str(_excel_serial(date(2026, 1, 1))), "old-A"],  # outside
                    ["src", "snap", "B", str(_excel_serial(date(2026, 4, 1))), "old-B"],  # inside prior (dropped)
                    ["src", "snap", "C", str(_excel_serial(date(2025, 12, 1))), "old-C"],  # outside
                ],
            )
            _write_xlsx(
                export,
                ["ID", "分配时间", "姓名"],
                [
                    ["B", _excel_serial(date(2026, 4, 2)), "new-B"],
                    ["D", _excel_serial(date(2026, 5, 1)), "new-D"],
                    ["A", _excel_serial(date(2026, 3, 20)), "new-A"],  # same ID as outside → near wins
                ],
                sheet_name="工单明细导出用表",
            )
            sheet, cols, rows, stats = merge_orders(
                export_xlsx=export,
                prior_parquet=prior,
                start=start,
                end=date(2026, 9, 16),
            )
            self.assertEqual(sheet, "工单明细导出用表")
            self.assertNotIn("source_id", cols)
            self.assertNotIn("snapshot_id", cols)
            self.assertGreater(stats["merged_rows"], stats["export_rows"])
            by_id = {str(r["ID"]): r for r in rows}
            self.assertEqual(by_id["A"]["姓名"], "new-A")  # near override
            self.assertEqual(by_id["C"]["姓名"], "old-C")  # outside kept
            self.assertEqual(by_id["B"]["姓名"], "new-B")
            self.assertEqual(by_id["D"]["姓名"], "new-D")
            outside_dates = [
                excel_serial_to_date(r["分配时间"])
                for r in rows
                if excel_serial_to_date(r["分配时间"]) is not None
                and excel_serial_to_date(r["分配时间"]) < start
            ]
            self.assertTrue(outside_dates)
            self.assertEqual(stats["outside_rows"], 2)


class WorkOrderCleaningTests(unittest.TestCase):
    def test_study_abroad_overlay_maps_channels_country_line_and_active_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference_path = root / "reference.xlsx"
            _write_xlsx(
                reference_path,
                [
                    "时间", "一级获取渠道", "二级获取渠道", "三级获取渠道", "数据提供方",
                    "矫正-渠道", "矫正-条线", "矫正-意向国家", "矫正-意向阶段", "矫正-咨询课程",
                ],
                [["1月", "网络资源", "店铺类", "美团点评", "provider", "大众", "欧亚条线", "中国香港", "研究生", ""]],
                sheet_name="Sheet1",
            )
            reference = load_work_order_reference(reference_path)
            rows = [
                {
                    "ID": "WO1", "团队": None, "一级渠道": "前途推荐", "二级渠道": "前途推荐",
                    "主被动": "主动", "资源主被动": "被动", "咨询方式一级渠道": "网络资源-店铺类",
                    "渠道": "美团点评", "意向国家/地区": "中国香港", "资源描述": "",
                },
                {
                    "ID": "WO2", "团队": "高中", "一级渠道": "原一级", "二级渠道": "原二级",
                    "主被动": "主动", "资源主被动": "被动", "咨询方式一级渠道": "网络资源-店铺类",
                    "渠道": "美团点评", "意向国家/地区": "中国香港", "资源描述": "",
                },
            ]
            cleaned, stats = clean_work_order_rows(rows, reference)
            self.assertEqual(cleaned[0]["一级渠道"], "网络资源")
            self.assertEqual(cleaned[0]["二级渠道"], "大众")
            self.assertEqual(cleaned[0]["主被动"], "被动")
            self.assertEqual(cleaned[0]["意向国家"], "中国香港")
            self.assertEqual(cleaned[0]["矫正条线"], "欧亚条线")
            self.assertEqual(cleaned[1]["一级渠道"], "原一级")
            self.assertEqual(cleaned[1]["二级渠道"], "原二级")
            self.assertEqual(stats["target_rows"], 1)
            self.assertEqual(stats["online_target_rows"], 1)
            self.assertEqual(stats["main_active_overrides"], 1)

    def test_offline_study_abroad_rows_are_held_without_cleaning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference_path = root / "reference.xlsx"
            _write_xlsx(
                reference_path,
                [
                    "时间", "一级获取渠道", "二级获取渠道", "三级获取渠道", "数据提供方",
                    "矫正-渠道", "矫正-条线", "矫正-意向国家", "矫正-意向阶段", "矫正-咨询课程",
                ],
                [["1月", "市场活动", "综合展", "小红书", "provider", "小红书", "欧亚条线", "中国香港", "研究生", ""]],
                sheet_name="Sheet1",
            )
            reference = load_work_order_reference(reference_path)
            rows = [{
                "ID": "OFF1", "团队": None, "一级渠道": "前途推荐", "二级渠道": "前途推荐",
                "主被动": "主动", "资源主被动": "被动", "咨询方式一级渠道": "市场活动-综合展",
                "渠道": "小红书", "意向国家/地区": "中国香港", "资源描述": "",
            }]
            cleaned, stats = clean_work_order_rows(rows, reference)
            self.assertEqual(cleaned[0]["一级渠道"], "前途推荐")
            self.assertEqual(cleaned[0]["二级渠道"], "前途推荐")
            self.assertEqual(cleaned[0]["主被动"], "主动")
            self.assertEqual(stats["offline_target_rows"], 1)

    def test_eurasia_online_path_sets_eurasia_line_without_country(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference_path = root / "reference.xlsx"
            _write_xlsx(
                reference_path,
                [
                    "时间", "一级获取渠道", "二级获取渠道", "三级获取渠道", "数据提供方",
                    "矫正-渠道", "矫正-条线", "矫正-意向国家", "矫正-意向阶段", "矫正-咨询课程",
                ],
                [["1月", "新媒体", "欧亚总部在线", "虚拟人", "provider", "个人渠道", "欧亚条线", "日本", "本科", ""]],
                sheet_name="Sheet1",
            )
            reference = load_work_order_reference(reference_path)
            rows = [{
                "ID": "EUR1", "团队": None, "一级渠道": "前途推荐", "二级渠道": "前途推荐",
                "主被动": "主动", "资源主被动": "被动", "咨询方式一级渠道": "新媒体-欧亚总部在线",
                "渠道": "虚拟人", "意向国家/地区": "", "资源描述": "",
            }]
            cleaned, _ = clean_work_order_rows(rows, reference)
            self.assertEqual(cleaned[0]["矫正条线"], "欧亚条线")

    def test_first_country_and_language_fallback_fill_country_and_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference_path = root / "reference.xlsx"
            _write_xlsx(
                reference_path,
                [
                    "时间", "一级获取渠道", "二级获取渠道", "三级获取渠道", "数据提供方",
                    "矫正-渠道", "矫正-条线", "矫正-意向国家", "矫正-意向阶段", "矫正-咨询课程",
                ],
                [
                    ["1月", "网络资源", "店铺类", "美团点评", "provider", "大众", "欧亚条线", "日本", "本科", ""],
                    ["1月", "网络资源", "店铺类", "小红书", "provider", "小红书", "欧亚条线", "法国", "本科", ""],
                ],
                sheet_name="Sheet1",
            )
            reference = load_work_order_reference(reference_path)
            rows = [
                {
                    "ID": "MULTI", "团队": None, "主被动": "主动", "资源主被动": "被动",
                    "咨询方式一级渠道": "网络资源-店铺类", "渠道": "美团点评",
                    "意向国家/地区": "日本,法国", "资源描述": "",
                },
                {
                    "ID": "LANG", "团队": None, "主被动": "主动", "资源主被动": "被动",
                    "咨询方式一级渠道": "网络资源-店铺类", "渠道": "小红书",
                    "意向国家/地区": "", "资源描述": "咨询法语课程",
                },
            ]
            cleaned, _ = clean_work_order_rows(rows, reference, include_audit=True)
            self.assertEqual(cleaned[0]["意向国家"], "日本")
            self.assertEqual(cleaned[0]["意向国家归属方式"], "字段首国")
            self.assertEqual(cleaned[1]["意向国家"], "法国")
            self.assertEqual(cleaned[1]["意向国家归属方式"], "资源描述语种推断")
            self.assertEqual(cleaned[1]["矫正条线"], "欧亚条线")


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
            sheet, cols, rows, stats = merge_cash(
                export_xlsx=export,
                prior_parquet=prior,
                start=start,
                end=date(2026, 9, 16),
            )
            self.assertEqual(sheet, "现金明细表")
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


if __name__ == "__main__":
    unittest.main()
