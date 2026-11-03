"""Bridge an explicit whole SEM workbook to the existing candidate manifest.

No browser, auth, export, source registration or publication. Historical samples
remain sample_only unless accompanied by an actual collector capture receipt.
"""
import argparse,json,hashlib,shutil
from pathlib import Path
from datetime import date
from openpyxl import load_workbook
from dashboard_product.management.candidate_sources import load_candidate_sources

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stage_sem(native, mapping_manifest, output, *, start, through, capture=None):
 native=Path(native).resolve(strict=True);mapping=Path(mapping_manifest).resolve(strict=True);output=Path(output).absolute()
 if date.fromisoformat(start)>date.fromisoformat(through):raise ValueError('sem_window_reversed')
 entries=[e for e in json.loads(mapping.read_text())['sources'] if e.get('kind')=='sem_daily']
 if len(entries)!=1:raise ValueError('sem_mapping_missing_or_ambiguous')
 entry=entries[0];book=load_workbook(native,read_only=True,data_only=False)
 try:
  names=book.sheetnames
  if not set(entry['sheets'])<=set(names):raise ValueError('sem_mapped_sheet_missing')
 finally:book.close()
 original_hash=sha(native);source=None
 if capture is not None:
  source=json.loads(Path(capture).read_text())
  if source.get('source_id')!='sem' or source.get('status')!='success' or source.get('start_date')!=start or source.get('through_date')!=through or set(source.get('account_ids',[]))!=set(entry['sheets']):raise ValueError('sem_collector_scope_mismatch')
  if not any(Path(f['path']).resolve()==native and f['sha256']==original_hash for f in source.get('files',[])):raise ValueError('sem_collector_file_mismatch')
  collector_proof=source['evidence'];proofpath=Path(collector_proof['path']).resolve(strict=True)
  if sha(proofpath)!=collector_proof['sha256']:raise ValueError('sem_collector_evidence_changed')
 output.mkdir(parents=True,exist_ok=False);copied=output/'native.xlsx';shutil.copyfile(native,copied)
 if sha(copied)!=original_hash:raise ValueError('sem_copy_digest_mismatch')
 manifest=output/'candidate-sources.json';manifest.write_text(json.dumps({'sources':[{**entry,'path':str(copied),'sha256':original_hash,'start_date':start,'end_date':through}]},ensure_ascii=False,indent=2));parsed=load_candidate_sources(manifest)
 info={'source_id':'sem','source_sha256':original_hash,'sheetnames':names,'mapped_sheets':list(entry['sheets']),'rows':len(parsed['rows']),'sample_only':source is None,'start_date':start,'through_date':through,'original_modified':False,'published':False};proof=output/'sample-validation.json';proof.write_text(json.dumps(info,ensure_ascii=False,indent=2))
 if source is None:
  source={'source_id':'sem','status':'sample_only','captured_at':None,'start_date':start,'through_date':through,'account_ids':list(entry['sheets']),'completion':{'complete':False,'through_date':None,'basis':'historical_sample_not_live_capture'},'evidence':{'path':str(proof),'sha256':sha(proof)}}
 else:
  target=output/'collector-evidence.json';shutil.copyfile(proofpath,target)
  if sha(target)!=collector_proof['sha256']:raise ValueError('sem_collector_evidence_changed_during_copy')
  source={**source,'evidence':{'path':str(target),'sha256':sha(target)}}
 source['files']=[{'path':str(copied),'sha256':original_hash}]
 receipt=output/'capture.json';receipt.write_text(json.dumps({'manifest_path':str(manifest),'sources':[source]},ensure_ascii=False,indent=2))
 if sha(native)!=original_hash:raise ValueError('sem_original_changed')
 return {'manifest':str(manifest),'capture':str(receipt),**info}

def load_sem_bundle(receipt):
 receipt=Path(receipt).resolve(strict=True);value=json.loads(receipt.read_text())
 if {s.get('source_id') for s in value.get('sources',[])}!={'sem'}:raise ValueError('sem_receipt_scope_invalid')
 manifest=Path(value['manifest_path']);manifest=manifest if manifest.is_absolute() else receipt.parent/manifest;entries=json.loads(manifest.read_text())['sources']
 if not entries or any(e.get('kind')!='sem_daily' for e in entries):raise ValueError('sem_receipt_manifest_scope_invalid')
 for e in entries:
  p=Path(e['path']);e['path']=str(p if p.is_absolute() else (manifest.parent/p).resolve(strict=True))
 for source in value['sources']:
  for spec in [*source.get('files',[]),source.get('evidence',{})]:
   if 'path' not in spec:raise ValueError('sem_receipt_file_reference_invalid')
   p=Path(spec['path']);spec['path']=str(p.resolve(strict=True) if p.is_absolute() else (receipt.parent/p).resolve(strict=True))
 return entries,value['sources']

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ['native','mapping-manifest','output']:p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--start',required=True);p.add_argument('--through',required=True);p.add_argument('--collector-capture',type=Path);a=p.parse_args();print(json.dumps(stage_sem(a.native,a.mapping_manifest,a.output,start=a.start,through=a.through,capture=a.collector_capture),ensure_ascii=False))
if __name__=='__main__':main()
