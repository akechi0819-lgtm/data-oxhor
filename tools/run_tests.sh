#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
venv="$repo_root/.venv"

if [ ! -x "$venv/bin/python" ]; then
    echo "Test environment is missing. Run: sh tools/install_runtime.sh test" >&2
    exit 2
fi

exec "$venv/bin/python" -m unittest discover -s "$repo_root/tests" -p 'test_*.py' "$@"
