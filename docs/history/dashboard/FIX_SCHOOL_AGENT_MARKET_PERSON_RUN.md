> 历史存档：原路径 `dashboard_product/docs/FIX_SCHOOL_AGENT_MARKET_PERSON_RUN.md`，于 2026-09-18 目录整理时归档。以下状态、命令、版本与凭据配置描述仅代表记录当时，不是当前操作入口。当前项目状态见 [DEVELOPMENT.md](../../archive/DEVELOPMENT-history-202611.md)；看板现行操作见 [DEPLOYMENT.md](../../../dashboard_product/DEPLOYMENT.md)。

# RUN: school-agent market person fix (2026-09-07)

## Verdict
User correct. Use resource-description market-person token, not entry clerk.

## Evidence (orders since 2026-09-01, campaign contains school-agent token)
- market-person token present: ~70/72
- roster hit via market person: ~57/72
- roster hit via entry clerk: ~2/72

## Code
- 当时 dashboard_actuals/v6 query.sql: entry_person = regexp_extract(resource description market-person), else entry clerk; manifest sha updated。现行刷新是 v7，仍保留该抽取。
- refresh.py comment; tests/docs wording

## Verify
- unit tests OK
- refresh run_dashboard_20260907_marketperson_fix: entry_hit 1->48, unassigned 61->13
- published four team booklets

Remaining unassigned: market-person name not in people.json roster.
