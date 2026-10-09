from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill

from data_acquisition.jobs.study_abroad_legacy import read_legacy_sources


JUNE = "FY27-6月市场绩效（带颜色）.xlsx"
JULY = "27财7月资源&签约-市场版.xlsx"
AUGUST = "27财8月资源&签约（市场版）.xlsx"


def _fill_rgb(value: str) -> PatternFill:
    return PatternFill(fill_type="solid", fgColor=value)


def _fill_theme(theme: int, tint: float) -> PatternFill:
    from openpyxl.styles import Color

    return PatternFill(fill_type="solid", fgColor=Color(theme=theme, tint=tint))


def _june_book(path: Path, *, ambiguous_row: bool = False,
               unknown_tint: bool = False, duplicate_legend: bool = False) -> None:
    book = Workbook()
    crm = book.active
    crm.title = "crm"
    rgb = _fill_rgb("FFFF0000")
    theme = _fill_theme(5, 0.4)
    crm["A1"], crm["B1"] = "合成甲", "合成乙"
    crm["A1"].fill = rgb
    crm["B1"].fill = rgb if duplicate_legend else theme
    headers = ["资源名称", "创建时间", "条线", "意向阶段"]
    crm.append(headers)
    crm.append(["资源记录", datetime(2026, 6, 3), "英国", "本科"])
    crm["A3"].fill = _fill_theme(5, 0.2) if unknown_tint else rgb
    if ambiguous_row:
        crm["B3"].fill = theme

    sheet = book.create_sheet("91")
    sheet["A1"], sheet["B1"] = "合成甲", "合成乙"
    sheet["A1"].fill, sheet["B1"].fill = rgb, theme
    sheet.append(["资源ID", "分配时间", "工单ID", "咨询类型", "工单状态"])
    sheet.append(["R-1", datetime(2026, 6, 4), "W-1", "留学", "正常"])
    sheet["A3"].fill = rgb

    contracts = book.create_sheet("留学签约")
    contracts["A1"], contracts["B1"] = "合成甲", "合成乙"
    contracts["A1"].fill, contracts["B1"].fill = rgb, theme
    contracts.append(["合同编号", "归档日期", "签约金额", "签约客户姓名"])
    contracts.append(["C-1", datetime(2026, 6, 5), 1000, "合成客户"])
    contracts["A3"].fill = rgb

    languages = book.create_sheet("语培签约")
    languages["A1"], languages["B1"] = "合成甲", "合成乙"
    languages["A1"].fill, languages["B1"].fill = rgb, theme
    languages.append(["姓名", "业务类型", "签约金额", "日期"])
    languages.append(["合成学员", "日语", 500, datetime(2026, 6, 7)])
    languages["A3"].fill = rgb

    book.save(path)
    book.close()


def _july_book(path: Path, *, date_conflict: bool = True) -> None:
    book = Workbook()
    crm = book.active
    crm.title = "crm (核算)"
    crm.append(["记录ID", "创建时间", "资源归属人", "大类归属", "条线", "意向阶段"])
    crm.append(["CRM-1", datetime(2026, 7, 2), "合成甲", "线上组", "英国", "本科"])

    sheet = book.create_sheet("91 (核算)")
    sheet.append(["资源ID", "分配时间", "资源归属人", "大类归属", "咨询类型",
                  "工单状态", "工单ID", "客户ID", "市场活动"])
    sheet.append(["R-1", datetime(2026, 7, 3), "合成甲", "线上组", "留学",
                  "正常", "W-1", "U-1", "活动"])

    contracts = book.create_sheet("留学签约 (核算)")
    contracts.append(["记录id", "合同编号", "归档日期", "签约金额", "签约归属",
                      "大类归属", "客户ID", "签约客户姓名"])
    contracts.append(["REC-1", "C-1", datetime(2026, 7, 4), 2000,
                      "合成甲", "线上组", None, "合成客户"])

    languages = book.create_sheet("语培签约 (核算)")
    languages.append(["月份", "日期", "姓名", "业务类型", "签约金额",
                      "大类归属", "签约归属", "日期"])
    languages.append([datetime(2026, 7, 1), 22, "合成学员一", "日语", 300,
                      "线上组", "合成甲", datetime(2026, 7, 22)])
    second_day = 25 if date_conflict else 26
    languages.append([datetime(2026, 7, 1), second_day, "合成学员二", "韩语", 400,
                      "线上组", "合成甲", datetime(2026, 7, 26)])
    book.save(path)
    book.close()


