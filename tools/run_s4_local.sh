#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
venv="$repo_root/.venv"

if [ "$#" -eq 0 ]; then
    echo "usage: tools/run_s4_local.sh COMMAND [ARGS...]" >&2
    echo "       tools/run_s4_local.sh quick-ppt prepare|finalize ..." >&2
    exit 2
fi

if [ "$1" = "quick-ppt" ]; then
    shift
    if [ "$#" -eq 0 ]; then
        echo "usage: tools/run_s4_local.sh quick-ppt prepare|finalize ..." >&2
        exit 2
    fi
    set -- "$repo_root/.venv/bin/python" "$repo_root/tools/s4_ppt_quick.py" "$@"
fi

# Use a minimal environment for local-only data, dependency and PPTX checks.
exec env -i \
    PATH="$venv/bin:/usr/bin:/bin" \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONNOUSERSITE=1 \
    S4_OFFLINE=1 \
    "$@"
