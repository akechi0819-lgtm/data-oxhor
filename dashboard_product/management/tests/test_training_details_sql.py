from __future__ import annotations

from datetime import date
from pathlib import Path
import unittest

import duckdb


ROOT = Path(__file__).resolve().parents[3]
SQL = ROOT / "dashboard_product/management/sql/training_details.sql"
ORDERS_TABLE = "br_work_orders__sheet_1f0596db9f25"
CASH_TABLE = "br_cash__sheet_39b8dee2e4b3"


def _serial(day):
    return (day - date(1899, 12, 30)).days


class TrainingDetailsQueryTests(unittest.TestCase):
    def test_cash_includes_each_student_type_and_orders_have_no_student_type(self):
        connection = duckdb.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute("CREATE SCHEMA landing")
        order_columns = [
            ("source_row_number", "INTEGER"), ("ID", "VARCHAR"), ("团队", "VARCHAR"),
            ("顾问归属", "VARCHAR"), ("跟进顾问", "VARCHAR"), ("主被动", "VARCHAR"),
            ("分配时间", "DOUBLE"), ("工单状态", "VARCHAR"), ("年级校正", "VARCHAR"),
            ("线上线下", "VARCHAR"), ("二级渠道", "VARCHAR"), ("一级渠道", "VARCHAR"),
            ("活动名称", "VARCHAR"), ("学生学校名称", "VARCHAR"), ("年级名称", "VARCHAR"),
            ("资源描述", "VARCHAR"), ("资源录入人", "VARCHAR"),
        ]
        connection.execute(
            f'CREATE TABLE landing."{ORDERS_TABLE}" (' +
            ", ".join(f'"{name}" {kind}' for name, kind in order_columns) + ")"
        )
        connection.execute(
            f'INSERT INTO landing."{ORDERS_TABLE}" VALUES (' + ", ".join("?" for _ in order_columns) + ")",
            [90, "O1", "高中", "高中顾问", "顾问甲", "主动", _serial(date(2026, 9, 10)),
             None, "高二", "线下", "异业渠道", "市场活动", "活动甲", "校名", "高二", None, None],
        )

        cash_columns = [
            ("source_row_number", "INTEGER"), ("工单ID", "VARCHAR"), ("业务日期", "DOUBLE"),
            ("团队", "VARCHAR"), ("班级编码", "VARCHAR"), ("报名人次", "VARCHAR"),
            ("渠道", "VARCHAR"), ("渠道属性", "VARCHAR"), ("新老生类型", "VARCHAR"),
            ("市场活动名称", "VARCHAR"), ("生源校", "VARCHAR"), ("学员年级", "VARCHAR"),
            ("学员编号", "VARCHAR"), ("报入现金收入", "VARCHAR"),
        ]
        connection.execute(
            f'CREATE TABLE landing."{CASH_TABLE}" (' +
            ", ".join(f'"{name}" {kind}' for name, kind in cash_columns) + ")"
        )
        cash_rows = [
            (1, "O1", date(2026, 9, 10), "高中", "C1", "1", "市场资源", "主动", "新生", "活动甲", None, "高二", "S1", "10.00"),
            (2, None, date(2026, 9, 11), "高中", "C2", "1", "市场资源", "被动", " 老生 ", "活动乙", None, "高二", "S2", "20.00"),
            (3, None, date(2026, 9, 12), "高中", "C3", "1", "市场资源", "被动", "   ", "活动丙", None, "高二", "S3", "30.00"),
            (4, None, date(2026, 9, 13), "高中", "C4", "1", "市场资源", "主动", "未知", "活动丁", None, "高二", "S4", "40.00"),
        ]
        placeholders = ", ".join("?" for _ in cash_columns)
        for row in cash_rows:
            values = list(row)
            values[2] = _serial(values[2])
            connection.execute(
                f'INSERT INTO landing."{CASH_TABLE}" VALUES ({placeholders})', values,
            )

        result = connection.execute(
            SQL.read_text(encoding="utf-8"),
            ["2026-09-01", "2026-10-01", "2026-09-01", [], [], ["主动", "被动"]],
        )
        columns = [item[0] for item in result.description]
        rows = [dict(zip(columns, values)) for values in result.fetchall()]
        types = {row["source_row_number"]: row["student_type"] for row in rows
                 if row["metric"] == "passive_reported_cash"}

        self.assertEqual(types, {1: "新生", 2: "老生", 3: None, 4: "未知"})
        order = next(row for row in rows if row["metric"] == "work_orders")
        self.assertEqual(order["source_row_number"], 90)
        self.assertIsNone(order["student_type"])


if __name__ == "__main__":
    unittest.main()
