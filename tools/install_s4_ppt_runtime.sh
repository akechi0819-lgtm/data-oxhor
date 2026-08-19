#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
venv="$repo_root/.venv"
python3 -m venv "$venv"
"$venv/bin/python" -m pip install -e "$repo_root[full]"
"$venv/bin/python" "$repo_root/tools/s4_ppt_preflight.py"
