#!/usr/bin/env bash
# Compatibility batch producer for notifications; native BI has its own P5 daily entry.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
WORKSPACE="${WORKSPACE:-${PROJECT_ROOT}/customers/bi_operations}"
PYTHON="${PYTHON:?set PYTHON to the existing warehouse virtualenv interpreter}"
export PATH="$(dirname "$PYTHON"):$PATH"
AS_OF_DATE="${AS_OF_DATE:-$(TZ=Asia/Shanghai date +%F)}"
RUN_ID="${RUN_ID:-run_management_$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)}"
cd "$PROJECT_ROOT"
"$PYTHON" -m data_acquisition.jobs.daily_warehouses check \
  --workspace "$WORKSPACE" --as-of-date "$AS_OF_DATE"
snapshot_id="$("$PYTHON" - "$WORKSPACE/Work/workspace.json" "$AS_OF_DATE" <<'PY'
import json,sys
from datetime import date
from monitoring_product.shared_delivery import _snapshot_cut_date
snapshot=json.load(open(sys.argv[1]))['current_snapshot_id']
if _snapshot_cut_date(snapshot)!=date.fromisoformat(sys.argv[2]):
    raise ValueError('daily dashboard requires the current snapshot to have been refreshed today')
print(snapshot)
PY
)"
study_snapshot_id="$("$PYTHON" - "$WORKSPACE/Work/StudyAbroad/current.json" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['snapshot_id'])
PY
)"
"$PYTHON" -m dashboard_product.management.build --workspace "$WORKSPACE" \
  --snapshot-id "$snapshot_id" --study-abroad-snapshot-id "$study_snapshot_id" \
  --run-id "$RUN_ID" --as-of-date "$AS_OF_DATE"
batch_dir="${WORKSPACE}/Output/DashboardManagement/${RUN_ID}"
shared_result="${batch_dir}/shared_result.json"
"$PYTHON" -m monitoring_product.shared_delivery --shared-result "$shared_result" \
  --output-dir "${batch_dir}/delivery_preview" --as-of-date "$AS_OF_DATE" \
  --state-dir "${WORKSPACE}/Work/DeliveryState" \
  --dashboard-base-url "${DASHBOARD_BASE_URL:-http://dashboard.apinova.cn}" --dry-run
# A fixed, explicit identity pointer, not a directory/time-based result lookup.
"$PYTHON" - "$WORKSPACE" "$shared_result" "$AS_OF_DATE" <<'PY'
import json,sys
from datetime import date,timedelta
from pathlib import Path
from monitoring_product.shared_preview import _read_shared_notifications
from monitoring_product.shared_delivery import _validate_contract,_today_shanghai
from data_acquisition.jobs.daily_warehouses import assert_daily_ready
ws=Path(sys.argv[1]).resolve(); shared=Path(sys.argv[2]).resolve()
body,notifications=_read_shared_notifications(shared)
_validate_contract(body,notifications,sys.argv[3],sending=False)
study=(body['metadata'].get('study_abroad_source') or {}).get('snapshot_id')
if not study:
    raise ValueError('management batch has no study-abroad Snapshot')
assert_daily_ready(ws,sys.argv[3],bi_snapshot_id=body['metadata']['snapshot_id'],study_snapshot_id=study)
as_of=date.fromisoformat(sys.argv[3])
if as_of != _today_shanghai() or body['metadata']['data_through'] != (as_of-timedelta(days=1)).isoformat():
    raise ValueError('daily dashboard requires fresh BI data through yesterday')
pointer=ws/'Work/ManagementDelivery/batch.json'; pointer.parent.mkdir(parents=True,exist_ok=True)
data={k:body['metadata'][k] for k in ('run_id','snapshot_id','data_through')}
data.update(as_of_date=sys.argv[3],shared_result=str(shared.relative_to(ws)))
temporary=pointer.with_suffix('.tmp'); temporary.write_text(json.dumps(data,ensure_ascii=False)+'\n')
temporary.replace(pointer)
PY
if [[ "${ALLOW_LEGACY_STATIC_PUBLISH:-0}" != "1" ]]; then
  echo "Notification batch prepared; legacy static publication retired. Native BI uses shadow_bi.p5.daily."
  exit 0
fi
release_dir="${WORKSPACE}/Output/DashboardRelease/${RUN_ID}"
"$PYTHON" -m dashboard_product.management.publication --shared-result "$shared_result" \
  --output-dir "$release_dir"
SHARED_RESULT="$shared_result" bash "$SCRIPT_DIR/publish_management_dashboard.sh"
manifest_sha="$("$PYTHON" - "$release_dir/manifest.json" <<'PY'
import hashlib,sys
print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())
PY
)"
RELEASE_DIR="$release_dir" MANIFEST_SHA="$manifest_sha" \
  REMOTE_RELEASE_DIR="/var/www/dashboard/releases/${RUN_ID}" \
  REMOTE_NGINX_CONF="${REMOTE_NGINX_CONF:?set the verified server Nginx configuration path}" \
  bash "$SCRIPT_DIR/activate_management_dashboard.sh"
