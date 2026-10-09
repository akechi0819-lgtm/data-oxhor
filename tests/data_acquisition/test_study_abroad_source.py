"""Synthetic workbook checks for the shared study-abroad source reader."""
from __future__ import annotations

import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import openpyxl

from workspace_modeling.operations.study_abroad_source import read_sheet_rows, read_sources


RESOURCE_HEADERS = [
    "分单日期\n（跟系统一致）", "资源ID\n（跟系统一致）",
    "市场资源归属人\n需要市场老师判定", "市场资源归属组\n（公式勿动）",
    "线下组资源\n是否退回", "市场活动", "一级渠道\n（跟系统一致）",
    "二级渠道\n（跟系统一致）", "三级渠道\n（跟系统一致）",
    "渠道来源\n需要人为判定\n(下拉选项)", "咨询类型\n(下拉选项)",
    "意向国家\n(下拉选项)", "意向阶段\n(下拉选项)",
    "归属条线\n(下拉选项)", "看板归类\n（公式勿动）", "资源描述",
]
CONTRACT_HEADERS = [
    "记录id", "合同编号", "归档月份", "归档日期",
    "市场资源归属人\n需要市场老师判定", "市场资源归属组\n（公式勿动）",
    "签约金额", "91资源市场活动", "客户ID", "留学国家", "申请学位",
    "来访类型", "来源渠道", "渠道明细", "合同状态", "备注",
]
LANGUAGE_HEADERS = [
    "资源ID", "工单ID", "业务日期", "市场资源归属人\n需要市场老师判定",
    "市场资源归属组\n（公式勿动）", "实缴金额", "学员编号", "语种", "班级编码",
    "业务类型", "新签/续签", "来访类型\n（一级渠道）",
    "渠道来源\n（二级渠道）", "渠道明细\n（三级渠道）",
]

REQUIRED_HEADERS = {
    "资源": (
        "资源ID\n（跟系统一致）", "分单日期\n（跟系统一致）",
        "市场资源归属人\n需要市场老师判定",
    ),
    "留学签约": (
        "记录id", "合同编号", "归档月份", "归档日期",
        "市场资源归属人\n需要市场老师判定", "签约金额",
    ),
    "小语种签约": (
        "工单ID", "业务日期", "市场资源归属人\n需要市场老师判定", "实缴金额",
    ),
}


def _default_records() -> dict[str, list[dict[str, object]]]:
    return {
        "资源": [{
            "分单日期\n（跟系统一致）": date(2026, 6, 3),
            "资源ID\n（跟系统一致）": "R-001",
            "市场资源归属人\n需要市场老师判定": "网络SSC",
            "市场资源归属组\n（公式勿动）": "线上团队",
            "线下组资源\n是否退回": "否", "市场活动": "样本活动",
            "一级渠道\n（跟系统一致）": "线上", "资源描述": "资源描述",
        }],
        "留学签约": [{
            "记录id": "R-001", "合同编号": "C-001", "客户ID": "U-001",
            "归档月份": "2026-06", "归档日期": date(2026, 6, 20),
            "市场资源归属人\n需要市场老师判定": "网络SSC",
            "市场资源归属组\n（公式勿动）": "线上团队", "签约金额": 12000,
            "91资源市场活动": "样本活动", "备注": "有效合同",
        }],
        "小语种签约": [{
            "资源ID": "R-001", "工单ID": "W-001", "业务日期": date(2026, 6, 21),
            "市场资源归属人\n需要市场老师判定": "网络SSC",
            "市场资源归属组\n（公式勿动）": "线上团队", "实缴金额": 800,
            "学员编号": "S-001", "语种": "日语",
        }],
    }


def _append_records(sheet, headers: list[str], records: list[dict[str, object]] | list[list[object]]) -> None:
    for record in records:
        if isinstance(record, dict):
            sheet.append([record.get(header) for header in headers])
        else:
            sheet.append(record)


