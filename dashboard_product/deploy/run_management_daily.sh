#!/usr/bin/env bash
# One management batch for both the static site and the paused/active delivery job.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
WORKSPACE="${WORKSPACE:-${PROJECT_ROOT}/customers/bi_operations}"
PYTHON="${PYTHON:?set PYTHON to the existing warehouse virtualenv interpreter}"
export PATH="$(dirname "$PYTHON"):$PATH"
AS_OF_DATE="${AS_OF_DATE:-$(TZ=Asia/Shanghai date +%F)}"
RUN_ID="${RUN_ID:-run_management_$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)}"
cd "$PROJECT_ROOT"
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
"$PYTHON" -m dashboard_product.management.build --workspace "$WORKSPACE" \
  --snapshot-id "$snapshot_id" --run-id "$RUN_ID" --as-of-date "$AS_OF_DATE"
batch_dir="${WORKSPACE}/Output/DashboardManagement/${RUN_ID}"
shared_result="${batch_dir}/shared_result.json"
"$PYTHON" -m monitoring_product.shared_delivery --shared-result "$shared_result" \
  --output-dir "${batch_dir}/delivery_preview" --as-of-date "$AS_OF_DATE" \
  --state-dir "${WORKSPACE}/Work/DeliveryState" \
  --dashboard-base-url "${DASHBOARD_BASE_URL:-http://dashboard.apinova.cn}" --dry-run
# A fixed, explicit identity pointer, not a directory/time-based result lookup.
"$PYTHON" - "$WORKSPACE" "$shared_result" "$AS_OF_DATE" <<'PY'
import json,sys
from pathlib import Path
from monitoring_product.shared_preview import _read_shared_notifications
from monitoring_product.shared_delivery import _validate_contract
ws=Path(sys.argv[1]).resolve(); shared=Path(sys.argv[2]).resolve()
body,notifications=_read_shared_notifications(shared)
_validate_contract(body,notifications,sys.argv[3],sending=True)
pointer=ws/'Work/ManagementDelivery/batch.json'; pointer.parent.mkdir(parents=True,exist_ok=True)
data={k:body['metadata'][k] for k in ('run_id','snapshot_id','data_through')}
data.update(as_of_date=sys.argv[3],shared_result=str(shared.relative_to(ws)))
temporary=pointer.with_suffix('.tmp'); temporary.write_text(json.dumps(data,ensure_ascii=False)+'\n')
temporary.replace(pointer)
PY
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
