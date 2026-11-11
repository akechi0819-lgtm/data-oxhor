import json
import tempfile
import unittest
from unittest.mock import patch
from zipfile import BadZipFile
from decimal import Decimal
from pathlib import Path

import duckdb

from dashboard_product.shadow_bi.sql_warehouse import expenses


class ExpenseWarehouseTests(unittest.TestCase):
    def setUp(self):
        self.connection = duckdb.connect(":memory:")
        self.addCleanup(self.connection.close)
        expenses.install(self.connection)

    def test_manifest_failure_keeps_committed_fees_and_new_business_visible(self):
        expenses.replace_sources(self.connection, {
            'rows':[self.row('xhs-old','2026-10-01',12,account_id='a')],
            'sources':[self.source('xhs-old',account_id='a')]}, 'fees-old')
        self.connection.execute('CREATE SCHEMA business; CREATE TABLE business.new_data AS SELECT 25 AS orders')
        result=expenses.refresh_from_manifest(self.connection, '/missing/fees/manifest.json', 'fees-new')
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['retained_rows'],1)
        self.assertEqual(self.connection.execute('SELECT sum(amount) FROM expenses.expense_rows').fetchone()[0],Decimal('12.00'))
        self.assertEqual(self.connection.execute('SELECT orders FROM business.new_data').fetchone()[0],25)

    def test_corrupt_sem_workbook_is_a_visible_fee_failure(self):
        with patch.object(expenses,'parse_manifest',side_effect=BadZipFile('invalid SEM workbook')):
            result=expenses.refresh_from_manifest(self.connection,'fees.json','fees-new')
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['error_type'],'BadZipFile')
        self.assertIn('invalid SEM workbook',result['error'])

    @staticmethod
    def source(source_id, platform="小红书", **values):
        return {
            "source_id": source_id, "grain": "daily", "platform": platform,
            "business_line": "training", "business_group": "大学",
            "start_date": "2026-10-01", "end_date": "2026-10-01",
            "sha256": "a" * 64, **values,
        }

    @staticmethod
    def row(source_id, day, amount, *, platform="小红书", source_row=2, **values):
        return {
            "source_id": source_id, "source_row": source_row,
            "business_line": "training", "business_group": "大学",
            "platform": platform, "start_date": day, "end_date": day,
            "amount": amount, **values,
        }

    def test_repeated_natural_key_with_new_source_id_replaces_instead_of_summing(self):
        expenses.replace_sources(self.connection, {
            "rows": [self.row("xhs_old", "2026-10-01", 12, account_id="account-7")],
            "sources": [self.source("xhs_old", account_id="account-7")],
        }, "import-1")
        expenses.replace_sources(self.connection, {
            "rows": [self.row("xhs_new", "2026-10-01", 12, account_id="account-7")],
            "sources": [self.source("xhs_new", account_id="account-7")],
        }, "import-2")

        result = self.connection.execute(
            "SELECT count(*), sum(amount), max(source_id) FROM expenses.expense_rows"
        ).fetchone()
        self.assertEqual(result, (1, Decimal("12.00"), "xhs_new"))

    def test_partial_input_replaces_only_its_explicit_window(self):
        expenses.replace_sources(self.connection, {
            "rows": [
                self.row("xhs-a", "2026-10-01", 10, account_id="account-a", source_row=2),
                self.row("xhs-a", "2026-10-02", 20, account_id="account-a", source_row=3),
                self.row("xhs-a", "2026-10-03", 30, account_id="account-a", source_row=4),
                self.row("xhs-b", "2026-10-01", 40, account_id="account-b", source_row=2),
            ],
            "sources": [
                {**self.source("xhs-a", account_id="account-a"), "end_date": "2026-10-03"},
                self.source("xhs-b", account_id="account-b"),
            ],
        }, "initial")
        expenses.replace_sources(self.connection, {
            "rows": [self.row("xhs-a-revised", "2026-10-02", 25, account_id="account-a")],
            "sources": [{**self.source("xhs-a-revised", account_id="account-a"),
                         "start_date": "2026-10-02", "end_date": "2026-10-02",
                         "requested_start_date": "2026-10-02", "requested_end_date": "2026-10-02"}],
        }, "partial")

        rows = self.connection.execute(
            "SELECT account_id, CAST(start_date AS VARCHAR), amount FROM expenses.expense_rows ORDER BY account_id, start_date"
        ).fetchall()
        self.assertEqual(rows, [
            ("account-a", "2026-10-01", Decimal("10.00")),
            ("account-a", "2026-10-02", Decimal("25.00")),
            ("account-a", "2026-10-03", Decimal("30.00")),
            ("account-b", "2026-10-01", Decimal("40.00")),
        ])

    def test_period_attribution_change_replaces_prior_group(self):
        def period_batch(source_id, group, amount):
            source = {
                "source_id": source_id, "grain": "period", "platform": "百度",
                "business_line": "abroad", "business_group": group,
                "company": "Company A", "start_date": "2026-10-01",
                "end_date": "2026-10-07", "sha256": "b" * 64,
            }
            row = {
                "source_id": source_id, "source_row": 4, "grain": "period",
                "business_line": "abroad", "business_group": group,
                "platform": "百度", "company": "Company A",
                "raw_channel": "百度推广", "start_date": "2026-10-01",
                "end_date": "2026-10-07", "amount": amount,
            }
            return {"rows": [row], "sources": [source]}

        expenses.replace_sources(self.connection, period_batch("period-old", "留学整体", 10), "initial")
        expenses.replace_sources(self.connection, period_batch("period-corrected", "新归属", 12), "correction")
        self.assertEqual(self.connection.execute(
            "SELECT count(*), max(business_group), sum(amount) FROM expenses.expense_rows"
        ).fetchone(), (1, "新归属", Decimal("12.00")))

    def test_validation_failure_leaves_existing_batch_untouched(self):
        self.connection.execute('CREATE SCHEMA business')
        self.connection.execute('CREATE TABLE business.updated_business AS SELECT 42 AS orders')
        expenses.replace_sources(self.connection, {
            "rows": [self.row("xhs", "2026-10-01", 12, account_id="account-7")],
            "sources": [self.source("xhs", account_id="account-7")],
        }, "initial")
        invalid = {
            "rows": [
                self.row("xhs", "2026-10-01", 99, account_id="account-7"),
                self.row("missing-source", "2026-10-02", 100, account_id="account-7"),
            ],
            "sources": [self.source("xhs", account_id="account-7")],
        }
        with self.assertRaisesRegex(ValueError, "source metadata missing"):
            expenses.replace_sources(self.connection, invalid, "invalid")
        self.assertEqual(self.connection.execute(
            "SELECT count(*), sum(amount), max(import_id) FROM expenses.expense_rows"
        ).fetchone(), (1, Decimal("12.00"), "initial"))
        self.assertEqual(self.connection.execute('SELECT orders FROM business.updated_business').fetchone()[0],42)

    def test_missing_amount_stays_null_in_daily_view_and_keeps_status(self):
        source = self.source("sem", platform="百度", source_sheet="百度",
                             business_line="abroad", business_group="留学整体",
                             start_date="2026-10-01", end_date="2026-10-01",
                             requested_start_date="2026-10-01", requested_end_date="2026-10-01")
        row = self.row("sem", "2026-10-01", None, platform="百度", source_sheet="百度",
                       business_line="abroad", business_group="留学整体",
                       amount_status="formula_derived_from_blank_consumption")
        expenses.replace_sources(self.connection, {"rows": [row], "sources": [source]}, "sem-import")

        self.assertEqual(self.connection.execute(
            "SELECT spend, row_count, missing_amount_count FROM expenses.daily_spend"
        ).fetchone(), (None, 1, 1))
        self.assertEqual(self.connection.execute(
            "SELECT amount, amount_status FROM expenses.expense_rows"
        ).fetchone(), (None, "formula_derived_from_blank_consumption"))

    def test_latest_source_state_does_not_accumulate_import_versions(self):
        for number in range(3):
            source_id=f'xhs-revision-{number}'
            expenses.replace_sources(self.connection, {
                'rows':[self.row(source_id,'2026-10-01',number,account_id='same-account')],
                'sources':[self.source(source_id,account_id='same-account')],
            },f'import-{number}')
        self.assertEqual(self.connection.execute('SELECT count(*) FROM expenses.expense_sources').fetchone()[0],1)
        self.assertEqual(self.connection.execute('SELECT amount FROM expenses.expense_rows').fetchone()[0],Decimal('2.00'))

    def test_observed_min_max_are_not_proof_of_a_complete_replacement_window(self):
        expenses.replace_sources(self.connection, {
            'rows':[self.row('xhs','2026-10-02',99,account_id='same-account')],
            'sources':[self.source('xhs',account_id='same-account')],
        },'initial')
        expenses.replace_sources(self.connection, {
            'rows':[self.row('xhs','2026-10-01',10,account_id='same-account'),
                    self.row('xhs','2026-10-03',30,account_id='same-account',source_row=3)],
            'sources':[self.source('xhs',account_id='same-account',end_date='2026-10-03')],
        },'partial')
        self.assertEqual(self.connection.execute('SELECT count(*),sum(amount) FROM expenses.expense_rows').fetchone(),(3,Decimal('139.00')))

    def test_verified_complete_account_window_can_remove_an_absent_project(self):
        source=self.source('ocean',platform='抖音',account_id='account-a',requested_start_date='2026-10-01',requested_end_date='2026-10-01')
        rows=[self.row('ocean','2026-10-01',10,platform='抖音',account_id='account-a',project_id=project,
                       placement_type='通投',marketing_scene='短视频',source_row=i+2) for i,project in enumerate(('p1','p2'))]
        expenses.replace_sources(self.connection,{'sources':[source],'rows':rows},'initial')
        expenses.replace_sources(self.connection,{'sources':[{**source,'replacement_window_complete':True}],'rows':[rows[0]]},'complete')
        self.assertEqual(self.connection.execute('SELECT project_id,amount FROM expenses.expense_rows').fetchall(),[('p1',Decimal('10.00'))])

    def test_decimal_storage_sums_cents_without_binary_float_drift(self):
        expenses.replace_sources(self.connection, {
            "rows": [
                self.row("xhs-a", "2026-10-01", 0.1, account_id="account-a"),
                self.row("xhs-b", "2026-10-01", 0.2, account_id="account-b"),
            ],
            "sources": [
                self.source("xhs-a", account_id="account-a"),
                self.source("xhs-b", account_id="account-b"),
            ],
        }, "decimal-import")
        self.assertEqual(self.connection.execute(
            "SELECT sum(amount) FROM expenses.expense_rows"
        ).fetchone()[0], Decimal("0.30"))
        self.assertEqual(self.connection.execute(
            "SELECT typeof(amount) FROM expenses.expense_rows LIMIT 1"
        ).fetchone()[0], "DECIMAL(24,2)")

    def test_manifest_parser_recovers_ocean_natural_key_from_source_row(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            native = root / "ocean.csv"
            native.write_text(
                "项目ID,项目名称,日期,营销场景,投放类型,消耗(元)\n"
                "project-8,项目八,2026-10-01,短视频,通投,35.5\n",
                encoding="utf-8-sig")
            manifest = root / "candidate-sources.json"
            manifest.write_text(json.dumps({"sources": [{
                "source_id": "ocean-run-1", "path": str(native), "kind": "ocean_daily",
                "business_line": "training", "business_group": "大学", "platform": "抖音",
            }]}, ensure_ascii=False))

            parsed = expenses.parse_manifest(manifest)
            self.assertEqual(parsed["rows"][0]["project_id"], "project-8")
            self.assertEqual(parsed["rows"][0]["placement_type"], "通投")
            self.assertEqual(parsed["rows"][0]["marketing_scene"], "短视频")


if __name__ == "__main__":
    unittest.main()
