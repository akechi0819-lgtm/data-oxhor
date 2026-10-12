#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
venv="$repo_root/.venv"

if [ ! -x "$venv/bin/python" ]; then
    echo "Test environment is missing. Run: sh tools/install_runtime.sh test" >&2
    exit 2
fi

export PYTHONDONTWRITEBYTECODE=1
cd "$repo_root"
"$venv/bin/python" -B -m pytest tests dashboard_product/tests dashboard_product/management/tests monitoring_product/tests "$@"
