import json
from pathlib import Path
from unittest.mock import patch
from data_platform.query.evidence import file_ref

def manifest(path, snapshot_id):
    (path.parent/'snapshot_manifest.json').write_text(json.dumps({'schema_version':'warehouse_snapshot.v2','snapshot_id':snapshot_id,'artifacts':[file_ref(path,path.parent,'application/octet-stream')]}))
