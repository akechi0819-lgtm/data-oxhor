#!/usr/bin/env bash
# Source producer: refresh both warehouses once; never publish pages or messages.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
WORKSPACE="${WORKSPACE:?set WORKSPACE to the existing customer workspace}"
PYTHON="${PYTHON:?set PYTHON to the warehouse virtualenv interpreter}"
AS_OF_DATE="${AS_OF_DATE:-$(TZ=Asia/Shanghai date +%F)}"
stamp="$(TZ=Asia/Shanghai date +%H%M%S)"
day="${AS_OF_DATE//-/}"
RUN_ID="${RUN_ID:-run_daily_sources_${day}_${stamp}}"
BI_SNAPSHOT_ID="${BI_SNAPSHOT_ID:-snapshot_bi_operations_${day}_daily_${stamp}}"
STUDY_SNAPSHOT_ID="${STUDY_SNAPSHOT_ID:-snapshot_study_abroad_${day}_daily_${stamp}}"
export PATH="$(dirname "$PYTHON"):$PATH"
cd "$PROJECT_ROOT"
args=(--workspace "$WORKSPACE" --as-of-date "$AS_OF_DATE" --run-id "$RUN_ID"
      --bi-snapshot-id "$BI_SNAPSHOT_ID" --study-snapshot-id "$STUDY_SNAPSHOT_ID")
if [[ -n "${BI_START_DATE:-}" ]]; then args+=(--bi-start-date "$BI_START_DATE"); fi
"$PYTHON" -m data_acquisition.jobs.daily_warehouses "${args[@]}"