def _write_workbook(
    path: Path,
    *,
    headers: dict[str, list[str]] | None = None,
    records: dict[str, list[dict[str, object]] | list[list[object]]] | None = None,
    missing_sheets: set[str] | None = None,
    with_mapping: bool = True,
) -> None:
    headers = headers or {
        "资源": RESOURCE_HEADERS,
        "留学签约": CONTRACT_HEADERS,
        "小语种签约": LANGUAGE_HEADERS,
    }
    defaults = _default_records()
    records = records or defaults
    missing_sheets = missing_sheets or set()

    workbook = openpyxl.Workbook()
    resource_sheet = workbook.active
    resource_sheet.title = "资源"
    for name in ("留学签约", "小语种签约"):
        workbook.create_sheet(name)

    for name in ("资源", "留学签约", "小语种签约"):
        if name in missing_sheets:
            workbook.remove(workbook[name])
            continue
        sheet = workbook[name]
        sheet.append(headers[name])
        _append_records(sheet, headers[name], records.get(name, defaults[name]))

    if with_mapping:
        mapping = workbook.create_sheet("筛选项")
        mapping.sheet_state = "hidden"
        mapping.auto_filter.ref = "A1:B3"
        # The first row is data; these columns have no heading row.
        mapping.append(["网络SSC", "线上团队"])
        mapping.append(["公式归属人", '=IF(TRUE,"缓存团队","")'])
        mapping.append(["国际市场", "国际市场"])

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()


def _rewrite_sheet_dimension(path: Path, sheet_xml_path: str, dimension: str) -> None:
    with ZipFile(path, "r") as source:
        entries = [(item, source.read(item.filename)) for item in source.infolist()]
    rewritten = []
    for item, contents in entries:
        if item.filename == sheet_xml_path:
            contents, count = re.subn(
                rb'(<dimension\b[^>]*\bref=")[^"]+("[^>]*/>)',
                lambda match: match.group(1) + dimension.encode("ascii") + match.group(2),
                contents,
                count=1,
            )
            if count != 1:
                raise AssertionError(f"No worksheet dimension found in {sheet_xml_path}")
        rewritten.append((item, contents))
    with ZipFile(path, "w") as target:
        for item, contents in rewritten:
            target.writestr(item, contents)


