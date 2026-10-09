#!/usr/bin/env bash
# Consume the producer's explicit batch identity; no business query or rebuild.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:?set PROJECT_ROOT to the dashboard source checkout}"
WORKSPACE="${WORKSPACE:-${PROJECT_ROOT}/customers/bi_operations}"
PYTHON="${PYTHON:?set PYTHON to the existing warehouse virtualenv interpreter}"
ENV_FILE="${ENV_FILE:?set ENV_FILE to the existing C-layer credentials file}"
as_of="$(TZ=Asia/Shanghai date +%F)"
cd "$PROJECT_ROOT"
"$PYTHON" -m data_acquisition.jobs.daily_warehouses check \
  --workspace "$WORKSPACE" --as-of-date "$as_of"
shared_result="$("$PYTHON" - "$WORKSPACE" "$as_of" <<'PY'
import json,sys
from pathlib import Path
from monitoring_product.shared_preview import _read_shared_notifications
from data_acquisition.jobs.daily_warehouses import assert_daily_ready
ws=Path(sys.argv[1]).resolve(); batch=json.loads((ws/'Work/ManagementDelivery/batch.json').read_text())
if batch['as_of_date']!=sys.argv[2]:
    raise ValueError('no explicit management batch for today')
shared=(ws/batch['shared_result']).resolve()
if not shared.is_relative_to(ws/'Output/DashboardManagement'):
    raise ValueError('shared result must stay in the management output directory')
body,payload=_read_shared_notifications(shared)
for key in ('run_id','snapshot_id','data_through'):
    if body['metadata'][key]!=batch[key]:
        raise ValueError(f'batch pointer {key} mismatch')
if payload['metadata']['as_of_date']!=batch['as_of_date']:
    raise ValueError('notification as_of_date mismatch')
study=(body['metadata'].get('study_abroad_source') or {}).get('snapshot_id')
if not study:
    raise ValueError('notification batch has no study-abroad Snapshot')
assert_daily_ready(ws,sys.argv[2],bi_snapshot_id=body['metadata']['snapshot_id'],study_snapshot_id=study)
print(shared)
PY
)"
"$PYTHON" -m monitoring_product.shared_delivery --shared-result "$shared_result" \
  --output-dir "$(dirname "$shared_result")/delivery" --as-of-date "$as_of" \
  --state-dir "$WORKSPACE/Work/DeliveryState" --env-file "$ENV_FILE" \
  --dashboard-base-url "${DASHBOARD_BASE_URL:-http://dashboard.apinova.cn}"
