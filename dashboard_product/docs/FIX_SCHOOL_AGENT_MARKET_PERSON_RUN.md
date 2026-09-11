> 历史施工记录。现行刷新合同是 `dashboard_actuals/v9`，见 [`CURRENT_STATUS.md`](CURRENT_STATUS.md)。

# RUN: school-agent market person fix (2026-09-07)

## Verdict
User correct. Use resource-description market-person token, not entry clerk.

## Evidence (orders since 2026-09-01, campaign contains school-agent token)
- market-person token present: ~70/72
- roster hit via market person: ~57/72
- roster hit via entry clerk: ~2/72

## Code
- 当时 dashboard_actuals/v6 query.sql: entry_person = regexp_extract(resource description market-person), else entry clerk; manifest sha updated。当时刷新是 v7，仍保留该抽取。
- refresh.py comment; tests/docs wording

## Verify
- unit tests OK
- refresh run_dashboard_20260907_marketperson_fix: entry_hit 1->48, unassigned 61->13
- published four team booklets

Remaining unassigned: market-person name not in people.json roster.