class StudyAbroadReaderTests(unittest.TestCase):
    def test_reads_xml_rows_outside_declared_dimensions_and_keeps_excel_row_number(self) -> None:
        for declared_dimension in ("A1:A1", "A1:Z200"):
            with self.subTest(dimension=declared_dimension), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "study-abroad.xlsx"
                _write_workbook(path, records={
                    "资源": [{"资源描述": "   "}, *_default_records()["资源"]],
                    "留学签约": _default_records()["留学签约"],
                    "小语种签约": _default_records()["小语种签约"],
                })
                _rewrite_sheet_dimension(path, "xl/worksheets/sheet1.xml", declared_dimension)

                result = read_sources(path)

                self.assertEqual([3], [row["source_row_number"] for row in result["resources"]])
                self.assertEqual("R-001", result["resources"][0]["resource_id"])

    def test_ignores_contract_footer_and_rows_without_contract_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "study-abroad.xlsx"
            valid = _default_records()["留学签约"][0]
            without_contract_number = {
                "记录id": "R-002", "合同编号": "", "归档月份": "2026-06",
                "归档日期": date(2026, 6, 22),
                "市场资源归属人\n需要市场老师判定": "线上组",
                "签约金额": 5000, "91资源市场活动": "活动B", "备注": "没有合同编号",
            }
            footer = {"备注": "说明：以下空白用于填写补充信息"}
            _write_workbook(path, records={
                "资源": _default_records()["资源"],
                "留学签约": [valid, without_contract_number, footer],
                "小语种签约": _default_records()["小语种签约"],
            })

            rows = read_sources(path)["contracts"]

            self.assertEqual(1, len(rows))
            self.assertEqual("C-001", rows[0]["contract_id"])

    def test_returns_hidden_filter_rows_separately_and_preserves_source_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "study-abroad.xlsx"
            resource = dict(_default_records()["资源"][0])
            resource["市场资源归属组\n（公式勿动）"] = "#N/A"
            _write_workbook(path, records={
                "资源": [resource],
                "留学签约": _default_records()["留学签约"],
                "小语种签约": _default_records()["小语种签约"],
            })

            result = read_sources(path)

            self.assertEqual("网络SSC", result["group_mapping"][0]["owner"])
            self.assertEqual("线上团队", result["group_mapping"][0]["source_group"])
            self.assertEqual(1, result["group_mapping"][0]["source_row_number"])
            self.assertEqual("国际市场", result["group_mapping"][2]["owner"])
            self.assertEqual("#N/A", result["resources"][0]["source_group"])

    def test_duplicate_resource_id_uses_leftmost_column_in_both_reader_apis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "study-abroad.xlsx"
            resource_headers = RESOURCE_HEADERS + ["资源ID"]
            row = [
                date(2026, 6, 3), "LEFT-ID", "网络SSC", "线上团队", "否", "样本活动",
                None, None, None, None, None, None, None, None, None, None, "RIGHT-ID",
            ]
            _write_workbook(path, headers={
                "资源": resource_headers,
                "留学签约": CONTRACT_HEADERS,
                "小语种签约": LANGUAGE_HEADERS,
            }, records={
                "资源": [row],
                "留学签约": _default_records()["留学签约"],
                "小语种签约": _default_records()["小语种签约"],
            })

            self.assertEqual("LEFT-ID", read_sources(path)["resources"][0]["resource_id"])
            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
            try:
                rows = read_sheet_rows(workbook, "资源", {"resource_id": "资源ID"})
            finally:
                workbook.close()
            self.assertEqual("LEFT-ID", rows[0]["resource_id"])

    def test_optional_columns_can_be_missing_and_return_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "study-abroad.xlsx"
            resource_headers = [header for header in RESOURCE_HEADERS if header != "资源描述"]
            _write_workbook(path, headers={
                "资源": resource_headers,
                "留学签约": CONTRACT_HEADERS,
                "小语种签约": LANGUAGE_HEADERS,
            }, with_mapping=False)

            result = read_sources(path)

            self.assertEqual([], result["group_mapping"])
            self.assertIsNone(result["resources"][0]["description"])
            self.assertEqual("U-001", result["contracts"][0]["customer_id"])
            self.assertEqual("S-001", result["languages"][0]["student_id"])

    def test_each_required_sheet_must_exist(self) -> None:
        for missing_sheet in ("资源", "留学签约", "小语种签约"):
            with self.subTest(sheet=missing_sheet), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "study-abroad.xlsx"
                _write_workbook(path, missing_sheets={missing_sheet})
                with self.assertRaisesRegex(ValueError, missing_sheet):
                    read_sources(path)

    def test_missing_critical_headers_fail_for_all_three_sheets(self) -> None:
        default_headers = {
            "资源": RESOURCE_HEADERS,
            "留学签约": CONTRACT_HEADERS,
            "小语种签约": LANGUAGE_HEADERS,
        }
        for sheet_name, required_headers in REQUIRED_HEADERS.items():
            for missing_header in required_headers:
                with self.subTest(sheet=sheet_name, header=missing_header), tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "study-abroad.xlsx"
                    headers = {name: list(items) for name, items in default_headers.items()}
                    headers[sheet_name].remove(missing_header)
                    _write_workbook(path, headers=headers)
                    expected_error = (f"{sheet_name}前10行未找到关键字段表头"
                                      if sheet_name == "资源"
                                      else f"{sheet_name} 缺少关键字段")
                    with self.assertRaisesRegex(ValueError, expected_error):
                        read_sources(path)

    def test_source_hash_is_checked_before_and_after_reading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "study-abroad.xlsx"
            _write_workbook(path)
            result = read_sources(path)
            self.assertEqual(64, len(result["source_sha256"]))
            self.assertEqual(str(path), result["source_path"])

            with patch("workspace_modeling.operations.study_abroad_source._sha256",
                       side_effect=["before", "after"]):
                with self.assertRaisesRegex(ValueError, "读取过程中发生变化"):
                    read_sources(path)


if __name__ == "__main__":
    unittest.main()
