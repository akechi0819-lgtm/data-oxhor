#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
profile=${1:-full}
venv="$repo_root/.venv"

case "$profile" in
    core|test|full) ;;
    *)
        echo "usage: tools/install_runtime.sh [core|test|full]" >&2
        exit 2
        ;;
esac

python3 -m venv "$venv"
"$venv/bin/python" -m pip install -e "$repo_root[$profile]"

echo "Installed data-oxhor[$profile] into $venv"
