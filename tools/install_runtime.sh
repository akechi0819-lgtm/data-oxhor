#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
profile=${1:-full}
venv="$repo_root/.venv"

case "$profile" in
    core|test|ppt|full) ;;
    *)
        echo "usage: tools/install_runtime.sh [core|test|ppt|full]" >&2
        exit 2
        ;;
esac

python3 -m venv "$venv"
extras="$profile"
if [ "$profile" = "test" ]; then
    extras="test,ppt"
fi
"$venv/bin/python" -m pip install -e "$repo_root[$extras]"

case "$profile" in
    test|ppt|full)
        "$venv/bin/python" "$repo_root/tools/s4_ppt_preflight.py"
        ;;
esac

echo "Installed education-business-analyst[$profile] into $venv"
