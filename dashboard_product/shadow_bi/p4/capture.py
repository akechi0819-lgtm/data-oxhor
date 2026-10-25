"""记录运行中HTTPS入口实际批次、页眉和关键数值，不输出凭据。"""
import argparse,json
from dashboard_product.shadow_bi.p4.verify_server import session,BASE,payload
from dashboard_product.shadow_bi.p3.catalog import AUDIT

def main(name):
    if '/' in name or '..' in name:raise ValueError('仅接受回执名称')
    s=session(AUDIT/'runtime/credentials.json');r=s.get(BASE+'/p4/version',timeout=30);r.raise_for_status();version=r.json()
    b=json.loads((AUDIT/'evidence/bootstrap.json').read_text());n=json.loads((AUDIT.parent/'shadow-bi-p35-20261023/native-bootstrap.json').read_text())
    m=s.get(BASE+'/api/v1/dashboard/'+str(n['dashboard_id']),timeout=30);m.raise_for_status()
    notes=[x.get('meta',{}).get('code','') for x in json.loads(m.json()['result']['position_json']).values() if isinstance(x,dict) and x.get('type')=='MARKDOWN']
    filters=[{'col':k,'op':'IN','val':[v]} for k,v in {'期间':'FY27','管理单元':'市场总计','语培统计范围':'被动'}.items()]
    r=s.post(BASE+'/api/v1/chart/data',json=payload(b['datasets']['native_overview_training'],['指标','本期完成','上年同期'],filters),timeout=120);r.raise_for_status()
    report={'version':version,'page_header':notes,'key_metrics':r.json()['result'][0]['data']}
    (AUDIT/'evidence'/(name+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({'release':version['release'],'matched':version['matched'],'key_metrics':report['key_metrics']},ensure_ascii=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('name');main(p.parse_args().name)
