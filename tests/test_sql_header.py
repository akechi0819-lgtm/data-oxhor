import os
import subprocess
import sys
import tempfile
from pathlib import Path

from dashboard_product.shadow_bi.sql_warehouse.header import coverage_note, update_date_label


ORIGINAL_COVERAGE_NOTE = (
    '![观近头像](/p3/assets/01-avatar.png) ![观近数据助手](/p3/assets/02-data-tablet.png)\n\n'
    '## 观近 · 市场经营\n\n'
    '语培截至 2026-11-05 · 留学截至 2026-11-05 · 金额单位：元'
)


def test_only_business_and_expense_dates_are_displayed():
    assert update_date_label({'abroad_through':'2026-11-05','training_through':'2026-11-05','expense_through':'2026-11-04'})=='留学 11.5｜语培 11.5｜费用 11.4'


def test_failed_expense_update_can_keep_its_old_date():
    assert update_date_label({'abroad_through':'2026-11-06','training_through':'2026-11-06','expense_through':'2026-11-04'})=='留学 11.6｜语培 11.6｜费用 11.4'


def test_coverage_note_only_inserts_expense_date_before_currency_label():
    dates={'training_through':'2026-11-05','abroad_through':'2026-11-05','expense_through':'2026-11-04'}
    expected=ORIGINAL_COVERAGE_NOTE.replace(
        ' · 金额单位：元',' · 费用截至 2026-11-04 · 金额单位：元',1)
    assert coverage_note(dates)==expected


def test_coverage_note_keeps_missing_expense_unset_without_zero_or_guard():
    base={'training_through':'2026-11-05','abroad_through':'2026-11-05'}
    expected=ORIGINAL_COVERAGE_NOTE.replace(
        ' · 金额单位：元',' · 费用未更新 · 金额单位：元',1)
    assert coverage_note({**base,'expense_through':None})==expected
    assert coverage_note(base)==expected
    assert '费用截至 0' not in expected


def test_coverage_note_import_works_without_shadow_bi_environment_or_current_pointer():
    root=Path(__file__).resolve().parents[1]
    env={key:value for key,value in os.environ.items() if not key.startswith('SHADOW_BI_')}
    env['PYTHONPATH']=str(root)
    script=(
        'import sys; '
        'from dashboard_product.shadow_bi.sql_warehouse.header import coverage_note; '
        "assert coverage_note({'training_through':'2026-11-05','abroad_through':'2026-11-05',"
        "'expense_through':'2026-11-04'}).endswith('费用截至 2026-11-04 · 金额单位：元'); "
        "assert 'dashboard_product.shadow_bi.p3.catalog' not in sys.modules"
    )
    with tempfile.TemporaryDirectory() as empty_cwd:
        result=subprocess.run([sys.executable,'-c',script],cwd=empty_cwd,env=env,
                              capture_output=True,text=True)
    assert result.returncode==0, result.stderr
