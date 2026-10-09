from __future__ import annotations

import unittest

from dashboard_product.management.capacity_radar import RADAR_DIMS, build_radar


def configs(*, full_abroad_target=True):
    people = {
        "teams": [
            {"team_id": "offline_market", "groups": [{"display_name": "高中组", "members": [
                {"display_name": name, "status": "active"}
                for name in ("语培甲", "语培乙", "静默成员")
            ]}]},
            {"team_id": "online_private", "groups": [{"display_name": "虚拟组", "members": [
                {"display_name": "虚拟甲", "status": "active"},
                {"display_name": "离职虚拟", "status": "departed"},
            ]}]},
        ]
    }
    monthly = {}
    if full_abroad_target:
        monthly = {
            f"2026-{month:02d}": {"cash": 10000} for month in range(6, 13)
        } | {
            f"2027-{month:02d}": {"cash": 10000} for month in range(1, 6)
        }
    abroad_people = {
        "team_id": "study_abroad_offline",
        "people": [
            {"display_name": "留学甲", "business_group": "大学", "status": "active",
             "monthly_targets": monthly},
            {"display_name": "留学乙", "business_group": "高中", "status": "active",
             "monthly_targets": {"2026-10": {"cash": 80000}}},
        ],
    }
    capacity = {
        "schema_version": "dashboard_capacity_targets.v1",
        "fiscal_year": "FY27",
        "annual_cash_by_person": 800000,
    }
    return people, abroad_people, capacity


def fact(fact_id, line, metric, value, owners, *, day="2026-06-10",
         domain=None, virtual_owners=None, student_id=None, first=None, second=None,
         segment=None, eligible=True):
    return {
        "fact_id": fact_id,
        "business_line": line,
        "metric": metric,
        "value": value,
        "event_date": day,
        "owners": owners,
        "virtual_owners": virtual_owners or [],
        "student_id": student_id,
        "customer_domain": domain,
        "first_channel": first,
        "second_channel": second,
        "segment_id": segment,
        "personal_eligible": eligible,
        "counts_toward_completion": True,
    }


