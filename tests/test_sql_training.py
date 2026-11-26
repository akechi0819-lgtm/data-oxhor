from __future__ import annotations

import copy
import json
import unittest

import duckdb

from tests.legacy_dashboard.training_facts import normalize_facts
from dashboard_product.management.school_attributes import attach_school_attributes
from dashboard_product.shadow_bi.sql_warehouse.training import install_training


PEOPLE = {
    "teams": [
        {"team_id": "offline_market", "groups": [{"members": [
            {"display_name": "王昊", "status": "active"},
        ]}]},
        {"team_id": "online_private", "groups": [{"members": [
            {"display_name": "虚拟甲", "status": "active"},
            {"display_name": "虚拟乙", "status": "active"},
            {"display_name": "离职虚拟", "status": "departed"},
        ]}]},
    ]
}
ABROAD_PEOPLE = {"people": [{"display_name": "孙伟", "business_group": "大学"}]}
MAPPING = {"留学顾问": "留学", "预备顾问": "留学预备"}


def training_row(work_order_id, row_number, *, metric="work_orders", group="高中",
                 team_id="offline_market", campaign="普通活动", mode="被动", **extra):
    row = {
        "work_order_id": work_order_id,
        "source_row_number": row_number,
        "event_date": "2026-09-10",
        "team_id": team_id,
        "business_group": group,
        "first_channel": "市场活动",
        "second_channel": "大学媒体投放",
        "campaign_name": campaign,
        "work_order_campaign_name": campaign,
        "entry_person": None,
        "school_name": "天津大学津南校区",
        "grade_name": "高二",
        "metric": metric,
        "actual_value": 1 if metric == "work_orders" else "125.50",
        "student_id": None,
        "student_type": None,
        "cash_channel": "市场资源" if metric == "passive_reported_cash" else None,
        "work_order_active_type": "被动",
        "cash_campaign_name": None,
        "order_status": None,
        "source_record": None,
        "cash_source_record": None,
        "acquisition_mode": mode,
        "class_code": "C-1",
        "registration_count": 1,
    }
    row.update(extra)
    return row


def order_row(work_order_id, *, source_team="高中", adviser=None, first="市场活动",
              second="大学媒体投放", source="腾讯广告", campaign="王昊活动",
              status=None, description="市场人员：王昊 虚拟甲"):
    return {
        "work_order_id": work_order_id,
        "source_team": source_team,
        "adviser": adviser,
        "follow_adviser": None,
        "first_channel": first,
        "second_channel": second,
        "source_channel": source,
        "campaign_name": campaign,
        "resource_entry_person": "王昊",
        "resource_description": description,
        "order_status": status,
        "source_record": json.dumps({"ID": work_order_id, "工单状态": status}, ensure_ascii=False),
    }


def rows_as_dicts(con, view):
    cursor = con.execute(f"SELECT * FROM business.{view} ORDER BY fact_id")
    names = [column[0] for column in cursor.description]
    output = []
    for values in cursor.fetchall():
        row = dict(zip(names, values))
        if isinstance(row.get("source_record"), str):
            row["source_record"] = json.loads(row["source_record"])
        if row.get("team_before_override") is None:
            row.pop("team_before_override")
        if row.get("team_override_reason") is None:
            row.pop("team_override_reason")
        output.append(row)
    return output


def _comparable(row):
    copied = dict(row)
    copied["value"] = float(copied["value"])
    return copied


def _copy_student_types(expected, source_rows):
    source_types = {}
    for source in source_rows:
        if source.get("metric") == "work_orders":
            fact_id = f"training:order:{source.get('work_order_id')}"
            student_type = None
        elif source.get("source_row_number") not in (None, ""):
            fact_id = f"training:cash:{source['source_row_number']}"
            student_type = str(source.get("student_type") or "").strip() or None
        else:
            continue
        source_types[fact_id] = student_type
    for fact in expected:
        fact["student_type"] = source_types.get(fact["fact_id"])


