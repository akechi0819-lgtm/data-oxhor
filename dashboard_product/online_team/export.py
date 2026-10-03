"""Export the accepted dashboard as one self-contained, allowlisted HTML file."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

def validate_public_data(data):
    if data.get('schema_version') != 'dashboard_rebuild.v1' or not data.get('periods'):
        raise ValueError('unsupported or empty dashboard data')
    metadata = data.get('metadata', {})
    if not all(metadata.get(k) for k in ('snapshot_id', 'data_through', 'run_id')):
        raise ValueError('dashboard data has no explicit identity or cutoff')
    forbidden = {'work_order_id', 'student_id', 'source_row_number', 'resource_description', 'query_receipts', 'details_ref'}
    def visit(value):
        if isinstance(value, dict):
            if forbidden.intersection(value):
                raise ValueError('private detail or evidence fields cannot be published')
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(data)


def export_site(site_dir: Path, output: Path) -> dict:
    site_dir, output = Path(site_dir).resolve(), Path(output).resolve()
    data_bytes = (site_dir / 'data.json').read_bytes()
    data = json.loads(data_bytes)
    validate_public_data(data)
    html = (site_dir / 'index.html').read_text(encoding='utf-8')
    css = (site_dir / 'styles.css').read_text(encoding='utf-8')
    js = (site_dir / 'app.js').read_text(encoding='utf-8')
    css_link = '<link rel="stylesheet" href="./styles.css" />'
    js_link = '<script src="./app.js" defer></script>'
    if html.count(css_link) != 1 or html.count(js_link) != 1 or html.count('</body>') != 1:
        raise ValueError('unexpected static template; refuse partial embedding')
    if '</script' in js.lower() or '</style' in css.lower():
        raise ValueError('asset contains an HTML closing delimiter')
    safe_data = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    safe_data = safe_data.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    html = html.replace(css_link, '<style>\n' + css + '\n</style>').replace(js_link, '')
    embedded = '<script id="dashboard-data" type="application/json">' + safe_data + '</script>\n<script>\n' + js + '\n</script>\n'
    html = html.replace('</body>', embedded + '</body>')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + '.tmp')
    temporary.write_text(html, encoding='utf-8')
    temporary.replace(output)
    return {'status': 'exported', 'file': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
            'size_bytes': output.stat().st_size, 'snapshot_id': data['metadata']['snapshot_id'],
            'data_through': data['metadata']['data_through'], 'run_id': data['metadata']['run_id']}
