#!/bin/bash
set -euo pipefail
set -a
. /etc/shadow-bi.env
set +a
cd /srv/shadow-bi/raw-code
exec /srv/shadow-bi/venv/bin/python -B -m dashboard_product.shadow_bi.p5.raw_publish