class SqlTrainingTests(unittest.TestCase):
    def setUp(self):
        self.training_rows = [
            training_row("O1", 10, group="青少", campaign="普通活动", order_status="删除",
                         student_type="新生",
                         source_record='{"ID":"O1","工单状态":"删除"}'),
            training_row("O2", 11, group="大学"),
            training_row("O3", 12, group="初中"),
            training_row("O4", 13, group="高中"),
            training_row("unmatched", 14, group="大学"),
            training_row("unknown-line", 15, group="其他"),
            training_row(None, 16, metric="passive_reported_cash", group="大学",
                         actual_value="25.555", cash_campaign_name="市场活动", campaign_name="否",
                         student_type=" 老生 ",
                         cash_source_record='{"渠道":"市场资源"}'),
            training_row("O1", 20, metric="passive_reported_cash", group="高中",
                         actual_value="125.50", cash_campaign_name="SCRM", campaign_name="O1 cash",
                         student_type="新生",
                         source_record=None, cash_source_record='{"工单ID":"O1"}'),
            training_row("O5", 21, metric="work_orders", group="高中", mode="主动"),
            training_row("O6", 22, metric="passive_reported_cash", group="高中",
                         team_id="offline_market", first_channel="TMK激活-平台", second_channel="小红书",
                         cash_channel="TMK", cash_campaign_name="SCRM", actual_value="200.00"),
            training_row(None, 18, metric="passive_reported_cash", group="大学",
                         actual_value="-50.00", student_type=""),
            training_row("O7", None, metric="passive_reported_cash", group="大学",
                         actual_value="300.00"),
        ]
        self.order_rows = [
            order_row("O1", status="删除", campaign="王昊活动（虚拟甲）"),
            order_row("O2", source_team="留学", adviser="留学顾问"),
            order_row("O3", source_team="", adviser="预备顾问", campaign="王昊预备活动"),
            order_row("O4", source_team="", adviser="未知顾问"),
            order_row("O5", source_team="高中", first="市场活动", second="线下校代", source="市场活动"),
            order_row("O6", first="市场活动", second="大学媒体投放", source="新东方PC官网"),
        ]
        self.cash_overrides = {"overrides": [{
            "work_order_id": "O1", "event_date": "2026-09-10", "amount": "125.50",
            "team_id": "online_private", "note": "确认现金团队",
        }]}
        self.school_rows = [
            {"source_row_number": row_number, "school_name": "天津大学津南校区", "school_attribute": "国外大学"}
            for row_number in (16, 18, 20, 22)
        ]
        self.con = duckdb.connect(":memory:")
        install_training(self.con, self.training_rows, self.order_rows, PEOPLE, ABROAD_PEOPLE,
                         MAPPING, self.cash_overrides, self.school_rows)

    def tearDown(self):
        self.con.close()

    def test_sql_training_view_matches_normalize_facts_fixture(self):
        expected_rows = copy.deepcopy(self.training_rows)
        attach_school_attributes(expected_rows, self.school_rows)
        expected, _ = normalize_facts(
            expected_rows, self.order_rows, PEOPLE, ABROAD_PEOPLE,
            MAPPING, cash_team_overrides=self.cash_overrides,
        )
        _copy_student_types(expected, expected_rows)
        actual = rows_as_dicts(self.con, "training_facts")
        self.assertEqual([_comparable(row) for row in actual], [_comparable(row) for row in sorted(expected, key=lambda row: row["fact_id"])])
        facts = {row["fact_id"]: row for row in actual}
        self.assertEqual(facts["training:cash:20"]["team_id"], "online_platform")
        self.assertEqual(facts["training:cash:20"]["team_before_override"], "online_private")
        self.assertEqual(facts["training:cash:20"]["team_override_reason"], "经核实直接线上投放（市场活动→大学媒体投放，原渠道：腾讯广告）")
        self.assertEqual(float(facts["training:cash:16"]["value"]), 25.56)
        self.assertEqual(facts["training:cash:16"]["student_type"], "老生")
        self.assertEqual(facts["training:cash:20"]["student_type"], "新生")
        self.assertIsNone(facts["training:cash:18"]["student_type"])
        self.assertIsNone(facts["training:order:O1"]["student_type"])
        self.assertEqual(facts["training:cash:20"]["virtual_owners"], ["虚拟甲"])
        self.assertNotIn("training:order:O2", facts)
        self.assertNotIn("training:order:unknown-line", facts)
        self.assertNotIn("training:cash:7", facts)

    def test_personnel_view_filters_to_passive_and_keeps_legacy_cash_rows_and_prep_exception(self):
        selected = [row for row in self.training_rows
                    if row.get("acquisition_mode") in (None, "被动")]
        expected_rows = copy.deepcopy(selected)
        attach_school_attributes(expected_rows, self.school_rows)
        expected, _ = normalize_facts(
            expected_rows, self.order_rows, PEOPLE, ABROAD_PEOPLE,
            MAPPING, cash_team_overrides=self.cash_overrides, personal_qualification=True,
        )
        _copy_student_types(expected, expected_rows)
        actual = rows_as_dicts(self.con, "training_personnel_facts")
        self.assertEqual([_comparable(row) for row in actual], [_comparable(row) for row in sorted(expected, key=lambda row: row["fact_id"])])
        facts = {row["fact_id"]: row for row in actual}
        self.assertIn("training:order:O3", facts)
        self.assertNotIn("training:order:O4", facts)
        self.assertNotIn("training:order:O5", facts)
        self.assertIn("training:cash:16", facts)
        self.assertIn("training:cash:18", facts)
        self.assertEqual(facts["training:cash:16"]["student_type"], "老生")
        self.assertIsNone(facts["training:cash:18"]["student_type"])

    def test_school_attribute_mapping_is_available_as_sql(self):
        con = duckdb.connect(":memory:")
        try:
            install_training(con, [training_row("school", 31)], [order_row("school")],
                             PEOPLE, ABROAD_PEOPLE, {}, school_rows=[
                                 {"source_row_number": 31, "school_name": "天津大学津南校区", "school_attribute": "国外大学"},
                             ])
            fact = rows_as_dicts(con, "training_facts")[0]
            self.assertEqual(fact["channel_school_name"], "天津大学")
            self.assertEqual(fact["school_attribute"], "大学*")
            self.assertEqual(fact["school_attribute_status"], "重点大学名单")
            self.assertEqual(con.execute("SELECT typeof(value) FROM business.training_facts").fetchone()[0], "DECIMAL(24,2)")
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
