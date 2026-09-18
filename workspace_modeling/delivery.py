"""Explicit analysis delivery packaging; no rendering or discovery."""
from __future__ import annotations
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from data_platform.query.evidence import EvidenceError, guarded, load_json_bytes, encode, file_ref, metadata, resolve_file, snapshot_ref, verify_receipt
from workspace_modeling.bridge_alignment.workspace import load_workspace

def context(root: Path, primary_role: str) -> dict:
    from workspace_modeling.company_bridge.service import load_bridge
    def workspace_file(value):
        path = root / value
        if Path(value).is_absolute() or ".." in Path(value).parts or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise EvidenceError("invalid workspace file")
        return path
    from workspace_modeling.casebook.router import guide
    _, config = load_workspace(root)
    if guide(root=root).get('next_step') != 'analyze':
        raise EvidenceError('workspace Bridge is not ready')
    if config.get('primary_role', primary_role) != primary_role:
        raise EvidenceError('workspace primary role mismatch')
    warehouse = workspace_file(config['current_warehouse_path'])
    bridge = load_bridge(workspace_file(config.get('current_bridge_path') or config['bridge_reference_path']))
    return {'workspace_ref': {'company_id': config['company_id']}, 'primary_role': primary_role,
            'snapshot_id': config['current_snapshot_id'], 'pack_ref': config['pack_ref'],
            'bridge_ref': {k:bridge[k] for k in ('bridge_id','bridge_version')}, 'snapshot_ref': snapshot_ref(warehouse, config['current_snapshot_id'])}

@guarded
def verify_delivery(path: Path, *, expected: dict | None = None) -> tuple[dict, list[Path]]:
    doc = load_json_bytes(path.read_bytes())
    if doc.get('schema_version') != 'business_delivery.v1' or doc.get('kind') != 'analysis':
        raise EvidenceError('unsupported analysis delivery')
    metadata(doc)
    for field, keys in (('workspace_ref', ('company_id',)), ('pack_ref', ('pack_id','pack_version')), ('bridge_ref', ('bridge_id','bridge_version'))):
        value = doc.get(field)
        if not isinstance(value,dict) or any(not isinstance(value.get(k),str) or not value[k] for k in keys):
            raise EvidenceError(f'invalid {field}')
    if not isinstance(doc.get('primary_role'),str) or not doc['primary_role'] or doc.get('metric_refs') != []:
        raise EvidenceError('role required; formal metric bindings are not implemented')
    if expected:
        for k in ('workspace_ref','primary_role','snapshot_id','pack_ref','bridge_ref'):
            if doc[k] != expected[k]:
                raise EvidenceError(f'delivery context mismatch: {k}')
    closure = [path]
    identities = set()
    selected_snapshot = None
    for field, id_key in (('query_refs','evidence_id'),('files','artifact_id')):
        refs = doc.get(field)
        if not isinstance(refs,list) or not refs:
            raise EvidenceError(f'{field} must be nonempty')
        for ref in refs:
            identity = ref.get(id_key)
            if not isinstance(identity,str) or not identity or identity in identities:
                raise EvidenceError('missing or duplicate evidence/artifact identity')
            identities.add(identity)
            target = resolve_file(path.parent, ref)
            closure.append(target)
            if field == 'query_refs':
                receipt, _ = verify_receipt(target)
                if receipt['evidence_id'] != identity or receipt['snapshot_id'] != doc['snapshot_id']:
                    raise EvidenceError('delivery/query identity mismatch')
                if selected_snapshot is not None and receipt['snapshot_ref'] != selected_snapshot:
                    raise EvidenceError('mixed Snapshot manifests')
                selected_snapshot = receipt['snapshot_ref']
                if expected and 'snapshot_ref' in expected and receipt['snapshot_ref'] != expected['snapshot_ref']:
                    raise EvidenceError('query belongs to another Snapshot manifest')
                closure.extend(resolve_file(target.parent, receipt[k]) for k in ('sql','parameters','result'))
            else:
                if target.suffix.lower() in {'.duckdb', '.parquet'} or ref['media_type'] in {'application/vnd.apache.parquet', 'application/x-duckdb'}:
                    raise EvidenceError('warehouse files are not delivery artifacts')
                if target.stat().st_size == 0:
                    raise EvidenceError('empty delivery file')
                if ref.get('media_type') == 'application/json':
                    try:
                        value = load_json_bytes(target.read_bytes())
                    except ValueError:
                        value = None
                    if isinstance(value, dict) and value.get('schema_version') == 'query_receipt.v1':
                        raise EvidenceError('query receipt is not a delivery file')
    if any(not x.resolve().is_relative_to(path.parent.resolve()) for x in closure):
        raise EvidenceError('delivery closure escapes package')
    return doc, list(dict.fromkeys(closure))

def create_delivery(*, root: Path, output_dir: Path, run_id: str, primary_role: str,
                    query_receipts: list[Path], files: list[dict], producer: dict) -> Path:
    """Copy explicit receipts/files; return delivery.json. Files: {path: Path, media_type: str}."""
    root = root.resolve()
    if not output_dir.resolve().is_relative_to(root) or output_dir.exists():
        raise EvidenceError('output package must be a new workspace-local directory')
    current = context(root, primary_role)
    for p in [*query_receipts, *(Path(f['path']) for f in files)]:
        if not p.resolve().is_relative_to(root):
            raise EvidenceError('selected input must be workspace-local')
    for item in files:
        source = Path(item['path']).resolve()
        relative = source.relative_to(root)
        if relative.parts[0] == 'Input' or 'snapshots' in relative.parts or source.suffix.lower() in {'.duckdb', '.parquet'}:
            raise EvidenceError('raw inputs and Snapshot files are not delivery artifacts')
    output_dir.mkdir(parents=True)
    try:
        query_refs = []
        for path in query_receipts:
            receipt, _ = verify_receipt(path)
            if receipt['snapshot_ref'] != current['snapshot_ref']:
                raise EvidenceError('selected query Snapshot mismatch')
            target = output_dir / 'queries' / receipt['evidence_id']
            target.mkdir(parents=True, exist_ok=False)
            for source in [path, *(resolve_file(path.parent,receipt[k]) for k in ('sql','parameters','result'))]:
                dest = target / source.relative_to(path.parent)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
            query_refs.append(file_ref(target / path.name, output_dir, 'application/json', evidence_id=receipt['evidence_id']))
        artifact_refs=[]
        for index, item in enumerate(files):
            source=Path(item['path'])
            dest=output_dir / 'files' / str(index) / source.name
            dest.parent.mkdir(parents=True)
            shutil.copyfile(source,dest)
            artifact_refs.append(file_ref(dest,output_dir,item['media_type'],artifact_id='artifact_'+uuid.uuid4().hex))
        doc={k:v for k,v in current.items() if k != 'snapshot_ref'}
        doc.update(schema_version='business_delivery.v1',kind='analysis',run_id=run_id,created_at=datetime.now(UTC).isoformat(),producer=producer,metric_refs=[],query_refs=query_refs,files=artifact_refs)
        path=output_dir / 'delivery.json'
        path.write_bytes(encode(doc))
        verify_delivery(path,expected=current)
        return path
    except Exception:
        shutil.rmtree(output_dir)
        raise
