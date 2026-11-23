"""Native channel source cache preserves the old source grid and tree shape."""
import json
import unittest

import duckdb

from dashboard_product.management.breakdowns import UNIVERSITY_SCHOOL_ATTRIBUTES
from dashboard_product.shadow_bi.sql_warehouse.native_channel_cache import (
    TABLE,
    SCOPES,
    UNIVERSITY_NODES_TABLE,
    install_native_channel_source,
    university_channel_node_sources,
)


class NativeChannelCacheTests(unittest.TestCase):
    scopes = SCOPES
    units = ("total", "prep", "high", "university", "virtual", "online",
             "overview_prep", "overview_high", "overview_university")
    periods = (
        ("FY27", "year", "2026-06-01"),
        ("Q1", "quarter", "2026-06-01"),
        ("Q2", "quarter", "2026-09-01"),
        ("Q3", "quarter", "2026-12-01"),
        ("Q4", "quarter", "2027-03-01"),
        ("2026-06", "month", "2026-06-01"),
        ("2026-07", "month", "2026-07-01"),
        ("2026-08", "month", "2026-08-01"),
        ("2026-09", "month", "2026-09-01"),
        ("2026-10", "month", "2026-10-01"),
        ("2026-11", "month", "2026-11-01"),
        ("2026-12", "month", "2026-12-01"),
        ("2027-01", "month", "2027-01-01"),
        ("2027-02", "month", "2027-02-01"),
        ("2027-03", "month", "2027-03-01"),
        ("2027-04", "month", "2027-04-01"),
        ("2027-05", "month", "2027-05-01"),
    )

    def setUp(self):
        self.con = duckdb.connect(":memory:")
        self.con.execute("SET threads=1; SET memory_limit='512MB'")
        self.con.execute("CREATE SCHEMA business")
        self.con.execute("""
            CREATE TABLE business.periods (
                period_id VARCHAR, kind VARCHAR, start_date DATE
            )
        """)
        self.con.executemany("INSERT INTO business.periods VALUES (?, ?, ?)", self.periods)
        self.con.execute("""
            CREATE TABLE business.dimension_seed (
                period_id VARCHAR, unit_id VARCHAR, acquisition_scope VARCHAR,
                business_line VARCHAR, dimension_type VARCHAR, dim1 VARCHAR,
                dim2 VARCHAR, dim3 VARCHAR, first_channel VARCHAR, metric VARCHAR,
                actual DOUBLE, prior DOUBLE, yoy DOUBLE, status VARCHAR,
                display VARCHAR, share DOUBLE, cash_share DOUBLE,
                channel_cash_share DOUBLE
            )
        """)
        self.con.execute("""
            CREATE MACRO business.dimension_query(periods, units, acquisitions, dimensions) AS TABLE (
                SELECT d.* FROM business.dimension_seed d
                WHERE (periods IS NULL OR array_length(periods)=0 OR list_contains(periods,d.period_id))
                  AND (units IS NULL OR array_length(units)=0 OR list_contains(units,d.unit_id))
                  AND (acquisitions IS NULL OR array_length(acquisitions)=0 OR list_contains(acquisitions,d.acquisition_scope))
                  AND (dimensions IS NULL OR array_length(dimensions)=0 OR list_contains(dimensions,d.dimension_type))
            )
        """)
        self._insert_dimensions()
        install_native_channel_source(self.con)

    def tearDown(self):
        self.con.close()

    def _insert_dimensions(self):
        attribute = UNIVERSITY_SCHOOL_ATTRIBUTES[0]
        rows = []
        for scope in self.scopes:
            for unit in ("total", "prep", "high", "virtual", "online",
                         "overview_prep", "overview_high", "overview_university"):
                rows.extend(self._channel_nodes(
                    "FY27", unit, scope, "training", "普通渠道", "一级来源",
                    {"overview_prep": "留学预备", "overview_high": "高中",
                     "overview_university": "大学"}.get(unit, "青少"), None,
                ))
            rows.extend(self._channel_nodes(
                "FY27", "total", scope, "abroad", "留学渠道", "合作来源",
                "线上留学", None,
            ))
            rows.extend(self._channel_nodes(
                "FY27", "university", scope, "training", "大学渠道", "一级大学来源",
                attribute, "目标学校",
            ))
            rows.extend(self._channel_nodes(
                "FY27", "university", scope, "abroad", "大学留学渠道", "大学合作来源",
                attribute, "留学目标学校",
            ))
        self.con.executemany(
            "INSERT INTO business.dimension_seed VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )

    @staticmethod
    def _channel_nodes(period, unit, scope, line, channel, first, group, school):
        nodes = [
            ("channel", channel, "∅", "∅"),
            ("channel_group", channel, group, "∅"),
        ]
        if school:
            nodes.append(("channel_school", channel, group, school))
        result = []
        for dimension_type, dim1, dim2, dim3 in nodes:
            for metric, actual in (("orders", 11.0), ("cash", 22.0), ("heads", 3.0)):
                result.append((
                    period, unit, scope, line, dimension_type, dim1, dim2, dim3,
                    first, metric, actual, actual / 2, 0.5, "available", "3人",
                    0.25, 0.5, 0.75,
                ))
        return result

    def test_installs_old_schema_complete_grid_and_physical_traversal_order(self):
        schema = self.con.execute(f"DESCRIBE {TABLE}").fetchall()
        self.assertEqual(
            [(row[0], row[1]) for row in schema],
            [
                ("acquisition_scope", "VARCHAR"),
                ("period_id", "VARCHAR"),
                ("team_id", "VARCHAR"),
                ("view", "VARCHAR"),
                ("row_json", "JSON"),
            ],
        )
        self.assertEqual(self.con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0], 1377)
        self.assertEqual(
            self.con.execute(
                f"""SELECT acquisition_scope, count(*), count(DISTINCT period_id),
                           count(DISTINCT team_id)
                    FROM {TABLE} GROUP BY acquisition_scope
                    ORDER BY acquisition_scope"""
            ).fetchall(),
            [(scope, 153, 17, 9) for scope in sorted(self.scopes)],
        )
        expected = [
            (scope, period_id, unit)
            for scope in self.scopes
            for period_id, _, _ in self.periods
            for unit in self.units
        ]
        actual = self.con.execute(
            f"SELECT acquisition_scope,period_id,team_id FROM {TABLE}"
        ).fetchall()
        self.assertEqual(actual, expected)

    def test_student_selection_keeps_separate_channel_cash(self):
        self.con.execute("""UPDATE business.dimension_seed SET actual=7
            WHERE unit_id='total' AND acquisition_scope='被动|老生'
            AND business_line='training' AND metric='cash'""")
        install_native_channel_source(self.con)
        amounts = {}
        for scope in ('被动', '被动|老生'):
            raw = self.con.execute(
                f"SELECT view FROM {TABLE} WHERE period_id='FY27' AND team_id='total' AND acquisition_scope=?",
                [scope],
            ).fetchone()[0]
            node = next(x for x in json.loads(raw)['channels'] if x['business_line']=='training')
            amounts[scope] = node['cash']['actual']
        self.assertEqual(amounts, {'被动': 22, '被动|老生': 7})

    def test_overview_groups_keep_nonempty_training_channel_trees(self):
        for unit, group in [('overview_prep', '留学预备'), ('overview_high', '高中'),
                            ('overview_university', '大学')]:
            for scope in self.scopes:
                raw = self.con.execute(
                    f"SELECT view FROM {TABLE} WHERE period_id='FY27' AND team_id=? AND acquisition_scope=?",
                    [unit, scope],
                ).fetchone()[0]
                channels = json.loads(raw)['channels']
                self.assertEqual(len(channels), 1)
                self.assertEqual(channels[0]['business_line'], 'training')
                self.assertEqual(channels[0]['name'], '普通渠道')
                self.assertEqual(channels[0]['groups'][0]['name'], group)
                self.assertEqual(channels[0]['orders']['actual'], 11)

    def test_fills_empty_rows_and_preserves_university_attribute_school_leaves(self):
        empty_view, empty_row = self.con.execute(
            f"SELECT view,row_json FROM {TABLE} WHERE acquisition_scope='被动' AND period_id='2026-12' AND team_id='online'"
        ).fetchone()
        self.assertEqual(json.loads(empty_view), {"channels": []})
        self.assertEqual(json.loads(empty_row), {
            "acquisition_scope": "被动",
            "period_id": "2026-12",
            "team_id": "online",
            "view": {"channels": []},
        })

        view = self.con.execute(
            f"SELECT view FROM {TABLE} WHERE acquisition_scope='被动' AND period_id='FY27' AND team_id='university'"
        ).fetchone()[0]
        tree = json.loads(view)
        parents = {node["name"]: node for node in tree["channels"]}
        self.assertIn("大学渠道", parents)
        self.assertIn("大学留学渠道", parents)
        training_child = parents["大学渠道"]["groups"][0]
        self.assertEqual(training_child["name"], UNIVERSITY_SCHOOL_ATTRIBUTES[0])
        self.assertEqual(training_child["schools"][0]["name"], "目标学校")
        abroad_child = parents["大学留学渠道"]["groups"][0]
        self.assertEqual(abroad_child["schools"][0]["name"], "留学目标学校")

    def test_builds_typed_university_group_and_school_rows(self):
        schema = self.con.execute(f"DESCRIBE {UNIVERSITY_NODES_TABLE}").fetchall()
        schema_types = {row[0]: row[1] for row in schema}
        self.assertEqual(schema_types["node_kind"], "VARCHAR")
        self.assertEqual(schema_types["school_name"], "VARCHAR")
        for name in ("工单", "工单同期", "工单同比", "现金", "现金占比", "渠道内现金占比"):
            self.assertEqual(schema_types[name], "DOUBLE")
        for name in ("分域人数", "工单状态", "现金状态", "人数状态"):
            self.assertEqual(schema_types[name], "VARCHAR")

        self.assertEqual(
            self.con.execute(
                f"""SELECT acquisition_scope,node_kind,business_line,channel,group_name,school_name,
                           工单,现金,渠道内现金占比,工单状态
                    FROM {UNIVERSITY_NODES_TABLE}
                    WHERE period_id='FY27'
                    ORDER BY acquisition_scope,
                             node_kind,business_line"""
            ).fetchall(),
            [
                (scope, kind, line, channel, UNIVERSITY_SCHOOL_ATTRIBUTES[0], school,
                 11.0, 22.0, 0.75, "已提供")
                for scope in sorted(self.scopes)
                for kind, line, channel, school in (
                    ("group", "abroad", "大学留学渠道", None),
                    ("group", "training", "大学渠道", None),
                    ("school", "abroad", "大学留学渠道", "留学目标学校"),
                    ("school", "training", "大学渠道", "目标学校"),
                )
            ],
        )

        sources = university_channel_node_sources()
        groups_sql = sources["groups"].replace("{{ acquisition_scope }}", "被动")
        schools_sql = sources["schools"].replace("{{ acquisition_scope }}", "被动")
        group_columns = [row[0] for row in self.con.execute(f"DESCRIBE ({groups_sql})").fetchall()]
        school_columns = [row[0] for row in self.con.execute(f"DESCRIBE ({schools_sql})").fetchall()]
        self.assertIn("同期状态", group_columns)
        self.assertNotIn("同期状态", school_columns)
        self.assertIn("渠道内现金占比", school_columns)
        self.assertEqual(self.con.execute(f"SELECT count(*) FROM ({groups_sql})").fetchone()[0], 2)
        self.assertEqual(self.con.execute(f"SELECT count(*) FROM ({schools_sql})").fetchone()[0], 2)
        self.assertEqual(
            self.con.execute(f"SELECT DISTINCT \"管理单元\" FROM ({groups_sql})").fetchall(),
            [("university",)],
        )

    def test_reinstall_rebuilds_the_source_from_current_dimension_rows(self):
        self.con.execute(
            "UPDATE business.dimension_seed SET dim1='刷新后渠道' WHERE unit_id='total' AND dim1='普通渠道'"
        )
        self.con.execute(
            "UPDATE business.dimension_seed SET status='partial' "
            "WHERE unit_id='university' AND metric='cash'"
        )
        install_native_channel_source(self.con)
        view, count = self.con.execute(
            f"SELECT view,(SELECT count(*) FROM {TABLE}) FROM {TABLE} WHERE acquisition_scope='被动' AND period_id='FY27' AND team_id='total'"
        ).fetchone()
        self.assertEqual(count, 1377)
        names = [node["name"] for node in json.loads(view)["channels"]]
        self.assertIn("刷新后渠道", names)
        self.assertNotIn("普通渠道", names)
        self.assertEqual(
            self.con.execute(
                f"SELECT DISTINCT \"现金状态\" FROM {UNIVERSITY_NODES_TABLE} WHERE period_id='FY27'"
            ).fetchall(),
            [("部分覆盖",)],
        )
        self.assertEqual(
            self.con.execute(
                f"SELECT count(*) FROM {UNIVERSITY_NODES_TABLE} WHERE period_id='FY27'"
            ).fetchone()[0],
            36,
        )


if __name__ == "__main__":
    unittest.main()
