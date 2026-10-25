"""同一封存库，对比相关聚合与向量数组拼装的完整学校HTML。"""
import hashlib,json,sys,types,time,os
from pathlib import Path
from jinja2 import Environment
from dashboard_product.shadow_bi.p3.catalog import ROOT,LIBRARY,BATCH,q
from dashboard_product.shadow_bi.p35.native_catalog import native_views
from data_platform.business_library import execute_library_query,read_library_result

def main():
    audit=ROOT/'.local/audits/shadow-bi-p4-20261024';old=types.ModuleType('school_before_html');old.__file__=str(ROOT/'dashboard_product/shadow_bi/p35/native_catalog.py');sys.modules[old.__name__]=old
    exec(compile((audit/'native-catalog-before-html.py').read_text(),old.__file__,'exec'),old.__dict__)
    from dashboard_product.shadow_bi.p35 import breakdown_views
    old_breakdown=types.ModuleType('school_before_breakdown');exec(compile((audit/'breakdown-before-school-prune.py').read_text(),'before-breakdown','exec'),old_breakdown.__dict__)
    current_build=breakdown_views.build;breakdown_views.build=old_breakdown.build
    try:before={v.key:v for v in old.native_views()}
    finally:breakdown_views.build=current_build
    after_views=native_views
    if os.environ.get('P4_NATIVE_CANDIDATE'):
        candidate=types.ModuleType('school_candidate');candidate.__file__=old.__file__;sys.modules[candidate.__name__]=candidate
        exec(compile(Path(os.environ['P4_NATIVE_CANDIDATE']).read_text(),candidate.__file__,'exec'),candidate.__dict__);after_views=candidate.native_views
    after={v.key:v for v in after_views()};checks=[]
    for key in ['native_overview_schools_training','native_overview_schools_abroad','native_virtual_schools_training','native_virtual_schools_abroad','native_prep_schools_training']:
        for scope in ['全部','主动','被动']:
            results=[];seconds=[];receipts=[];digests=[]
            for tag,spec in [('before',before[key]),('after',after[key])]:
                filters={**spec.filters,('学校主被动' if '学校主被动' in spec.filters else '语培统计范围'):scope};removed=set()
                def values(name,remove_filter=False):
                    if remove_filter:removed.add(name)
                    value=filters.get(name,[]);return value if isinstance(value,list) else [value]
                sql=Environment().from_string(spec.sql).render(filter_values=values,columns=['学校表现','排列顺序'],groupby=[])
                clauses=[q(k)+' IN ('+','.join("'"+str(v).replace("'","''")+"'" for v in (value if isinstance(value,list) else [value]))+')' for k,value in filters.items() if k not in removed and value is not None]
                sql=sql.replace('FROM queries.acquisition_facts f','FROM (SELECT * FROM queries.acquisition_facts) f').replace('JOIN queries.periods p','JOIN (SELECT * FROM queries.periods) p')
                sql='SELECT 学校表现,排列顺序 FROM ('+sql+') d'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY 排列顺序'
                started=time.monotonic();r=execute_library_query(library=LIBRARY,batch_id=BATCH,sql=sql,run_id='run_p4_html_'+key+'_'+scope.encode().hex()+'_'+tag,output_root=audit/'html-comparison',max_rows=10000,max_result_bytes=100000000);data=read_library_result(r,output_root=audit/'html-comparison');seconds.append(time.monotonic()-started);results.append(data['rows']);receipts.append(str((audit/'html-comparison'/r['run_id']/r['receipt']['path']).resolve()));digests.append(hashlib.sha256(json.dumps(sorted(row[0] for row in data['rows']),ensure_ascii=False).encode()).hexdigest())
            # ROW_NUMBER对同值学校未定义次序；按完整HTML比对全部节点，另核对名次集合。
            assert sorted(r[0] for r in results[0])==sorted(r[0] for r in results[1]),(key,scope,len(results[0]),len(results[1]))
            # 固定业务线提早过滤后隐藏名次重新从1编号；业务排序仍按父工单，比较排序后的指标序列。
            import xml.etree.ElementTree as ET
            orders=lambda rows:[ET.fromstring(r[0]).findall('./details/summary/span')[2].find('strong').text for r in rows]
            assert orders(results[0])==orders(results[1]),(key,scope,'orders sequence')
            digest=hashlib.sha256(json.dumps(results[0],ensure_ascii=False).encode()).hexdigest();checks.append({'key':key,'scope':scope,'rows':len(results[0]),'sha256':digest,'html_sha256_before':digests[0],'html_sha256_after':digests[1],'receipt_before':receipts[0],'receipt_after':receipts[1],'seconds_before':seconds[0],'seconds_after':seconds[1],'status':'passed'});print(key,scope,len(results[0]),[round(x,3) for x in seconds],flush=True)
    (audit/os.environ.get('P4_COMPARISON_NAME','school-html-comparison.json')).write_text(json.dumps({'checks':checks},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
