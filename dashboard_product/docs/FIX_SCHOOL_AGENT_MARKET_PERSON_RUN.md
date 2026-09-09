# RUN: school-agent market person fix (2026-09-07)

## Verdict
User correct. Use resource-description market-person token, not entry clerk.

## Evidence (orders since 2026-09-01, campaign contains school-agent token)
- market-person token present: ~70/72
- roster hit via market person: ~57/72
- roster hit via entry clerk: ~2/72

## Code
- dashboard_actuals/v6 query.sql: entry_person = regexp_extract(resource description market-person), else entry clerk; manifest sha updated
- refresh.py comment; tests/docs wording

## Verify
- unit tests OK
- refresh run_dashboard_20260907_marketperson_fix: entry_hit 1->48, unassigned 61->13
- published four team booklets

Remaining unassigned: market-person name not in people.json roster.
