"""Compile the fixed notification payload from SQL warehouse views."""
from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from typing import Mapping

from .relations import records


HERE = Path(__file__).resolve().parent
_LEDGERS = (
    'personal_orders', 'personal_secondary_orders', 'team_orders',
    'personal_cash', 'team_cash', 'unassigned_cash',
)


def _date_text(value):
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return str(value)[:10] if value is not None else None


def _coverage_from_config(con, config):
    if isinstance(config, Mapping):
        value = config.get('study_abroad_source')
        if value is not None:
            return value
    if config is not None and not isinstance(config, Mapping):
        value = getattr(config, 'study_abroad_source', None)
        if value is not None:
            return value

    relation = con.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema='config' AND table_name='study_abroad_source'
        LIMIT 1
    """).fetchone()
    if relation:
        rows = records(con, 'SELECT * FROM config.study_abroad_source')
        if len(rows) == 1:
            row = rows[0]
            for key in ('source_json', 'coverage_json', 'study_abroad_source'):
                if row.get(key):
                    value = row[key]
                    return json.loads(value) if isinstance(value, str) else value
            return {key: _date_text(value) if key in ('start_date', 'through_date') else value
                    for key, value in row.items()}
    raise ValueError('study_abroad_source coverage is required')


def install_notifications(con):
    """Install session-local SQL views; this adds no persistent warehouse tables."""
    con.execute('CREATE TEMP TABLE IF NOT EXISTS notification_run (through_date DATE, source_json JSON)')
    con.execute((HERE / 'sql' / 'notifications.sql').read_text(encoding='utf-8'))


def compile_notifications(con, config=None, *, through, study_abroad_source=None):
    """Return the legacy ``management_notifications.v1`` payload from SQL views.

    ``business.periods``, ``business.team_metrics``, ``business.personal_metrics``,
    ``business.facts``, ``business.personnel_facts``, and ``config.people`` must
    already be installed. Fact selection, ownership credits, channel summaries,
    period math, targets, and derived notification metrics are SQL-owned.
    """
    through_date = date.fromisoformat(_date_text(through))
    source = (_coverage_from_config(con, config) if study_abroad_source is None
              else study_abroad_source)
    if not isinstance(source, Mapping) or not source.get('start_date') or not source.get('through_date'):
        raise ValueError('study_abroad_source must include start_date and through_date')
    source = dict(source)
    source['start_date'] = _date_text(source['start_date'])
    source['through_date'] = _date_text(source['through_date'])

    install_notifications(con)
    con.execute('DELETE FROM notification_run')
    con.execute('INSERT INTO notification_run VALUES (?, ?)', [through_date, json.dumps(source, ensure_ascii=False)])

    contexts = records(con, 'SELECT * FROM notification_context ORDER BY channel_order')
    if len(contexts) != 8:
        raise ValueError('notification periods are missing; expected all eight channel windows')

    team_metrics = {}
    for row in records(con, 'SELECT channel_id,metric,metric_json FROM notification_team_metric_json'):
        team_metrics.setdefault(row['channel_id'], {})[row['metric']] = json.loads(row['metric_json'])

    people = {}
    for row in records(con, """
        SELECT channel_id,source_person_json,display_json,secondary_json
        FROM notification_person_payloads ORDER BY channel_order,name
    """):
        person = json.loads(row['source_person_json'])
        person.update(json.loads(row['display_json']))
        if row['secondary_json'] is not None:
            person.update(json.loads(row['secondary_json']))
        people.setdefault(row['channel_id'], []).append(person)

    ledgers = {}
    for row in records(con, """
        SELECT channel_id,ledger_name,fact_json FROM notification_ledger_json
        ORDER BY channel_order,ledger_name,CAST(event_date AS DATE),coalesce(work_order_id,''),fact_id
    """):
        ledgers.setdefault(row['channel_id'], {}).setdefault(row['ledger_name'], []).append(json.loads(row['fact_json']))

    channels = {}
    for row in records(con, """
        SELECT s.channel_id,s.name,s.month,
          CASE WHEN c.business_line='abroad' AND NOT(c.through_date BETWEEN c.source_start AND c.source_through)
               THEN NULL ELSE s.today END AS today,
          s.share FROM notification_channel_shares s JOIN notification_context c USING(channel_id)
        ORDER BY c.channel_order,s.month DESC,s.name
    """):
        channels.setdefault(row['channel_id'], []).append({
            'name': row['name'], 'month': row['month'], 'today': row['today'], 'share': row['share'],
        })

    messages = []
    for context in contexts:
        channel_id = context['channel_id']
        message = {
            'id': f"{context['team_id']}.{context['business_line']}",
            'channel_id': context['delivery_channel_id'],
            'business_line': context['business_line'],
            'title': context['title'],
            'month': context['month'],
            'window': {
                'data_through': _date_text(context['through_date']),
                'team_start': _date_text(context['team_start']),
                'team_end': _date_text(context['team_end']),
                'team_through': _date_text(context['natural_through']),
                'team_progress': context['team_progress'],
                'person_month': context['person_month'],
                'person_start': _date_text(context['person_start']),
                'person_end': f"{context['person_month']}-25" if context['person_start'] else None,
                'person_through': _date_text(context['person_through']),
                'person_progress': context['person_progress'],
            },
            'team_metrics': team_metrics.get(channel_id, {}),
            'people': people.get(channel_id, []),
            'channels': channels.get(channel_id, []),
            'ledgers': {name: ledgers.get(channel_id, {}).get(name, []) for name in _LEDGERS},
        }
        if context['personal_only']:
            message['personal_only'] = True
        if context['business_line'] == 'abroad':
            message['source_coverage'] = source
        messages.append(message)

    return {
        'schema_version': 'management_notifications.v1',
        'data_through': through_date.isoformat(),
        'messages': messages,
    }
