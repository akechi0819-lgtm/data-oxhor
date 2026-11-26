import json
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from openpyxl import Workbook

from dashboard_product.shadow_bi.sql_warehouse import expenses
from ops.costs import parse_input, ingest


@pytest.mark.parametrize('suffix', ['csv', 'xlsx', 'json'])
def test_manual_input_missing_and_confirmed_zero(tmp_path, suffix):
    path = tmp_path / ('report.' + suffix)
    rows = [{'日期':'2026-11-23','业务组':'高中','金额':12},
            {'日期':'2026-11-24','业务组':'高中','金额':None}]
    if suffix == 'csv':
        path.write_text('日期,业务组,金额\n2026-11-23,高中,12\n2026-11-24,高中,\n', encoding='utf-8')
    elif suffix == 'json':
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    else:
        wb=Workbook(); sheet=wb.active; sheet.append(list(rows[0]));
        for row in rows: sheet.append(list(row.values()))
        wb.save(path); wb.close()
    con=duckdb.connect()
    ingest(con, path=path, platform='xhs', confirmed_zero=['高中=2026-11-25'], import_id='one')
    assert con.execute('SELECT CAST(start_date AS VARCHAR),amount,amount_status FROM expenses.expense_rows ORDER BY 1').fetchall() == [
        ('2026-11-23',Decimal('12.00'),'reported_value'), ('2026-11-24',None,'missing_amount'),
        ('2026-11-25',Decimal('0.00'),'reported_zero')]
    ingest(con, path=path, platform='xhs', confirmed_zero=['高中=2026-11-25'], import_id='two')
    assert con.execute('SELECT count(*) FROM expenses.expense_rows').fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM expenses.expense_rows WHERE start_date='2026-11-26'").fetchone()[0] == 0
    con.close()


def test_sem_requires_actual_platform_and_scoped_zero(tmp_path):
    path=tmp_path/'input.json'; path.write_text('[]')
    with pytest.raises(ValueError, match='具体平台'):
        parse_input(path, platform='sem', confirmed_zero=['高中=2026-11-25'])
    parsed=parse_input(path, platform='sem', confirmed_zero=['高中/百度=2026-11-25'])
    assert parsed['rows'][0]['platform']=='百度'


def test_reported_total_replaces_native_day_without_touching_other_dates(tmp_path):
    con=duckdb.connect()
    source={'source_id':'x', 'platform':'小红书','grain':'daily','business_line':'training','business_group':'高中','account_id':'a'}
    row={'source_id':'x','source_row':1,'account_id':'a','start_date':'2026-11-23','end_date':'2026-11-23','amount':42}
    expenses.replace_sources(con,{'sources':[source],'rows':[row]},'old')
    path=tmp_path/'input.csv';path.write_text('日期,业务组,金额\n2026-11-23,高中,12\n',encoding='utf-8')
    ingest(con,path=path,platform='xhs',import_id='manual')
    assert con.execute('SELECT amount FROM expenses.expense_rows').fetchall()==[(Decimal('12.00'),)]


def test_reported_day_corrects_existing_report_and_ignores_blank(tmp_path):
    con = duckdb.connect()
    source = {'source_id': 'reported-20261125:高中:腾讯广告', 'source_kind': 'reported_platform_daily',
              'platform': '腾讯广告', 'grain': 'daily', 'business_line': 'training',
              'business_group': '高中'}
    row = {'source_id': source['source_id'], 'source_row': 1, 'business_line': 'training',
           'business_group': '高中', 'platform': '腾讯广告', 'start_date': '2026-11-25',
           'end_date': '2026-11-25', 'amount': Decimal('295.22')}
    expenses.replace_sources(con, {'sources': [source], 'rows': [row]}, 'original')
    path = tmp_path / 'input.csv'
    path.write_text('日期,业务组,金额\n2026-11-25,高中,300.25\n', encoding='utf-8')
    ingest(con, path=path, platform='tencent', import_id='correction')
    ingest(con, path=path, platform='tencent', import_id='retry')
    assert con.execute('SELECT count(*),sum(amount) FROM expenses.expense_rows').fetchone() == (1, Decimal('300.25'))
    path.write_text('日期,业务组,金额\n2026-11-25,高中,\n', encoding='utf-8')
    ingest(con, path=path, platform='tencent', import_id='blank')
    assert con.execute('SELECT count(*),sum(amount) FROM expenses.expense_rows').fetchone() == (1, Decimal('300.25'))


