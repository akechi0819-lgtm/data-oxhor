"""Run an actual local command and append its measured exit receipt."""
import argparse
from datetime import datetime,UTC
from pathlib import Path
import subprocess
import json

def main():
    p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,required=True);p.add_argument('--name',required=True);p.add_argument('argv',nargs=argparse.REMAINDER);a=p.parse_args()
    argv=a.argv[1:] if a.argv[:1]==['--'] else a.argv
    root=a.evidence.resolve();root.mkdir(parents=True,exist_ok=True)
    logfile=root/(a.name+'.log')
    if logfile.exists():raise ValueError('拒绝覆盖原命令记录')
    started=datetime.now(UTC).isoformat()
    with logfile.open('w') as f:
        done=subprocess.run(argv,cwd=Path.cwd(),stdout=f,stderr=subprocess.STDOUT)
    receipt={'argv':argv,'cwd':str(Path.cwd()),'started_at':started,'ended_at':datetime.now(UTC).isoformat(),'exit_code':done.returncode,'log':logfile.name}
    with (root/'execution-receipts.jsonl').open('a') as f:f.write(json.dumps(receipt,ensure_ascii=False)+'\n')
    print(json.dumps(receipt,ensure_ascii=False));return done.returncode
if __name__=='__main__':raise SystemExit(main())
