"""One local activity-input component. No data-write endpoint or DB patch."""
import json,time
from pathlib import Path
from flask import Response,request
from flask_login import login_required
ROOT=Path(__file__).resolve().parents[2]
A=ROOT/'.local/audits/shadow-bi-p1-20261022'

def install(app):
 @app.route('/p1/activity/')
 @login_required
 def activity():
  dataset=json.loads((A/'evidence/bootstrap.json').read_text())['datasets']['activities']
  html=(Path(__file__).with_name('activity.html')).read_text().replace('__ACTIVITY_DATASET_ID__',str(dataset))
  return Response(html,mimetype='text/html')
 @app.after_request
 def audit_chart(response):
  if request.path.rstrip('/') in {'/api/v1/chart/data','/datasource/samples'} and request.method=='POST':
   # Private local evidence only; never capture auth headers/cookies.
   record={'time_ns':time.time_ns(),'path':request.path,'status':response.status_code,'args':request.args.to_dict(),'request':request.get_json(silent=True),'response':response.get_json(silent=True)}
   with (A/'evidence/chart-requests.jsonl').open('a') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
  return response
