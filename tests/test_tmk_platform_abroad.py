"""The TMK platform acquisition channel is online for regular study-abroad facts."""
from __future__ import annotations

from collections import Counter
import unittest

from data_acquisition.jobs.work_order_cleaning import WorkOrderReference
from dashboard_product.management.study_abroad_facts import _make_fact
from tests.data_acquisition.test_study_abroad_facts import _fact_row


SOURCE_SHA256 = "a" * 64
REFERENCE = WorkOrderReference({}, {}, {"日本": "亚洲条线"}, {}, {})
TMK_CHANNEL = ("TMK激活-平台", "平台来源", "matched_existing", "explicit_tmk_platform")


def _make(row, channel=TMK_CHANNEL):
    return _make_fact(row, channel, Counter(), REFERENCE)


class TmkPlatformAbroadTests(unittest.TestCase):
    def test_resource_and_contract_tmk_facts_are_online_and_keep_source_fields(self):
        resource = _fact_row(
            fact_type="resource", fact_id="resources:tmk-100", business_line="study_abroad",
            event_date="2026-07-01", segment_id="study_abroad_offline", resource_id="R-100",
            owner="资源归属甲", source_owner="资源登记甲", first_channel="TMK激活-平台",
            second_channel="原始二级", third_channel="原始三级", source_sha256=SOURCE_SHA256,
        )
        contract = _fact_row(
            fact_type="signature", fact_id="contracts:tmk-200", business_line="study_abroad",
            event_date="2026-07-02", segment_id="study_abroad_online", resource_id="R-200",
            owner="签约归属乙", source_owner="签约登记乙", first_channel="TMK激活-平台",
            second_channel="原始签约二级", third_channel="原始签约三级",
            source_sha256=SOURCE_SHA256, contract_id="C-200", customer_key="study_abroad:U-200",
            gross_signing_amount="125.50", gross_amount="125.50", positive_signature=True,
        )

        resource_fact = _make(resource)
        contract_fact = _make(contract)

        self.assertEqual(resource_fact["segment_id"], "study_abroad_online")
        self.assertEqual(resource_fact["team_id"], "online_platform")
        self.assertEqual(resource_fact["acquisition_mode"], "online")
        self.assertFalse(resource_fact["offline_channel_eligible"])
        self.assertEqual(resource_fact["metric"], "orders")
        self.assertEqual(resource_fact["value"], 1)
        self.assertEqual(resource_fact["fact_id"], "abroad-source:resources:tmk-100")
        self.assertEqual(resource_fact["resource_id"], "R-100")
        self.assertEqual(resource_fact["owner"], "资源归属甲")
        self.assertEqual(resource_fact["source_owner"], "资源登记甲")
        self.assertEqual(resource_fact["owners"], ["资源归属甲"])
        self.assertEqual(resource_fact["business_group"], "大学")
        self.assertEqual(resource_fact["first_channel"], "TMK激活-平台")
        self.assertEqual(resource_fact["second_channel"], "平台来源")
        self.assertEqual(resource_fact["raw_first_channel"], "TMK激活-平台")
        self.assertEqual(resource_fact["raw_second_channel"], "原始二级")

        self.assertEqual(contract_fact["segment_id"], "study_abroad_online")
        self.assertEqual(contract_fact["team_id"], "online_platform")
        self.assertEqual(contract_fact["acquisition_mode"], "online")
        self.assertFalse(contract_fact["offline_channel_eligible"])
        self.assertEqual(contract_fact["metric"], "cash")
        self.assertEqual(contract_fact["value"], 125.5)
        self.assertEqual(contract_fact["fact_id"], "abroad-source:contracts:tmk-200")
        self.assertEqual(contract_fact["resource_id"], "R-200")
        self.assertEqual(contract_fact["contract_id"], "C-200")
        self.assertEqual(contract_fact["customer_key"], "study_abroad:U-200")
        self.assertEqual(contract_fact["student_id"], "study_abroad:U-200")
        self.assertEqual(contract_fact["owner"], "签约归属乙")
        self.assertEqual(contract_fact["source_owner"], "签约登记乙")
        self.assertEqual(contract_fact["owners"], ["签约归属乙"])
        self.assertEqual(contract_fact["first_channel"], "TMK激活-平台")
        self.assertEqual(contract_fact["raw_first_channel"], "TMK激活-平台")

    def test_other_channels_keep_existing_online_and_offline_assignments(self):
        expected = {
            "study_abroad_offline": ("offline_market", "offline", True),
            "study_abroad_online": ("online_platform", "online", False),
        }
        for segment, (team, mode, offline_eligible) in expected.items():
            with self.subTest(segment=segment):
                row = _fact_row(
                    fact_type="resource", fact_id=f"resources:other-{segment}",
                    business_line="study_abroad", event_date="2026-07-03", segment_id=segment,
                    resource_id="R-300", owner="渠道归属丙", first_channel="市场活动",
                    second_channel="高校活动", source_sha256=SOURCE_SHA256,
                )
                fact = _make(row, ("市场活动", "高校活动", "matched_existing", "existing_rule"))

                self.assertEqual(fact["segment_id"], segment)
                self.assertEqual(fact["team_id"], team)
                self.assertEqual(fact["acquisition_mode"], mode)
                self.assertEqual(fact["offline_channel_eligible"], offline_eligible)
                self.assertEqual(fact["first_channel"], "市场活动")

    def test_tmk_channel_does_not_pull_supplemental_segments_into_market(self):
        for segment in ("ssc", "international_market", "unassigned"):
            with self.subTest(segment=segment):
                row = _fact_row(
                    fact_type="resource", fact_id=f"resources:tmk-{segment}",
                    business_line="study_abroad", event_date="2026-07-04", segment_id=segment,
                    resource_id=f"R-{segment}", owner="待归属丁", first_channel="TMK激活-平台",
                    second_channel="原始二级", source_sha256=SOURCE_SHA256,
                )
                fact = _make(row)

                self.assertEqual(fact["segment_id"], segment)
                self.assertIsNone(fact["team_id"])
                self.assertEqual(fact["acquisition_mode"], "supplemental")
                self.assertFalse(fact["offline_channel_eligible"])
                self.assertEqual(fact["first_channel"], "TMK激活-平台")
                if segment == "international_market":
                    self.assertEqual(fact["owners"], [])


if __name__ == "__main__":
    unittest.main()
