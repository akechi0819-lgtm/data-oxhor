"""Adapt the legacy native school tree to flat SQL warehouse relations."""
from __future__ import annotations

import re
from collections.abc import Callable


_SUPPORTED_PAGES = frozenset({'overview', 'virtual', 'prep'})


def _cte_body_bounds(sql: str, name: str) -> tuple[int, int]:
    match = re.search(r'\b' + re.escape(name) + r'\s+AS\s*\(', sql, re.IGNORECASE)
    if match is None:
        raise ValueError(f'legacy school SQL is missing the {name} CTE')
    open_paren = sql.find('(', match.start(), match.end())
    depth = 1
    quote: str | None = None
    index = open_paren + 1
    while index < len(sql):
        char = sql[index]
        next_char = sql[index + 1] if index + 1 < len(sql) else ''
        if quote is not None:
            if char == quote:
                if next_char == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            index += 1
            continue
        if char == '-' and next_char == '-':
            newline = sql.find('\n', index + 2)
            index = len(sql) if newline < 0 else newline + 1
            continue
        if char == '/' and next_char == '*':
            end_comment = sql.find('*/', index + 2)
            if end_comment < 0:
                raise ValueError(f'legacy school SQL has an unterminated comment in {name}')
            index = end_comment + 2
            continue
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                return open_paren + 1, index
        index += 1
    raise ValueError(f'legacy school SQL has an unterminated {name} CTE')


def _replace_cte(sql: str, name: str, body: str) -> str:
    start, end = _cte_body_bounds(sql, name)
    return sql[:start] + body + sql[end:]


def _missing_grades_sql() -> str:
    return """SELECT f.school_name,
          COALESCE(f.grade_name,'年级未归属') AS grade_name,
          SUM(CASE WHEN TRY_CAST(f.event_date AS DATE) BETWEEN p.start_date AND p.through_date
                   THEN f.value ELSE 0 END) AS cash,
          SUM(CASE WHEN TRY_CAST(f.event_date AS DATE) BETWEEN p.prior_start_date AND p.prior_through_date
                   THEN f.value ELSE 0 END) AS prior
          FROM business.facts f
          JOIN (
            SELECT period_id AS id, start_date, through_date,
              CAST(start_date - INTERVAL '1 year' AS DATE) AS prior_start_date,
              CAST(through_date - INTERVAL '1 year' AS DATE) AS prior_through_date
            FROM business.periods
          ) p ON p.id='{{ chosen_period }}'
          WHERE f.business_line='training' AND f.acquisition_mode='主动'
            AND f.metric='cash' AND f.team_id IS NULL
            AND (TRY_CAST(f.event_date AS DATE) BETWEEN p.start_date AND p.through_date
                 OR TRY_CAST(f.event_date AS DATE) BETWEEN p.prior_start_date AND p.prior_through_date)
          GROUP BY f.school_name,f.grade_name"""


def native_school_sql(
    page: str,
    legacy_sql: str,
    school_detail_factory: Callable[[str], str],
) -> str:
    """Keep the legacy school-tree JSON contract while replacing warehouse sources.

    ``school_detail_factory(page)`` supplies the flat school/grade relation used
    by the legacy ``raw`` CTE. It exposes the old raw columns, including parent/
    child metrics, selected ``语培统计范围`` and actual ``节点范围``. For ``prep``
    it also exposes ``业务组``. The factory is owned by catalog code so this
    module has no catalog dependency.
    """
    if page not in _SUPPORTED_PAGES:
        raise ValueError(f'flat school-tree adapter does not support page {page!r}')
    if not isinstance(legacy_sql, str) or not legacy_sql.strip():
        raise ValueError('legacy school SQL must be a non-empty SQL string')
    if not callable(school_detail_factory):
        raise TypeError('school_detail_factory must be callable')

    raw_sql = school_detail_factory(page)
    if not isinstance(raw_sql, str) or not raw_sql.strip():
        raise ValueError(f'school detail factory returned no SQL for {page}')

    adapted = _replace_cte(legacy_sql, 'raw', raw_sql)
    if page != 'overview':
        adapted = _replace_cte(adapted, 'missing_grades', _missing_grades_sql())
    if re.search(r'\bqueries\s*\.', adapted, re.IGNORECASE):
        raise ValueError('adapted school SQL still references queries.*')
    return adapted
