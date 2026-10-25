"""分业务线分区及渠道/ROI下钻的真实数据与已保存配置核查。"""
import json
from html import escape
from xml.etree import ElementTree as ET
from dashboard_product.shadow_bi.p3 import verify_api as api
from dashboard_product.shadow_bi.p3.catalog import ROOT,AUDIT
from dashboard_product.shadow_bi.p35.native_catalog import native_views


def check_display(row,source,is_child):
    cells=list(row.findall('span'))
    assert len(cells)==4
    for cell,metric in zip(cells[1:],['现金','工单','人头']):
        text=''.join(cell.itertext())
        def formatted(value,percent=False):
            if value is None:return '—'
            return format(value*100,'.1f')+'%' if percent else format(value,',.2f')
        expected=source.get('分域人数') if metric=='人头' else None
        if not expected:
            expected=formatted(source[metric])
            if metric!='现金' and expected.endswith('.00'):expected=expected[:-3]
        assert cell.find('strong').text==expected,(metric,cell.find('strong').text,expected)
        assert '同期 '+formatted(source[metric+'同期'])+' · '+formatted(source[metric+'同比'],True) in text,(metric,text)
        if metric in ['现金','工单']:
            assert '占本业务线'+metric+' '+formatted(source[metric+'占比'],True) in text,(metric,text)
        if metric=='现金' and is_child:
            assert '占本渠道现金 '+formatted(source['渠道内现金占比'],True) in text,text


def main():
    api.VIEWS+=native_views();c=api.Client();checks=[]
    for page in ['overview','virtual','prep','university']:
        columns=['业务线','渠道','一级渠道','工单','现金','人头','工单同期','工单同比','现金同期','现金同比','人头同期','人头同比','分域人数','工单占比','现金占比']
        parents=c.query(page+'_channels',columns=columns,limit=5000)['data']
        children=c.query(page+'_channels_child',columns=columns+['业务组名称','渠道内现金占比'],limit=5000)['data']
        totals={line:{metric:sum((p[metric] or 0) for p in parents if p['业务线']==line) for metric in ['工单','现金']} for line in {p['业务线'] for p in parents}}
        for source in parents+children:
            for metric in ['工单','现金']:
                denominator=totals[source['业务线']][metric]
                expected=source[metric]/denominator if denominator and source[metric] is not None else None
                actual_share=source[metric+'占比']
                assert (expected is None and actual_share is None) or (expected is not None and actual_share is not None and abs(expected-actual_share)<1e-10),(page,metric,source)
        actual=[]
        for token,line in [('training','语培'),('abroad','留学及小语种')]:
            if page=='prep' and token=='abroad':continue
            rows=c.query('native_'+page+'_channel_tree_'+token,columns=columns+['渠道表现'],limit=5000)['data']
            assert all(r['业务线']==line for r in rows)
            for row in rows:
                identity=lambda r:(r['业务线'],r['渠道'],r['一级渠道'])
                ref=next(p for p in parents if identity(p)==identity(row))
                assert all(ref[k]==row[k] for k in columns)
                details=ET.fromstring(row['渠道表现']).find('details')
                check_display(details.find('summary'),ref,False)
                displayed_children={list(node.findall('span'))[0].text:node for node in details.findall('div')}
                expected_children=[child for child in children if identity(child)==identity(row)]
                assert len(displayed_children)==len(expected_children)
                for child in children:
                    if identity(child)==identity(row):
                        check_display(displayed_children[child['业务组名称']],child,True)
                        if ref['现金'] not in (None,0) and child['现金'] is not None:
                            assert abs(child['渠道内现金占比']-child['现金']/ref['现金'])<1e-10
            actual.extend({k:r[k] for k in columns} for r in rows)
        assert len(actual)==len(parents)
        checks.append({'page':page,'channel_parents':len(parents),'child_rows':len(children),'status':'passed'})
    for page in ['overview','virtual','prep','university']:
        for kind,columns in [('grades',['业务线','年级','工单','现金']),('schools',['业务线','学校','学校树'])]:
            if page=='university' and kind=='schools':continue
            baseline=c.query('native_'+page+'_'+kind,columns=columns,limit=10000)['data']
            combined=[]
            for token,line in [('training','语培'),('abroad','留学及小语种')]:
                if page=='prep' and token=='abroad':continue
                part=c.query('native_'+page+'_'+kind+'_'+token,columns=columns,limit=10000)['data']
                assert all(row['业务线']==line for row in part)
                combined+=part
            encode=lambda rows:sorted(json.dumps(r,sort_keys=True,ensure_ascii=False) for r in rows)
            assert encode(baseline)==encode(combined),(page,kind)
            checks.append({'page':page,'partition':kind,'rows':len(combined),'status':'passed'})
    for page in ['overview','virtual','prep','university']:
        # 原年级源没有heads，不把空投影伪装成已有业务指标。
        data=c.query(page+'_grades',columns=['人头','人头同期','人头同比','分域人数'],limit=10000)['data']
        assert all(all(value is None for value in row.values()) for row in data)
        checks.append({'page':page,'grade_source_heads_not_provided':True,'status':'passed'})
    rows=c.query('native_online_roi_tree',columns=['业务线','花费','回收倍数','单条工单成本','费用与回收'],limit=100)['data']
    original=c.query('online_summary',columns=['业务线','指标','花费','回收倍数','单条工单成本'],limit=100)['data']
    for row in rows:
        ref=next(r for r in original if r['业务线']==row['业务线'] and r['指标']=='现金（元）')
        assert all(row[k]==ref[k] for k in ['花费','回收倍数','单条工单成本'])
        if row['业务线']=='语培':assert all(g in row['费用与回收'] for g in ['高中','留学预备','大学'])
        else:assert '费用未按条线提供' in row['费用与回收']
    proof=json.loads((AUDIT.parent/'shadow-bi-p35-20261023/native-bootstrap.json').read_text())
    positions=proof['position'];overview=positions['TABS-overview']['children'];prep=positions['TABS-prep']['children']
    assert not any(positions[t]['meta']['text']=='高中留学渠道' for t in overview)
    assert any(positions[t]['meta']['text']=='高中留学渠道' for t in prep)
    for key in ['overview_people','prep_people','university_people','virtual_people']:
        chart=proof['charts'][key];r=c.s.get(c.base+'/api/v1/chart/'+str(chart)).json()['result'];p=json.loads(r['params']);assert not set(p['all_columns'])&{'窗口开始','窗口结束','现金状态','人数状态','分域人数'};assert not any(col.endswith('状态') for col in p['all_columns'])
        assert p['column_config']['语培工单']['d3NumberFormat']==',.2~f'
    checks.append({'key':'roi_existing_values_and_qualification','status':'passed'})
    c.save(checks)

if __name__=='__main__':main()
