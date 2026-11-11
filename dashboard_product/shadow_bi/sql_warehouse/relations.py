"""Load controlled query results/configuration into a new derived warehouse."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def load_rows(con, schema, name, rows, *, columns=None):
    """Staging JSON is ephemeral; source rows are never mutated."""
    con.execute(f'CREATE SCHEMA IF NOT EXISTS {quote(schema)}')
    target = f'{quote(schema)}.{quote(name)}'
    if not rows:
        if not columns:
            raise ValueError(f'empty input needs an explicit schema: {target}')
        con.execute(f'CREATE OR REPLACE TABLE {target} (' + ','.join(
            f'{quote(k)} {v}' for k, v in columns.items()) + ')')
        return
    with tempfile.TemporaryDirectory(prefix='oxhor-sql-') as folder:
        path = Path(folder) / 'rows.jsonl'
        path.write_text(''.join(json.dumps(r, ensure_ascii=False, default=str) + '\n' for r in rows))
        if columns:
            con.execute(f'CREATE OR REPLACE TABLE {target} AS SELECT * FROM read_json(?, columns=?, format=\'newline_delimited\')', [str(path), columns])
        else:
            con.execute(f'CREATE OR REPLACE TABLE {target} AS SELECT * FROM read_json_auto(?, format=\'newline_delimited\', sample_size=-1)', [str(path)])


def records(con, sql, params=None):
    cur = con.execute(sql, params)
    return [dict(zip([c[0] for c in cur.description], row)) for row in cur.fetchall()]
