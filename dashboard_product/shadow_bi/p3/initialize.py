"""Create P3-only runtime by consistent read-only backup of local P1 metadata."""
import json,sqlite3,os
from dashboard_product.shadow_bi.p3.catalog import ROOT,AUDIT

def main():
 runtime=AUDIT/'runtime'
 runtime.mkdir(mode=0o700,exist_ok=False)
 source=ROOT/'.local/audits/shadow-bi-p1-20261022/runtime'
 # Keep the P1 login; new secret key is valid because copied encrypted DB URLs are unused.
 credential=json.loads((source/'credentials.json').read_text())
 (runtime/'credentials.json').write_text(json.dumps(credential))
 os.chmod(runtime/'credentials.json',0o600)
 with sqlite3.connect('file:'+str(source/'superset.db')+'?mode=ro',uri=True) as src,sqlite3.connect(runtime/'superset.db') as dst:src.backup(dst)
 (runtime/'home').mkdir()
 print('P3 runtime initialized; P1 unchanged')
if __name__=='__main__':main()
