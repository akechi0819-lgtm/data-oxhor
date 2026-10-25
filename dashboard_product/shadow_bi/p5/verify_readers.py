"""使用一名已提供原密码的账号验证只读链路；密码只从stdin读取，不保存。"""
import argparse
import json
from pathlib import Path
import sys
import requests
from dashboard_product.shadow_bi.p4.verify_server import payload, BASE
from dashboard_product.shadow_bi.p3.catalog import AUDIT


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--username', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--password-stdin', action='store_true', required=True)
    a = p.parse_args()
    password = sys.stdin.read()
    client = requests.Session()
    client.trust_env = False
    response = client.post(BASE+'/api/v1/security/login', json={
        'username':a.username,'password':password,'provider':'db','refresh':True},timeout=30)
    response.raise_for_status()
    client.headers['Authorization']='Bearer '+response.json()['access_token']
    client.headers['Referer']=BASE+'/'
    csrf=client.get(BASE+'/api/v1/security/csrf_token/',timeout=30)
    csrf.raise_for_status()
    client.headers['X-CSRFToken']=csrf.json()['result']
    datasets = json.loads((AUDIT/'evidence/bootstrap.json').read_text())['datasets']
    native = json.loads((AUDIT.parent/'shadow-bi-p35-20261023/native-bootstrap.json').read_text())
    results = []
    for username in (a.username,):
        checks = []
        r = client.get(BASE+'/api/v1/dashboard/'+str(native['dashboard_id']), timeout=30)
        r.raise_for_status(); checks.append({'check': 'dashboard-read', 'status': r.status_code})
        filters = [{'col': k, 'op': 'IN', 'val': [v]} for k, v in
                   {'期间': 'FY27', '管理单元': '市场总计', '语培统计范围': '被动'}.items()]
        r = client.post(BASE+'/api/v1/chart/data', json=payload(
            datasets['native_overview_training'], ['指标', '本期完成', '上年同期'], filters), timeout=120)
        r.raise_for_status()
        rows = r.json()['result'][0]['data']
        assert {x['指标'] for x in rows} == {'工单', '现金（元）', '人头'}
        checks.append({'check': 'actual-chart-query', 'status': 200, 'rows': rows})
        r = client.get(BASE+'/api/v1/database/', timeout=30); r.raise_for_status()
        database = r.json()['result'][0]
        assert not database['expose_in_sqllab'] and not database['allow_dml']
        checks.append({'check': 'metadata-no-dml-sqllab', 'status': 'passed'})
        denied_requests = [
            ('sql-lab', 'post', '/api/v1/sqllab/execute/',
             {'database_id': database['id'], 'sql': 'SELECT 42', 'runAsync': False, 'schema': 'queries', 'queryLimit': 1}),
            ('raw-facts', 'post', '/api/v1/chart/data', payload(datasets['facts'], ['工单'])),
            ('dashboard-edit', 'put', '/api/v1/dashboard/'+str(native['dashboard_id']), {}),
            ('database-edit', 'put', '/api/v1/database/'+str(database['id']), {}),
        ]
        for name, method, url, body in denied_requests:
            r = getattr(client, method)(BASE+url, json=body, timeout=30)
            assert r.status_code in (401, 403), (username, name, r.status_code)
            checks.append({'check': 'denied-'+name, 'status': r.status_code})
        results.append({'username': username, 'checks': checks})
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps({'status': 'passed', 'readers': results}, ensure_ascii=False, indent=2))
    print(json.dumps({'status': 'passed', 'readers': len(results), 'checks': sum(len(x['checks']) for x in results)}))


if __name__ == '__main__':
    main()
