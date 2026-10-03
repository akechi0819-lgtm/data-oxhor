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
"$venv/bin/python" -B -m unittest discover -s tests -t . -p 'test_*.py' "$@"
"$venv/bin/python" -B -m unittest discover -s dashboard_product/tests -p 'test_*.py' "$@"
"$venv/bin/python" -B -m unittest discover -s monitoring_product/tests -p 'test_*.py' "$@"
