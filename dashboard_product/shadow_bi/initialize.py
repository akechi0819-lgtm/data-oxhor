"""Create P1 private runtime directories and local credentials once."""
from pathlib import Path
import json,secrets
ROOT=Path(__file__).resolve().parents[2]
R=ROOT/'.local/audits/shadow-bi-p1-20261022/runtime'
R.mkdir(parents=True,exist_ok=True)
(R/'home').mkdir(exist_ok=True)
(R.parent/'evidence').mkdir(exist_ok=True)
p=R/'credentials.json'
if not p.exists():
 p.write_text(json.dumps({'username':'p1_local','password':secrets.token_urlsafe(24),'secret_key':secrets.token_urlsafe(48)}));p.chmod(0o600)
print('P1 runtime initialized; local credentials retained privately')