def _august_book(path: Path) -> None:
    book = Workbook()
    resources = book.active
    resources.title = "资源"
    resources.append(["分配时间", "资源ID", "工单ID", "客户ID", "归属大类",
                      "资源归属", "咨询类型（优化后）"])
    resources.append([None, None, None, None, None, None, None])
    resources.append([None, None, "W-1", None, None, None, None])

    contracts = book.create_sheet("留学签约")
    contracts.append(["记录id", "合同编号", "归档日期", "签约归属", "归属大类",
                      "签约金额", "客户ID", "签约客户姓名"])
    contracts.append([None] * 8)
    contracts.append([None, "C-1", datetime(2026, 8, 5), "合成甲", "线上组",
                      900, None, "合成客户"])

    languages = book.create_sheet("语培签约")
    languages.append(["业务日期", "签约归属", "归属大类", "实缴金额", "学员编号",
                      "姓名", "语种", "资源ID", "工单ID"])
    languages.append([None] * 9)
    languages.append([datetime(2026, 8, 7), "合成甲", "线上组", 500, None,
                      "合成学员", "韩语", "R-8", None])
    book.save(path)
    book.close()


class LegacyStudyAbroadReaderTests(unittest.TestCase):
    def test_color_signature_includes_color_type_value_and_tint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / JUNE
            _june_book(path, unknown_tint=True)

            result = read_legacy_sources(path)

            crm = result["resources"][0]
            self.assertIsNone(crm["owner"])
            self.assertIsNone(crm["resource_id"])
            self.assertTrue(crm["technical_record_key"].endswith(":crm:3"))
            self.assertNotEqual(crm["technical_record_key"], crm["resource_id"])
            self.assertEqual(1, result["diagnostics"]["by_sheet"][f"{JUNE}::crm"]
                             ["uncolored_or_unknown_owner_rows"])

    def test_tinted_legend_fill_resolves_and_uncolored_rows_remain_ownerless(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / JUNE
            _june_book(path)
            book = load_workbook(path)
            book["crm"]["A3"].fill = _fill_theme(5, 0.4)
            book["91"]["A3"].fill = PatternFill()
            book.save(path)
            book.close()

            result = read_legacy_sources(path)

            self.assertEqual("合成乙", result["resources"][0]["owner"])
            self.assertIsNone(result["resources"][1]["owner"])
            self.assertEqual("R-1", result["resources"][1]["resource_id"])

    def test_multiple_known_owner_colors_on_one_row_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / JUNE
            _june_book(path, ambiguous_row=True)

            with self.assertRaisesRegex(ValueError, "多个已知归属人颜色"):
                read_legacy_sources(path)

    def test_legend_fill_cannot_map_to_two_owners(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / JUNE
            _june_book(path, duplicate_legend=True)

            with self.assertRaisesRegex(ValueError, "颜色图例填充无法唯一映射"):
                read_legacy_sources(path)

    def test_missing_customer_ids_keep_names_as_identity_basis_without_making_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / JUNE
            _june_book(path)

            result = read_legacy_sources(path)

            contract = result["contracts"][0]
            language = result["languages"][0]
            self.assertIsNone(contract["customer_id"])
            self.assertFalse(contract["customer_identity_available"])
            self.assertEqual("name", contract["customer_identity_basis"])
            self.assertEqual("合成客户", contract["customer_name"])
            self.assertIsNone(language["student_id"])
            self.assertIsNone(language["work_order_id"])
            self.assertFalse(language["customer_identity_available"])
            self.assertEqual("name", language["customer_identity_basis"])
            self.assertTrue(result["historical_import"])

    def test_july_headers_and_two_date_fields_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / JULY
            _july_book(path)

            result = read_legacy_sources(path)

            self.assertEqual("CRM-1", result["resources"][0]["resource_id"])
            self.assertEqual("R-1", result["resources"][1]["resource_id"])
            self.assertEqual(datetime(2026, 7, 22).date(), result["languages"][0]["date"])
            self.assertEqual("日语", result["languages"][0]["language"])
            self.assertEqual("日语", result["languages"][0]["business_type"])
            self.assertIsNone(result["languages"][1]["date"])
            self.assertEqual(1, result["diagnostics"]["by_sheet"][f"{JULY}::语培签约 (核算)"]
                             ["date_pair_conflicts"])
            self.assertIsNone(result["contracts"][0]["customer_id"])
            self.assertEqual("REC-1", result["contracts"][0]["record_id"])

    def test_august_blank_templates_drop_but_incomplete_records_and_lineage_remain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / AUGUST
            _august_book(path)

            result = read_legacy_sources(path)

            self.assertEqual(1, len(result["resources"]))
            self.assertEqual(1, len(result["contracts"]))
            self.assertEqual(1, len(result["languages"]))
            self.assertIsNone(result["resources"][0]["resource_id"])
            self.assertEqual("W-1", result["resources"][0]["work_order_id"])
            self.assertEqual("R-8", result["languages"][0]["resource_id"])
            self.assertIsNone(result["languages"][0]["work_order_id"])
            self.assertEqual("name", result["languages"][0]["customer_identity_basis"])
            self.assertEqual("留学签约", result["contracts"][0]["origin_sheet"])
            self.assertEqual(1, result["diagnostics"]["by_sheet"][f"{AUGUST}::资源"]
                             ["template_rows_excluded"])


if __name__ == "__main__":
    unittest.main()
