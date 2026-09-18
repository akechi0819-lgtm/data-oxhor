from __future__ import annotations
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from data_platform.query.evidence import EvidenceError, file_ref, read_query_result, verify_receipt
from data_platform.query.service import execute_query
from workspace_modeling.delivery import create_delivery, verify_delivery
from tests.platform.test_query_service import warehouse

class EvidenceClosureTests(unittest.TestCase):
    def test_query_tampering_empty_identity_and_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); db=root/'warehouse.duckdb'; warehouse(db)
            def query(sql='SELECT * FROM landing.values_table', **kw):
                return execute_query(warehouse=db,snapshot_id='snapshot_query_test',sql=sql,run_id='run_evidence_test',output_root=root/'Output',**kw)
            a=query(); b=query()
            self.assertNotEqual(a['receipt']['evidence_id'],b['receipt']['evidence_id'])
            self.assertEqual([],read_query_result(query('SELECT 1 WHERE false'),output_root=root/'Output')['rows'])
            for name in ('query.sql','parameters.json','result.json'):
                response=query(); receipt=root/'Output'/response['run_id']/response['receipt']['path']
                (receipt.parent/name).write_text('tampered')
                with self.assertRaises(EvidenceError): read_query_result(response,output_root=root/'Output')
            path=root/'Output'/a['run_id']/a['receipt']['path']; doc=json.loads(path.read_text())
            doc['sql']['path']='../query.sql'; path.write_text(json.dumps(doc))
            with self.assertRaises(EvidenceError): verify_receipt(path)
            output=root/'Else'; output.mkdir(); (output/'run_evidence_test').symlink_to(root/'Output/run_evidence_test',target_is_directory=True)
            with self.assertRaises(EvidenceError): read_query_result(b,output_root=output)
            with self.assertRaises(ValueError): execute_query(warehouse=db,snapshot_id='snapshot_query_test',sql='SELECT 1',run_id='run_evidence_test',output_root=output)

    def test_delivery_rejects_foreign_snapshot_raw_files_and_receipts_as_files(self):
        from tests.test_casebook import CasebookTests
        from tests.evidence_helpers import delivery
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            fixture=CasebookTests(); fixture.setUp(); root=fixture._workspace(Path(d))
            path=delivery(root); doc, _=verify_delivery(path)
            receipt=path.parent/doc['query_refs'][0]['path']
            raw=root/'Input/raw.xlsx'; raw.parent.mkdir(); raw.write_bytes(b'raw workbook')
            db=root/json.loads((root/'Work/workspace.json').read_text())['current_warehouse_path']
            for source in (raw,db):
                with patch('workspace_modeling.casebook.router.guide',return_value={'next_step':'analyze'}):
                    with self.assertRaises(EvidenceError):
                        create_delivery(root=root,output_dir=root/'Output/rejected',run_id='run_rejected',primary_role='operator',query_receipts=[receipt],files=[{'path':source,'media_type':'application/octet-stream'}],producer={'name':'test','version':'1'})
                self.assertFalse((root/'Output/rejected').exists())
            foreign=root/'foreign/warehouse.duckdb'; foreign.parent.mkdir(); warehouse(foreign,'snapshot_current')
            foreign_manifest=foreign.parent/'snapshot_manifest.json'; content=json.loads(foreign_manifest.read_text()); content['different_publisher']='foreign'; foreign_manifest.write_text(json.dumps(content))
            response=execute_query(warehouse=foreign,snapshot_id='snapshot_current',sql='SELECT 1',run_id='run_foreign',output_root=root/'Output')
            report=root/'Output/report.html'
            with patch('workspace_modeling.casebook.router.guide',return_value={'next_step':'analyze'}):
                with self.assertRaises(EvidenceError):
                    create_delivery(root=root,output_dir=root/'Output/rejected',run_id='run_rejected',primary_role='operator',query_receipts=[root/'Output/run_foreign'/response['receipt']['path']],files=[{'path':report,'media_type':'text/html'}],producer={'name':'test','version':'1'})
            doc['files']=[file_ref(receipt,path.parent,'application/json',artifact_id='artifact_forbidden')]
            path.write_text(json.dumps(doc))
            with self.assertRaises(EvidenceError): verify_delivery(path)

    def test_cli_nonfinite_result_is_structured_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); db=root/'warehouse.duckdb'; warehouse(db)
            sql=root/'query.sql'; sql.write_text("SELECT 'NaN'::DOUBLE")
            p=subprocess.run([sys.executable,'-m','interfaces.data_platform','query','--warehouse',str(db),'--snapshot-id','snapshot_query_test','--run-id','run_nonfinite','--output-root',str(root/'Output'),'--sql-file',str(sql)],capture_output=True,text=True)
            self.assertNotEqual(0,p.returncode)
            self.assertEqual('failed',json.loads(p.stdout)['status'])
            self.assertNotIn('Traceback',p.stderr)

    def test_real_cli_capture_html_and_delete_source(self):
        from tests.bridge.test_alignment_wizard import BridgeAlignmentWizardTests
        from tests.fixtures.bridge_alignment.fake_adapter import FakeAdapter
        from workspace_modeling.bridge_alignment.service import start_session, propose_candidates, answer_question, finalize_session
        from workspace_modeling.bridge_alignment.workspace import load_workspace
        from data_platform.query.service import describe_warehouse
        with tempfile.TemporaryDirectory() as d:
            fixture=BridgeAlignmentWizardTests(); fixture.setUp(); root=fixture._workspace(Path(d))
            session='session_evidence_test'; start_session(root=root,session_id=session)
            proposed=propose_candidates(root=root,session_id=session,adapter=FakeAdapter())
            for q in proposed['pending_questions']:
                answer_question(root=root,session_id=session,candidate_key=q['candidate_key'],option_id=q['options'][0]['option_id'],answer_text=q['options'][0]['label'],confirmed_by='synthetic reviewer')
            finalize_session(root=root,session_id=session,bridge_id='bridge_company_fixture',bridge_version='1.0.0')
            _, config=load_workspace(root); db=root/config['current_warehouse_path']; snap=config['current_snapshot_id']
            description=describe_warehouse(warehouse=db,snapshot_id=snap)
            table=next(r for r in description['relations'] if r['schema']=='landing')
            sql_path=root/'query.sql'; sql_path.write_text(f'SELECT count(*) AS n FROM landing."{table["name"]}"')
            completed=subprocess.run([sys.executable,'-m','interfaces.data_platform','query','--warehouse',str(db),'--snapshot-id',snap,'--run-id','run_cli_evidence','--output-root',str(root/'Output'),'--sql-file',str(sql_path)],capture_output=True,text=True)
            self.assertEqual(0,completed.returncode,completed.stdout+completed.stderr)
            response=json.loads(completed.stdout); data=read_query_result(response,output_root=root/'Output')
            report=root/'Output/report.html'; report.write_text(f'<!doctype html><title>合成分析</title><p>记录数：{data["rows"][0][0]}</p>')
            delivery=create_delivery(root=root,output_dir=root/'Output/delivery',run_id='run_analysis_test',primary_role='operator',query_receipts=[root/'Output'/response['run_id']/response['receipt']['path']],files=[{'path':report,'media_type':'text/html'}],producer={'name':'synthetic_report','version':'1.0.0'})
            capture={'schema_version':'casebook_capture.v2','case_id':'case_cli_archive','primary_role':'operator','question_category':'volume','question':'记录多少','normalized_question':'source row count','key_queries':[],'evidence_sources':[{'path':str(delivery.relative_to(root))}],'summary':'合成记录数已验证','created_by':'synthetic reviewer'}
            (root/'capture.json').write_text(json.dumps(capture))
            def cli(*args):
                p=subprocess.run([sys.executable,'-m','interfaces.casebook',*args,'--workspace',str(root)],capture_output=True,text=True)
                self.assertEqual(0,p.returncode,p.stdout+p.stderr); return json.loads(p.stdout)
            cli('case-capture','--manifest','capture.json')
            cli('case-verify','--case-id','case_cli_archive')
            shutil.rmtree(root/'Output'); shutil.rmtree(db.parent)
            cli('case-verify','--case-id','case_cli_archive')
            case=root/'Work/Casebook/candidates/case_cli_archive'
            archived=case/'evidence/delivery_1/delivery.json'; doc=json.loads(archived.read_text()); doc['primary_role']='other'
            archived.write_text(json.dumps(doc)); case_doc=json.loads((case/'case.json').read_text()); case_doc['evidence'][0]['sha256']=file_ref(archived,case,'application/json')['sha256']; (case/'case.json').write_text(json.dumps(case_doc))
            from workspace_modeling.casebook.service import verify_case
            self.assertEqual('failed',verify_case(root=root,case_id='case_cli_archive')['status'])