def test_reported_day_rejects_overlapping_period_total(tmp_path):
    con = duckdb.connect()
    source = {'source_id': 'tencent-period', 'source_kind': 'tencent_manual_csv', 'grain': 'period',
              'business_line': 'training', 'business_group': '高中', 'platform': '腾讯广告', 'account_id': '94274565'}
    row = {'source_id': source['source_id'], 'source_row': 1, 'business_line': 'training',
           'business_group': '高中', 'platform': '腾讯广告', 'account_id': '94274565',
           'start_date': '2026-11-01', 'end_date': '2026-11-24', 'amount': Decimal('7322.43')}
    expenses.replace_sources(con, {'sources': [source], 'rows': [row]}, 'period')
    path = tmp_path / 'input.csv'
    path.write_text('日期,业务组,金额\n2026-11-20,高中,12\n', encoding='utf-8')
    with pytest.raises(ValueError, match='期间累计费用重叠'):
        ingest(con, path=path, platform='tencent', import_id='overlap')
    assert con.execute('SELECT count(*),sum(amount) FROM expenses.expense_rows').fetchone() == (1, Decimal('7322.43'))


def test_cost_candidate_clones_identity_and_keeps_business_and_preview(tmp_path):
    from data_platform.query.evidence import file_ref
    from dashboard_product.shadow_bi.sql_warehouse.foundation import TABLES
    from ops.costs import build_cost_candidate
    base=tmp_path/'base';base.mkdir();(base/'source-evidence').mkdir()
    db=base/'warehouse.duckdb'
    with duckdb.connect(str(db)) as con:
        con.execute('CREATE SCHEMA meta; CREATE TABLE meta.identity AS SELECT ? AS batch_id',['base'])
        con.execute('CREATE SCHEMA landing')
        for table in TABLES['training'] + TABLES['abroad']:
            con.execute(f'CREATE TABLE landing."{table}" AS SELECT 123 AS id')
        expenses.install(con)
        con.execute('CREATE VIEW expenses.cost_total AS SELECT sum(amount) AS total FROM expenses.expense_rows')
        con.execute("CREATE SCHEMA business; CREATE VIEW business.update_dates AS SELECT DATE '2026-11-25' training_through, DATE '2026-11-25' abroad_through, (SELECT max(end_date) FROM expenses.expense_rows) expense_through")
    preview={'schema_version':'management_notifications.v1','data_through':'2026-11-25','messages':[{} for _ in range(8)]}
    (base/'notification-preview.json').write_text(json.dumps(preview))
    manifest={'schema_version':'sql_warehouse_candidate.v1','status':'built_unreconciled','published':False,
              'batch_id':'base','snapshots':{'training':'t','abroad':'a'},'as_of_date':'2026-11-26',
              'through_date':'2026-11-25','database':file_ref(db,base,'application/vnd.duckdb'),
              'notification_preview':file_ref(base/'notification-preview.json',base,'application/json'),
              'relations':[{'table_schema':'landing','table_name':table} for table in TABLES['training']+TABLES['abroad']]}
    (base/'candidate.json').write_text(json.dumps(manifest))
    path=tmp_path/'input.csv';path.write_text('日期,业务组,金额\n2026-11-25,高中,12\n',encoding='utf-8')
    candidate=build_cost_candidate(baseline_dir=base,output_dir=tmp_path/'result',costs=parse_input(path,platform='xhs'),batch_id='fees-new')
    assert candidate['batch_id']=='fees-new'
    assert '费用 11.25' in candidate['display_label']
    assert (tmp_path/'result'/'notification-preview.json').read_bytes()==(base/'notification-preview.json').read_bytes()
    with duckdb.connect(str(tmp_path/'result'/'warehouse.duckdb'),read_only=True) as con:
        assert con.execute('SELECT batch_id FROM meta.identity').fetchone()==('fees-new',)
        assert con.execute('SELECT total FROM expenses.cost_total').fetchone()==(Decimal('12.00'),)
        assert con.execute(f'SELECT id FROM landing."{TABLES["training"][0]}"').fetchone()==(123,)
    with duckdb.connect(str(db),read_only=True) as con:
        assert con.execute('SELECT count(*) FROM expenses.expense_rows').fetchone()==(0,)
        assert con.execute('SELECT batch_id FROM meta.identity').fetchone()==('base',)
