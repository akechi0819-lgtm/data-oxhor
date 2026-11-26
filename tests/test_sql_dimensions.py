"""Dimension rollups stay in DuckDB and retain the management breakdown rules."""
import unittest

import duckdb

from dashboard_product.shadow_bi.sql_warehouse.dimensions import install_dimensions


class DimensionSqlTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect(":memory:")
        self.con.execute("SET threads=2; SET memory_limit='512MB'")
        self.con.execute("CREATE SCHEMA business; CREATE SCHEMA config; CREATE SCHEMA source")
        self.con.execute("""
            CREATE VIEW business.acquisition_scopes AS
            SELECT * FROM (VALUES
                ('被动','被动','全部'),('主动','主动','全部'),('全部','全部','全部'),
                ('被动|新生','被动','新生'),('被动|老生','被动','老生'),
                ('主动|新生','主动','新生'),('主动|老生','主动','老生'),
                ('全部|新生','全部','新生'),('全部|老生','全部','老生')
            ) t(acquisition_scope, acquisition_mode, student_type_scope)
        """)
        self.con.execute("""
            CREATE TABLE business.periods (
                period_id VARCHAR, start_date DATE, through_date DATE,
                status VARCHAR, time_progress DOUBLE
            )
        """)
        self.con.execute("""
            CREATE TABLE business.scopes (
                unit_id VARCHAR, source_team VARCHAR, business_group VARCHAR,
                abroad_segment VARCHAR, selection_mask INTEGER
            )
        """)
        self.con.execute("""
            CREATE TABLE business.period_events (
                period_id VARCHAR, unit_id VARCHAR, acquisition_scope VARCHAR,
                business_line VARCHAR, comparison VARCHAR, event_date DATE,
                metric VARCHAR, value DOUBLE, student_id VARCHAR, class_code VARCHAR,
                registration_count DOUBLE, business_group VARCHAR, comparison_group VARCHAR,
                first_channel VARCHAR, second_channel VARCHAR, school_name VARCHAR,
                school_attribute VARCHAR, channel_school_name VARCHAR, grade_name VARCHAR,
                customer_domain VARCHAR, segment_id VARCHAR, country VARCHAR, line VARCHAR, fact_id VARCHAR
            )
        """)
        self.con.execute("""
            CREATE TABLE business.team_metrics (
                period_id VARCHAR, unit_id VARCHAR, acquisition_scope VARCHAR,
                business_line VARCHAR, metric VARCHAR, actual DOUBLE, prior DOUBLE,
                target DOUBLE, status VARCHAR, time_progress DOUBLE
            )
        """)
        self.con.execute("""
            CREATE TABLE config.targets (
                business_line VARCHAR, business_group VARCHAR, team_id VARCHAR,
                period_id VARCHAR, metric VARCHAR, target DOUBLE
            )
        """)
        self.con.execute("""
            CREATE TABLE source.market_orders (
                work_order_id VARCHAR, event_date DATE, business_group VARCHAR,
                team_id VARCHAR, first_channel VARCHAR, second_channel VARCHAR
            )
        """)
        self.con.execute("""
            CREATE TABLE source.new_student_cash (
                cash_date DATE, student_type VARCHAR, business_group VARCHAR,
                cash_amount DECIMAL(38, 2)
            )
        """)
        self.con.execute("""
            INSERT INTO business.periods VALUES
                ('2026-06', DATE '2026-06-01', DATE '2026-06-30', 'available', 1.0)
        """)
        self.con.executemany(
            "INSERT INTO business.scopes VALUES (?, ?, ?, ?, ?)",
            [
                ('total', None, None, None, None),
                ('online_scope', None, None, None, None),
                ('offline_scope', None, None, None, None),
                ('prep', 'offline_market', '留学预备', None, None),
                ('university', 'offline_market', '大学', 'study_abroad_offline', None),
                ('selection_1', None, None, None, 1),
            ],
        )
        self.con.execute("CREATE TABLE source.training_rows (_input_order BIGINT, metric VARCHAR, work_order_id VARCHAR, source_row_number VARCHAR)")
        self._team_metrics()
        self._targets()
        self._events()
        self._sources()
        install_dimensions(self.con)

    def tearDown(self):
        self.con.close()

    def _team_metrics(self):
        rows = []
        for unit, lines in (
            ('total', ('training', 'abroad')),
            ('prep', ('training',)),
            ('university', ('training', 'abroad')),
        ):
            for line in lines:
                for metric in ('orders', 'cash', 'heads'):
                    rows.append((
                        '2026-06', unit, '被动', line, metric,
                        None, None, None, 'available', 1.0,
                    ))
        self.con.executemany(
            "INSERT INTO business.team_metrics VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows,
        )

    def _targets(self):
        rows = []
        for team, orders, cash in (
            ('offline_market', 10, 100),
            ('online_private', 20, 200),
            ('online_platform', 30, 300),
        ):
            rows.extend([
                ('training', '留学预备', team, '2026-06', 'orders', orders),
                ('training', '留学预备', team, '2026-06', 'cash', cash),
            ])
        rows.extend([
            ('training', '大学', 'offline_market', '2026-06', 'orders', 40),
            ('training', '大学', 'offline_market', '2026-06', 'cash', 400),
        ])
        self.con.executemany("INSERT INTO config.targets VALUES (?, ?, ?, ?, ?, ?)", rows)

    def _event(
        self, *, unit='total', line='training', comparison='actual', metric='cash',
        value=0, student=None, course=None, registration=0, business_group='留学预备',
        comparison_group='青少', first='市场活动', second='校代', school='学校A',
        attribute=None, channel_school=None, grade='七年级', domain=None,
        segment=None, country=None, country_line=None, day='2026-06-10', scope='被动',
    ):
        ordinal = self.con.execute("SELECT COUNT(*) + 1 FROM source.training_rows").fetchone()[0]
        self.con.execute("INSERT INTO source.training_rows VALUES (?, 'passive_reported_cash', NULL, ?)", [ordinal, str(ordinal)])
        self.con.execute(
            """INSERT INTO business.period_events VALUES (
                '2026-06', ?, ?, ?, ?, CAST(? AS DATE), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            [unit, scope, line, comparison, day, metric, value, student, course,
             registration, business_group, comparison_group, first, second, school,
             attribute, channel_school, grade, domain, segment, country, country_line, f"training:cash:{ordinal}"],
        )

    def _events(self):
        # One student qualifies in two classes but is counted once. Another does
        # not meet the money threshold, and one has no positive registration.
        for value, course, registration, student in (
            (1000, 'C1', 0, 'S1'), (600, 'C1', 1, 'S1'),
            (2000, 'C2', 1, 'S1'), (1500, 'C1', 1, 'S2'),
            (1499, 'C1', 1, 'S3'), (2500, 'C1', 0, 'S4'),
        ):
            self._event(value=value, course=course, registration=registration, student=student)
        self._event(metric='orders', value=99, student='S1')
        self._event(comparison='prior', value=1500, course='C1', registration=1, student='S1', day='2025-06-10')

        # The same selected fact shape exists under the prep operating unit.
        self._event(unit='prep', value=1500, course='P1', registration=1, student='P1', grade='八年级')
        self._event(unit='prep', metric='orders', value=1, student='P1', grade='八年级')
        self._event(unit='prep', comparison='prior', value=1500, course='P1', registration=1,
                    student='P1', grade='八年级', day='2025-06-10')

        # University training channel groups use school attributes, then expose
        # the normalized channel-school name under that category.
        self._event(unit='university', business_group='大学', comparison_group='大学',
                    value=1500, student='U1', course='U1', registration=1,
                    attribute='本地大学', channel_school='大学渠道名', school='大学原学校', grade='大一')
        self._event(unit='university', business_group='大学', comparison_group='大学',
                    metric='orders', value=1, student='U1', attribute='本地大学',
                    channel_school='大学渠道名', school='大学原学校', grade='大一')

        # Two abroad customer domains remain separate when both occur inside
        # the same selected bucket; country rows are still ordinary SQL sums.
        self._event(unit='university', line='abroad', business_group='大学',
                    metric='cash', value=300, student='A1', domain='study_abroad',
                    segment='study_abroad_offline', school=None, grade=None)
        self._event(unit='university', line='abroad', business_group='大学',
                    metric='cash', value=500, student='L1', domain='small_language',
                    segment='study_abroad_offline', school=None, grade=None)
        self._event(unit='university', line='abroad', business_group='大学',
                    metric='orders', value=1, student='A1', domain='study_abroad',
                    segment='study_abroad_offline', country='英国', country_line='英澳条线', school=None, grade=None)
        self._event(unit='university', line='abroad', business_group='大学',
                    metric='orders', value=2, student='A2', domain='study_abroad',
                    segment='unassigned', country=None, country_line=None, school=None, grade=None)
        self._event(line='abroad', metric='orders', value=1, segment='study_abroad_online',
                    country='加拿大', country_line='北美条线')

    def _sources(self):
        self.con.executemany(
            "INSERT INTO source.market_orders VALUES (?, ?, ?, ?, ?, ?)",
            [
                ('M1', '2026-06-10', '青少', 'offline_market', '市场活动', '校代'),
                ('M1', '2026-06-10', '青少', 'offline_market', '市场活动', '校代'),
                ('M2', '2026-06-11', '初中', 'offline_market', '市场活动', '校代'),
                ('M3', '2026-06-12', '未映射组', 'offline_market', '市场活动', '校代'),
                ('M0', '2025-06-10', '青少', 'offline_market', '市场活动', '校代'),
                ('ON1', '2026-06-13', '青少', 'online_private', '线上活动', '虚拟人'),
                ('ON2', '2026-06-14', '未映射组', 'online_platform', 'TMK激活-平台', '平台'),
                ('ONP', '2025-06-13', '青少', 'online_platform', '线上活动', '平台'),
            ],
        )
        self.con.execute("""
            INSERT INTO source.new_student_cash VALUES
                (DATE '2026-06-10', '新生', '留学预备', 10000.00),
                (DATE '2026-06-10', '老生', '留学预备', 5000.00),
                (DATE '2026-06-10', NULL, '留学预备', 2500.00),
                (DATE '2026-06-10', '新生', '留学预备', -100.00)
        """)

    def _dimension_row(self, dimension_type, dim1, *, unit='total', scope='被动',
                       line='training', dim2='∅', dim3='∅', first='∅', metric='orders'):
        return self.con.execute(
            """SELECT actual, prior, target, status, share, cash_share,
                      channel_cash_share, passive_cash_share,
                      cash_share_numerator, cash_share_denominator
               FROM business.dimension_metrics
               WHERE period_id='2026-06' AND unit_id=? AND acquisition_scope=?
                 AND business_line=? AND dimension_type=? AND dim1=? AND dim2=? AND dim3=?
                 AND first_channel=? AND metric=?""",
            [unit, scope, line, dimension_type, dim1, dim2, dim3, first, metric],
        ).fetchone()

    def test_grade_cash_share_preserves_mixed_integer_float_sum_and_fact_order(self):
        # Real FY27 grade amounts: _number emits whole amounts as ints. Their
        # insertion order changes Python 3.12's mixed-type compensated sum.
        amounts = [296453.3, 64667.3, 253536.4, 176758.8, 155258.3,
                   136891, 169250, 349115.6, 1350322.2, 182731, 938370.9,
                   210059, 117700, 11027.3, 0, 0, 0, 10350]
        self.con.execute("DELETE FROM business.period_events")
        self.con.execute("DELETE FROM source.training_rows")
        for index, amount in enumerate(amounts):
            self._event(grade=f'grade-{99-index}', value=amount)
        rows = self.con.execute("""
            SELECT dim1, actual, cash_share FROM business.dimension_query(
                ['2026-06'], ['total'], ['被动'], ['grade']) WHERE metric='cash'
        """).fetchall()
        denominator = 4422491.100000001
        self.assertEqual(sum(amounts), denominator)
        self.assertNotEqual(sum(map(float, amounts)), denominator)
        for _, actual, share in rows:
            self.assertEqual(share, actual / denominator)
        self.assertEqual(dict((name, share) for name, _, share in rows)['grade-82'],
                         0.0023403099669324374)

    def test_grade_cash_integer_prefix_first_float_is_not_compensated(self):
        amounts = [405260, 146629.1, 14719.7, 60960, 16200, 303948,
                   4980, 13300, 13500, 18920]
        self.con.execute("DELETE FROM business.period_events")
        self.con.execute("DELETE FROM source.training_rows")
        for index, amount in enumerate(amounts):
            self._event(grade=f'grade-{index}', value=amount)
        rows = self.con.execute("""
            SELECT actual, cash_share FROM business.dimension_query(
                ['2026-06'], ['total'], ['被动'], ['grade']) WHERE metric='cash'
        """).fetchall()
        denominator = 998416.7999999999
        self.assertEqual(sum(amounts), denominator)
        for actual, share in rows:
            self.assertEqual(share, actual / denominator)

    def test_school_cash_share_sums_mixed_amounts_in_school_name_order(self):
        # School traversal is alphabetical, independently of fact insertion.
        # Cover both a fractional first amount and an integer prefix.
        cases = [
            [296453.3, 64667.3, 253536.4, 176758.8, 155258.3,
             136891, 169250, 349115.6, 1350322.2, 182731, 938370.9,
             210059, 117700, 11027.3, 0, 0, 0, 10350],
            [405260, 146629.1, 14719.7, 60960, 16200, 303948,
             4980, 13300, 13500, 18920],
        ]
        for amounts in cases:
            self.con.execute('DELETE FROM business.period_events')
            self.con.execute('DELETE FROM source.training_rows')
            for index in reversed(range(len(amounts))):
                self._event(school=f'school-{index:02}', value=amounts[index])
            rows = self.con.execute("""
                SELECT dim1,actual,cash_share FROM business.dimension_query(
                    ['2026-06'], ['total'], ['被动'], ['school']) WHERE metric='cash'
                ORDER BY dim1
            """).fetchall()
            self.assertEqual(len(rows), len(amounts))
            denominator = sum(amounts)
            for (_, actual, share), amount in zip(rows, amounts):
                self.assertEqual(actual, amount)
                self.assertEqual(share, amount / denominator)
            children = self.con.execute("""
                SELECT dimension_type,actual,cash_share FROM business.dimension_query(
                    ['2026-06'], ['total'], ['被动'], ['school_grade']) WHERE metric='cash'
                ORDER BY dim1
            """).fetchall()
            self.assertEqual(len(children), len(amounts))
            for (kind, actual, share), amount in zip(children, amounts):
                self.assertEqual(kind, 'school_grade')
                self.assertEqual(actual, amount)
                self.assertEqual(share, amount / denominator)

    def test_business_group_uses_passive_market_orders_targets_and_cash_share(self):
        row = self._dimension_row('business_group', '留学预备')
        self.assertEqual(row[:4], (3.0, 2.0, 60.0, 'available'))

        cash = self._dimension_row('business_group', '留学预备', metric='cash')
        self.assertEqual(cash[2:4], (600.0, 'available'))
        self.assertAlmostEqual(cash[7], 9099 / 17500)
        self.assertEqual(cash[8:], (9099.0, 17500.0))

        unknown = self._dimension_row('business_group', '业务组暂无法拆分')
        self.assertEqual(unknown[0], 2.0)

    def test_scope_business_groups_use_raw_market_team_ids_and_unknown_skeleton(self):
        online = self._dimension_row('business_group', '留学预备', unit='online_scope')
        offline = self._dimension_row('business_group', '留学预备', unit='offline_scope')
        self.assertEqual(online[:4], (1.0, 1.0, 50.0, 'available'))
        self.assertEqual(offline[:4], (2.0, 1.0, 10.0, 'available'))

        for unit, expected_orders in (('online_scope', 1.0), ('offline_scope', 1.0)):
            unknown_orders = self._dimension_row(
                'business_group', '业务组暂无法拆分', unit=unit,
            )
            self.assertEqual(unknown_orders[0], expected_orders)
            for metric in ('cash', 'heads'):
                zero = self._dimension_row(
                    'business_group', '业务组暂无法拆分', unit=unit, metric=metric,
                )
                self.assertEqual(zero[0], 0.0)
                self.assertEqual(zero[3], 'available')

        active_online = self._dimension_row(
            'business_group', '业务组暂无法拆分', unit='online_scope', scope='主动',
        )
        all_offline = self._dimension_row(
            'business_group', '留学预备', unit='offline_scope', scope='全部',
        )
        self.assertEqual(active_online[0], 0.0)
        self.assertEqual(all_offline[0], 0.0)
        self.assertIsNone(all_offline[2])

    def test_market_order_override_is_limited_to_passive_total_business_groups(self):
        self._event(unit='total', scope='主动', metric='orders', value=7, student='S1')
        self._event(unit='total', scope='全部', metric='orders', value=106, student='S1')
        self.con.executemany(
            "INSERT INTO business.team_metrics VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ('2026-06', 'total', scope, 'training', metric, None, None, None, 'available', 1.0)
                for scope in ('主动', '全部') for metric in ('orders', 'cash', 'heads')
            ],
        )
        install_dimensions(self.con)
        active_row = self._dimension_row('business_group', '留学预备', scope='主动')
        all_row = self._dimension_row('business_group', '留学预备', scope='全部')
        active, all_scope = active_row[0], all_row[0]
        self.assertEqual((active, all_scope), (7.0, 106.0))
        self.assertIsNone(active_row[2])
        self.assertIsNone(all_row[2])

    def test_training_head_qualification_dedupes_student_after_class_threshold(self):
        heads = self._dimension_row('business_group', '留学预备', metric='heads')
        self.assertEqual(heads[0], 2.0)
        prior = self.con.execute("""
            SELECT actual, prior FROM business.dimension_metrics
            WHERE unit_id='total' AND acquisition_scope='被动' AND business_line='training'
              AND dimension_type='comparison_group' AND dim1='青少' AND metric='heads'
        """).fetchone()
        self.assertEqual(prior, (2.0, 1.0))

    def test_positive_cash_share_denominator_follows_student_type_scope(self):
        values = self.con.execute("""
            SELECT acquisition_scope, cash_share_denominator
            FROM business.dimension_metrics
            WHERE period_id='2026-06' AND unit_id='total' AND business_line='training'
              AND dimension_type='business_group' AND dim1='留学预备' AND metric='cash'
              AND acquisition_scope IN ('被动','被动|新生','被动|老生')
        """).fetchall()
        self.assertEqual(dict(values), {
            '被动': 17500.0, '被动|新生': 10000.0, '被动|老生': 5000.0,
        })

    def test_channel_school_grade_alias_and_grade_metrics(self):
        group = self._dimension_row(
            'channel_group', '校代', unit='university', line='training',
            dim2='本地大学', first='市场活动', metric='orders',
        )
        self.assertEqual(group[0], 1.0)
        school = self._dimension_row(
            'channel_school', '校代', unit='university', line='training',
            dim2='本地大学', dim3='大学渠道名', first='市场活动', metric='orders',
        )
        self.assertEqual(school[0], 1.0)

        grade = self._dimension_row(
            'school_grade', '学校A', unit='prep', line='training',
            dim2='初二', metric='orders',
        )
        self.assertEqual(grade[0], 1.0)
        grade_metrics = self.con.execute("""
            SELECT DISTINCT metric FROM business.dimension_metrics WHERE dimension_type='grade'
        """).fetchall()
        self.assertEqual({row[0] for row in grade_metrics}, {'orders', 'cash'})

    def test_parameterized_dimension_query_filters_before_returning_rows(self):
        rows = self.con.execute("""
            SELECT DISTINCT period_id, unit_id, acquisition_scope, dimension_type
            FROM business.dimension_query(
                ['2026-06'], ['university'], ['被动'], ['channel_group']
            )
        """).fetchall()
        self.assertEqual(rows, [('2026-06', 'university', '被动', 'channel_group')])
        share = self.con.execute("""
            SELECT channel_cash_share FROM business.dimension_query(
                ['2026-06'], ['university'], ['被动'], ['channel_group'])
            WHERE business_line='training' AND metric='cash' AND dim2='本地大学'
        """).fetchone()
        self.assertEqual(share, (1.0,))

    def test_abroad_split_heads_and_country_views(self):
        heads = self.con.execute("""
            SELECT actual, prior, status, display, study_heads, small_language_heads
            FROM business.dimension_metrics
            WHERE period_id='2026-06' AND unit_id='university' AND acquisition_scope='被动'
              AND business_line='abroad' AND dimension_type='channel' AND dim1='校代'
              AND first_channel='市场活动' AND metric='heads'
        """).fetchone()
        self.assertEqual(heads, (None, None, 'separate_counts', '留学1人／小语种1人', 1.0, 1.0))
        country = self.con.execute("""
            SELECT online, offline, unassigned, total FROM business.dimension_countries
            WHERE period_id='2026-06' AND unit_id='university' AND acquisition_scope='被动'
              AND line='英澳条线' AND country='英国'
        """).fetchone()
        self.assertEqual(country, (0.0, 1.0, 0.0, 1.0))
        selection_country = self.con.execute("""
            SELECT online, offline, unassigned, total FROM business.dimension_countries
            WHERE period_id='2026-06' AND unit_id='selection_1' AND acquisition_scope='被动'
              AND line='北美条线' AND country='加拿大'
        """).fetchone()
        self.assertEqual(selection_country, (1.0, 0.0, 0.0, 1.0))
        grouped = self.con.execute("""
            SELECT online, offline, unassigned, total FROM business.dimension_country_groups
            WHERE period_id='2026-06' AND unit_id='university' AND acquisition_scope='被动'
              AND line='英澳条线'
        """).fetchone()
        self.assertEqual(grouped, (0.0, 1.0, 0.0, 1.0))

    def test_virtual_resources_are_counted_in_online_country_split(self):
        self._event(unit='total', line='abroad', metric='orders', value=1,
                    segment='study_abroad_virtual', country='加拿大', country_line='北美条线')
        country = self.con.execute("""
            SELECT online, offline, unassigned, total FROM business.dimension_countries
            WHERE period_id='2026-06' AND unit_id='total' AND acquisition_scope='被动'
              AND line='北美条线' AND country='加拿大'
        """).fetchone()
        self.assertEqual(country, (2.0, 0.0, 0.0, 2.0))


if __name__ == '__main__':
    unittest.main()