class CapacityRadarTests(unittest.TestCase):
    def test_primary_business_sources_weights_targets_and_peer_groups(self):
        people, abroad_people, capacity = configs()
        facts = [
            fact("to1", "training", "orders", 4, ["语培甲", "语培乙"],
                 virtual_owners=["虚拟甲"]),
            fact("tc1", "training", "cash", 100, ["语培甲", "语培乙"],
                 virtual_owners=["虚拟甲"], student_id="T1",
                 first="市场活动", second="线下校代"),
            fact("abroad-resource", "abroad", "orders", 1, ["留学甲"],
                 domain="study_abroad", segment="study_abroad_offline"),
            fact("language-resource", "abroad", "orders", 1, ["留学甲"],
                 domain="small_language", segment="study_abroad_offline"),
            fact("abroad-signature", "abroad", "cash", 200, ["留学甲"],
                 domain="study_abroad", student_id="S1", first="渠道合作",
                 second="线下校代", segment="study_abroad_offline"),
            fact("language-cash", "abroad", "cash", 300, ["留学甲"],
                 domain="small_language", student_id="S1", first="市场活动",
                 segment="study_abroad_offline"),
            fact("network-cash", "abroad", "cash", 400, ["留学甲"],
                 domain="study_abroad", student_id="S2", first="网络资源",
                 segment="study_abroad_offline"),
            fact("tmk-cash", "abroad", "cash", 50, ["留学甲"],
                 domain="study_abroad", student_id="S3", first="TMK",
                 segment="study_abroad_offline"),
            fact("intl-order", "abroad", "orders", 99, ["留学甲"],
                 domain="study_abroad", segment="international_market"),
            fact("ssc-order", "abroad", "orders", 88, ["留学甲"],
                 domain="study_abroad", segment="ssc"),
            fact("not-personal", "abroad", "cash", 1000, ["留学甲"],
                 domain="study_abroad", segment="study_abroad_offline", eligible=False),
            fact("乙-resource", "abroad", "orders", 1, ["留学乙"],
                 domain="study_abroad", segment="study_abroad_offline"),
            fact("乙-cash", "abroad", "cash", 25, ["留学乙"],
                 domain="study_abroad", student_id="S1", first="官方合作高校",
                 segment="study_abroad_offline"),
        ]

        rows = build_radar(facts, people, abroad_people, "2026-09-30", capacity)
        by_name = {row["name"]: row for row in rows}

        self.assertEqual(tuple(key for key, _ in RADAR_DIMS),
                         ("orders", "heads", "conversion", "partner", "tmk", "campaign"))
        self.assertEqual(by_name["语培甲"]["business_line"], "training")
        self.assertEqual(by_name["语培甲"]["peer_group"], "training|高中")
        self.assertEqual(by_name["留学甲"]["business_line"], "abroad")
        self.assertEqual(by_name["留学甲"]["peer_group"], "abroad|留学")
        self.assertEqual(by_name["语培甲"]["orders"], 2)
        self.assertEqual(by_name["语培乙"]["orders"], 2)
        self.assertEqual(by_name["虚拟甲"]["orders"], 4)
        self.assertEqual(by_name["语培甲"]["partner"], 50)
        self.assertEqual(by_name["虚拟甲"]["partner"], 100)
        # The offline and virtual teams use separate peer means.
        axes = {axis["key"]: axis for axis in by_name["语培甲"]["radar"]["axes"]}
        self.assertAlmostEqual(axes["orders"]["mean"], 4 / 3)
        self.assertEqual(by_name["虚拟甲"]["radar"]["peer_count"], 1)

        abroad = by_name["留学甲"]
        self.assertEqual(abroad["orders"], 2)
        self.assertEqual(abroad["cash"], 950)
        self.assertEqual(abroad["partner"], 200)
        self.assertEqual(abroad["campaign"], 300)
        self.assertEqual(abroad["tmk"], 50)
        # S1 exists in both customer domains; don't pretend they can be merged.
        self.assertIsNone(abroad["heads"])
        self.assertIsNone(abroad["conversion"])
        self.assertEqual(abroad["product_parts"]["study_abroad"]["heads"], 3)
        self.assertEqual(abroad["product_parts"]["small_language"]["heads"], 1)
        self.assertEqual(abroad["product_parts"]["study_abroad"]["conversion"], 3)
        self.assertEqual(abroad["cash_capacity"], 120000)
        self.assertEqual(abroad["cash_progress_completion"], 950 / 40000)
        self.assertEqual(by_name["留学乙"]["heads"], 1)
        self.assertEqual(by_name["留学乙"]["conversion"], 1)
        self.assertIsNone(by_name["留学乙"]["cash_capacity"])
        self.assertEqual(abroad["start_date"], "2026-06-01")
        self.assertEqual(abroad["through_date"], "2026-09-30")

    def test_empty_covered_window_yields_zero_metrics_and_missing_targets_stay_none(self):
        people, abroad_people, _ = configs(full_abroad_target=False)

        rows = build_radar([], people, abroad_people, "2026-09-30", None)
        by_name = {row["name"]: row for row in rows}

        for name in ("语培甲", "留学甲", "留学乙"):
            self.assertEqual(by_name[name]["orders"], 0)
            self.assertEqual(by_name[name]["cash"], 0)
            self.assertEqual(by_name[name]["heads"], 0)
            self.assertEqual(by_name[name]["partner"], 0)
            self.assertEqual(len(by_name[name]["radar"]["axes"]), 6)
        self.assertIsNone(by_name["语培甲"]["cash_capacity"])
        self.assertIsNone(by_name["留学甲"]["cash_capacity"])
        self.assertIsNone(by_name["留学乙"]["cash_capacity"])
        self.assertIsNone(by_name["语培甲"]["cash_progress_completion"])

    def test_customer_domain_with_missing_id_keeps_heads_unknown(self):
        people, abroad_people, capacity = configs()
        facts = [
            fact("resource", "abroad", "orders", 1, ["留学甲"],
                 domain="study_abroad", segment="study_abroad_offline"),
            fact("cash-no-id", "abroad", "cash", 100, ["留学甲"],
                 domain="study_abroad", segment="study_abroad_offline"),
        ]

        row = next(row for row in build_radar(facts, people, abroad_people, "2026-06-30", capacity)
                   if row["name"] == "留学甲")

        self.assertIsNone(row["heads"])
        self.assertIsNone(row["conversion"])
        self.assertIsNone(row["product_parts"]["study_abroad"]["heads"])

    def test_single_customer_domain_conversion_uses_all_own_business_orders(self):
        people, abroad_people, capacity = configs()
        facts = [fact("study-resource", "abroad", "orders", 2, ["留学甲"], domain="study_abroad", segment="study_abroad_offline"),
                 fact("language-resource", "abroad", "orders", 1, ["留学甲"], domain="small_language", segment="study_abroad_offline"),
                 fact("study-cash", "abroad", "cash", 100, ["留学甲"], domain="study_abroad", segment="study_abroad_offline", student_id="contracts:1")]
        row = next(row for row in build_radar(facts, people, abroad_people, "2026-06-30", capacity) if row["name"] == "留学甲")
        self.assertEqual(row["orders"], 3)
        self.assertAlmostEqual(row["conversion"], 1 / 3)
        self.assertAlmostEqual(row["product_parts"]["study_abroad"]["conversion"], 1 / 2)

    def test_same_person_cannot_have_two_primary_rosters(self):
        people, abroad_people, capacity = configs()
        abroad_people["people"].append({"display_name": "语培甲", "business_group": "大学"})

        with self.assertRaisesRegex(ValueError, "同时配置"):
            build_radar([], people, abroad_people, "2026-06-30", capacity)


if __name__ == "__main__":
    unittest.main()
