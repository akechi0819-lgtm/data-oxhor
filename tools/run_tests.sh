#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
venv="$repo_root/.venv"

if [ ! -x "$venv/bin/python" ]; then
    echo "Test environment is missing. Run: sh tools/install_runtime.sh test" >&2
    exit 2
fi

"$venv/bin/python" -m unittest discover -s "$repo_root/tests" -t "$repo_root" -p 'test_*.py' "$@"
"$venv/bin/python" -m unittest discover -s "$repo_root/dashboard_product/tests" -p 'test_*.py' "$@"
"$venv/bin/python" -m unittest discover -s "$repo_root/monitoring_product/tests" -p 'test_*.py' "$@"
