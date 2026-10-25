"""将P4键裁剪前后查询在同一封存库的全默认输出逐值比较。"""
import hashlib,json,sys,tarfile,types
from pathlib import Path
from jinja2 import Environment
from dashboard_product.shadow_bi.p3.catalog import VIEWS,ROOT,LIBRARY,BATCH,q
from data_platform.business_library import execute_library_query,read_library_result

def main():
    audit=ROOT/'.local/audits/shadow-bi-p4-20261024'
    with tarfile.open(audit/'release.tar.gz') as t:source=t.extractfile('code/dashboard_product/shadow_bi/p3/catalog.py').read().decode()
    module=types.ModuleType('p4_original_catalog');module.__file__=str(ROOT/'dashboard_product/shadow_bi/p3/catalog.py');sys.modules[module.__name__]=module;exec(compile(source,module.__file__,'exec'),module.__dict__)
    original={v.key:v for v in module.VIEWS};checks=[]
    def rendered(v):
        removed=set()
        def values(name,remove_filter=False):
            if remove_filter:removed.add(name)
            value=v.filters.get(name,[])
            return value if isinstance(value,list) else [value]
        sql=Environment().from_string(v.sql).render(filter_values=values)
        conditions=[]
        for name,val in v.filters.items():
            if name in removed or val is None:continue
            values_=val if isinstance(val,list) else [val]
            conditions.append(q(name)+' IN ('+','.join("'"+str(x).replace("'","''")+"'" for x in values_)+')')
        return 'SELECT * FROM ('+sql+') checked'+(' WHERE '+' AND '.join(conditions) if conditions else '')
    def digest(data):
        return hashlib.sha256('\n'.join(sorted(json.dumps(dict(zip(data['columns'],row)),sort_keys=True,ensure_ascii=False,default=str) for row in data['rows'])).encode()).hexdigest()
    for v in VIEWS:
        old=original[v.key]
        if old.sql==v.sql:continue
        hashes=[];counts=[]
        for variant,spec in [('before',old),('after',v)]:
            run='run_p4_projection_'+v.key+'_'+variant
            r=execute_library_query(library=LIBRARY,batch_id=BATCH,sql=rendered(spec),run_id=run,output_root=audit/'projection',max_rows=100000,max_result_bytes=100000000)
            d=read_library_result(r,output_root=audit/'projection');hashes.append(digest(d));counts.append(len(d['rows']))
        if hashes[0]!=hashes[1]:raise AssertionError((v.key,counts,hashes))
        checks.append({'key':v.key,'rows':counts[0],'output_sha256':hashes[0],'status':'passed'});print(v.key,counts[0],flush=True)
    (audit/'projection-comparison.json').write_text(json.dumps({'checks':checks,'source':'sealed same batch; all columns and rows at existing default filters'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
