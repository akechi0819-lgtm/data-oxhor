"""从主目录固定Superset环境只读备份P3批次元数据。"""
import json,sqlite3,os
from dashboard_product.shadow_bi.p3.catalog import ROOT,AUDIT

def main():
 runtime=AUDIT/'runtime'
 runtime.mkdir(mode=0o700,exist_ok=False)
 source=ROOT/'.local/runtime/superset'
 # 沿用现有账号；复制库内加密连接URL不再使用，可重新生成批次密钥。
 credential=json.loads((source/'credentials.json').read_text())
 (runtime/'credentials.json').write_text(json.dumps(credential))
 os.chmod(runtime/'credentials.json',0o600)
 with sqlite3.connect('file:'+str(source/'superset.db')+'?mode=ro',uri=True) as src,sqlite3.connect(runtime/'superset.db') as dst:src.backup(dst)
 (runtime/'home').mkdir()
 print('P3 runtime initialized from canonical Superset metadata')
if __name__=='__main__':main()
