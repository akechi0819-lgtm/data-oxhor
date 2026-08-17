#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
venv="$repo_root/.venv"
python3 -m venv "$venv"
"$venv/bin/pip" install -e "$repo_root"
"$venv/bin/pip" install -r "$repo_root/tools/s4_ppt_requirements.lock"
"$venv/bin/python" "$repo_root/tools/s4_ppt_preflight.py"
