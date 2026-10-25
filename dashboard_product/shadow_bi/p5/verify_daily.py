"""将服务器三种语培范围的原生显示与同批受控查询逐项核对。"""
import argparse
import json
from pathlib import Path
import time
from data_platform.business_library import execute_library_query, read_library_result
from dashboard_product.shadow_bi.p3.catalog import AUDIT
from dashboard_product.shadow_bi.p4.verify_server import session, payload, BASE


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    target = Path('/var/lib/shadow-bi/current').resolve()
    library = target/'library'
    manifest = json.loads((library/'library_manifest.json').read_text())
    native = json.loads((AUDIT/'evidence/bootstrap.json').read_text())
    client = session(AUDIT/'runtime/credentials.json')
    version = client.get(BASE+'/p4/version', timeout=30).json()
    assert version['matched'] and version['release'] == target.name
    client.headers['X-Shadow-BI-Release'] = target.name
    checks = []
    for scope in ('被动', '主动', '全部'):
        fields = ["json_extract_string(view,'$.lines.training."+metric+'.'+field+"')"
                  for metric in ('orders', 'cash', 'heads') for field in ('actual', 'prior')]
        receipt = execute_library_query(library=library, batch_id=manifest['batch_id'],
            sql="SELECT "+','.join(fields)+" FROM queries.scoped_team_periods WHERE period_id='FY27' AND team_id='total' AND acquisition_scope=?",
            parameters=[scope], run_id='run_p5_check_'+str(time.time_ns()),
            output_root=AUDIT/'evidence/p5-daily-query')
        expected = read_library_result(receipt, output_root=AUDIT/'evidence/p5-daily-query')['rows'][0]
        filters = [{'col': k, 'op': 'IN', 'val': [v]} for k, v in
                   {'期间': 'FY27', '管理单元': '市场总计', '语培统计范围': scope}.items()]
        response = client.post(BASE+'/api/v1/chart/data', json=payload(
            native['datasets']['native_overview_training'], ['指标', '本期完成', '上年同期'], filters), timeout=120)
        response.raise_for_status()
        rows = response.json()['result'][0]['data']
        mapping = {r['指标']: r for r in rows}
        for i, name in enumerate(('工单', '现金（元）', '人头')):
            for j, field in enumerate(('本期完成', '上年同期')):
                actual = mapping[name][field]
                wanted = expected[2*i+j]
                assert (actual == '—' if wanted is None else abs(float(actual.replace(',', ''))-float(wanted)) < .005)
        checks.append({'scope': scope, 'values': rows, 'expected': expected, 'query_receipt': receipt})
    report = {'status': 'passed', 'release': target.name, 'batch_id': manifest['batch_id'],
              'coverage': manifest['coverage'], 'metrics_compared': 18, 'checks': checks}
    a.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'status': 'passed', 'release': target.name, 'metrics_compared': 18}))


if __name__ == '__main__':
    main()
