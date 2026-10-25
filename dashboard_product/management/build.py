"""Build locally from explicit BI and isolated study-abroad Snapshots."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys

from dashboard_product.online_team.build import (
    ROOT, MAPPING, read, write, sha, query, prepare_output, shanghai_today,
    source_label,
)
from dashboard_product.online_team.export import export_site, validate_public_data

HERE = Path(__file__).resolve().parent


def presentation_data(value):
    """Omit absent optional presentation fields; private calculation output stays complete."""
    if isinstance(value, dict):
        return {key: presentation_data(item) for key, item in value.items()
                if item is not None and item != ''}
    if isinstance(value, list):
        return [presentation_data(item) for item in value]
    return value


def write_site_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')


def export_department(out, public, page, team_ids):
    """Package each independently composed board with only its management units."""
    package = out / 'packages' / page
    package.mkdir(parents=True, exist_ok=True)
    data = {**public, 'periods': [{**period, 'teams': [team for team in period['teams'] if team['id'] in team_ids]}
                                for period in public['periods']]}
    data.pop('reconciliation', None)
    data.pop('capacity', None)
    data.pop('activities', None)
    write_site_json(package / 'data.json', data)
    write_site_json(out / 'site' / f'{page}.data.json', data)
    html = (HERE / 'web' / f'{page}.html').read_text(encoding='utf-8')
    html = html.replace('./boards.css', './styles.css').replace('./boards.js', './app.js')
    (package / 'index.html').write_text(html, encoding='utf-8')
    shutil.copy2(out / 'site/boards.css', package / 'styles.css')
    shutil.copy2(out / 'site/boards.js', package / 'app.js')
    return export_site(package, out / f'{page}.html')


def build(args):
    from dashboard_product.management.calculation import calculate
    model = calculate(args)
    out, ws = model['out'], model['workspace']
    public, online_data = model['public'], model['online_data']
    facts, personnel_details = model['facts'], model['personnel_details']
    receipts, diagnostics = model['receipts'], model['diagnostics']
    segments, notifications = model['segments'], model['notifications']
    sources, through = model['sources'], model['through']
    notes = public['metadata']['notes']
    write(out / 'notifications.json', notifications)
    write(out / 'online_shared_result.json', online_data)
    private = {'schema_version': 'management_details.v1', 'metadata': public['metadata'], 'records': facts,
               'personnel_contribution': personnel_details,
               'query_receipts': receipts, 'diagnostics': diagnostics}
    write(out / 'details.json', private)
    write(out / 'shared_result.json', {**public, 'prep_high_selections': segments, 'query_receipts': receipts, 'diagnostics': diagnostics,
        'source_hashes': {source_label(p, ws): sha(p) for p in sources},
        'notifications_ref': {'path': 'notifications.json', 'sha256': sha(out / 'notifications.json')},
        'online_ref': {'path': 'online_shared_result.json', 'sha256': sha(out / 'online_shared_result.json')},
        'details_ref': {'path': 'details.json', 'sha256': sha(out / 'details.json'), 'record_count': len(facts)}})
    write(out / 'reconciliation.json', public['reconciliation'])
    report = ['# P2 同窗对数', '', f'Snapshot：{args.snapshot_id}；截止：{through}', '',
              '| 项目 | 参考值 | 当前值 | 算术差额 | 状态 |', '| --- | ---: | ---: | ---: | --- |']
    report.extend(f"| {r['label']} | {r['baseline']} | {r['current']} | {r['difference']} | {'非同口径，不代表漏单' if r['status'] == 'not_comparable' else '已确认归属调整' if r['status'] == 'confirmed_change' else '待核差异'} |" for r in public['reconciliation']['rows'] if r['status'] != 'matched')
    report.extend(['', *[r['scope_note'] for r in public['reconciliation']['rows'] if r.get('scope_note')]])
    report.extend(['', *public['reconciliation']['notes'], '', *notes])
    (out / 'reconciliation.md').write_text('\n'.join(report)+'\n', encoding='utf-8')
    view_data = presentation_data({key: value for key, value in public.items() if key != 'reconciliation'})
    # 新页的null区分未接入与已接入的真实0；不能沿用其他页省略可选字段的序列化。
    view_data['capacity'] = public['capacity']
    view_data['metadata'].pop('notes', None)
    for period in view_data['periods']:
        period.pop('countries', None)
    site_data = {**view_data, 'periods': [{**period, 'teams': [t for t in period['teams']
                                                            if t['id'] in {'total','virtual','online'}]}
                                        for period in view_data['periods']]}
    write_site_json(out / 'site/data.json', site_data)
    for asset in (HERE / 'web').iterdir():
        if asset.is_file() and asset.suffix in ('.html', '.css', '.js'):
            shutil.copy2(asset, out / 'site' / asset.name)
    nav_js = (HERE / 'web/suite-nav.js').read_text(encoding='utf-8')
    nav_css = (HERE / 'web/suite-nav.css').read_text(encoding='utf-8')
    for name in ('app.js','boards.js'):
        asset = out / 'site' / name
        shared_js = nav_js + '\n' + (HERE / 'web/flat-tables.js').read_text(encoding='utf-8')
        if name == 'app.js': shared_js += '\n' + (HERE / 'web/capacity-view.js').read_text(encoding='utf-8') + '\n' + (HERE / 'web/capacity-radar.js').read_text(encoding='utf-8')
        asset.write_text(shared_js + '\n' + asset.read_text(encoding='utf-8'), encoding='utf-8')
    for name in ('styles.css','boards.css'):
        asset = out / 'site' / name
        extra_css = nav_css + '\n' + (HERE / 'web/flat-tables.css').read_text(encoding='utf-8')
        if name == 'styles.css': extra_css += '\n' + (HERE / 'web/capacity-view.css').read_text(encoding='utf-8') + '\n' + (HERE / 'web/capacity-radar.css').read_text(encoding='utf-8')
        asset.write_text(asset.read_text(encoding='utf-8') + '\n' + extra_css, encoding='utf-8')
    exported = export_site(out / 'site', out / 'index.html')
    departments = [export_department(out, view_data, 'university', {'university'})]
    segment_payloads = {}
    for mask, period_data in segments.items():
        cleaned = presentation_data(period_data)
        for p in cleaned: p.pop('countries', None)
        payload = {'schema_version': view_data['schema_version'], 'metadata': view_data['metadata'], 'periods': cleaned}
        segment_payloads[mask] = payload
        write_site_json(out / 'site' / f'prep_high.{mask}.data.json', payload)
    full_prep = {**segment_payloads['7'], 'selection_views': segment_payloads}
    departments.append(export_department(out, full_prep, 'prep_high', {'prep_high'}))
    # Local multi-file preview loads only the chosen precomputed selection.
    write_site_json(out / 'site/prep_high.data.json', segment_payloads['7'])
    online_dir = out / 'packages/online'
    online_dir.mkdir(parents=True, exist_ok=True)
    online_web = ROOT / 'dashboard_product/online_team/web'
    for asset in ('index.html', 'styles.css', 'app.js'):
        shutil.copy2(online_web / asset, online_dir / asset)
    write_site_json(online_dir / 'data.json', online_data)
    export_site(online_dir, out / 'online.html')
    online_html = (out / 'online.html').read_text(encoding='utf-8')
    online_html = online_html.replace('<body>', '<body data-page="online">', 1)
    online_html = online_html.replace('</head>', '<style>' + nav_css + '</style></head>', 1)
    online_html = online_html.replace('</body>', '<script>' + nav_js + '</script></body>', 1)
    (out / 'site/online.html').write_text(online_html, encoding='utf-8')
    (out / 'online.html').write_text(online_html, encoding='utf-8')
    write(out / 'online_reference.json', {'run_id': args.run_id, 'snapshot_id': args.snapshot_id,
          'data_through': through.isoformat(), 'source': 'same_management_batch', 'sha256': sha(out / 'online.html')})
    return {'status': 'built', 'output_dir': str(out), 'snapshot_id': args.snapshot_id,
            'data_through': through.isoformat(), 'facts': len(facts), 'periods': len(public['periods']),
            'activities': len(public['activities']), 'diagnostics': diagnostics, 'html': exported,
            'department_pages': departments}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', type=Path, default=ROOT / 'customers/bi_operations')
    p.add_argument('--snapshot-id', required=True)
    p.add_argument('--study-abroad-snapshot-id', required=True)
    p.add_argument('--run-id', required=True)
    p.add_argument('--as-of-date')
    print(json.dumps(build(p.parse_args()), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
