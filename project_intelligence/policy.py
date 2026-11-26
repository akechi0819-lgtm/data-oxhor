"""Explicit publication scope; new files require a reviewed policy change."""
from __future__ import annotations

import re

# Paths are relative to an operator-selected checkout, never supplied by a caller.
DOCUMENTS = (
    'AGENTS.md', 'README.md', 'DEVELOPMENT.md', 'SYNC.md',
    'pyproject.toml',
    'docs/architecture.md', 'docs/maintainer-guide.md',
    'docs/integration-guide.md',
    'docs/monitoring-cloud-deployment.md',
    'docs/project-intelligence.md',
    '.agents/skills/daily-ops/SKILL.md', '.agents/skills/biz-analysis/SKILL.md',
    '.agents/skills/biweekly-report/SKILL.md',
    'market_workspace/AGENTS.md', 'market_workspace/ACCESS.md',
    'market_workspace/INTERFACES.md',
    'dashboard_product/README.md', 'dashboard_product/DEPLOYMENT.md',
    'monitoring_product/README.md',
    'interfaces/data_platform.py',
    'data_platform/query/service.py', 'data_platform/snapshots/ingest.py',
    'data_acquisition/jobs/rebuild_bi_warehouse.py',
    'data_acquisition/jobs/bi_window_merge.py',
    'data_acquisition/connectors/bi/bi_downloads.py',
    'workspace_modeling/operations/personnel.py',
    'dashboard_product/config/saved_queries.json',
    'dashboard_product/management/validation.py',
    'monitoring_product/shared_delivery.py',
    'project_intelligence/policy.py', 'project_intelligence/service.py',
    'project_intelligence/__main__.py',
)
WORKSPACES = {
    'bi_operations': 'customers/shadow_bi_daily',
}
MODULES = {
    'ops': '日更、独立费用、腾讯表同步与状态台账',
    'interfaces': '确定性 CLI 边界',
    'data_acquisition': 'BI 导出、窗口合并和来源接入',
    'data_platform': 'Snapshot、表结构、受控只读查询',
    'workspace_modeling': '共享人员规则',
    'dashboard_product': '固定受控查询、共同计算、看板渲染与静态发布',
    'monitoring_product': '同批结果预览、交付物与已授权投递',
    'market_workspace': '绑定运营工作区的市场工作面',
    'project_intelligence': '本地项目上下文只读服务',
}
SKILLS = ('daily-ops', 'biz-analysis', 'biweekly-report')
# These are documented integrations, not health probes or live task configuration.
INTEGRATIONS = (
    ('bi', 'BI 浏览器导出 / Chrome CDP', 'data_acquisition/connectors/bi/bi_downloads.py', 'code_declared'),
    ('local_host', '本机 DeepSeek Harness', 'docs/architecture.md', 'document_declared'),
    ('grok_cloud', 'Grok 云电脑、外部调度与分层回写', 'SYNC.md', 'document_declared'),
    ('bi_server', '原生 Superset BI、服务器双数仓、共享聚合与固定发布', 'dashboard_product/DEPLOYMENT.md', 'document_declared'),
    ('dingtalk', '同批人员进度通知投递', 'monitoring_product/shared_delivery.py', 'code_declared'),
    ('github', '公开代码仓与私密中转仓', 'SYNC.md', 'document_declared'),
)
MAX_FILE_BYTES = 512_000
MAX_RESPONSE_BYTES = 128_000
MAX_LINES = 160
MAX_LINE_CHARS = 1600
MAX_RESULTS = 50

# Conservative suppression, not a promise to recognize arbitrary unknown secrets.
# Dedicated credential files never enter DOCUMENTS or workspace projections.
SENSITIVE_LINE = re.compile(
    r'(?i)(password|passwd|pwd\b|secret|token|cookie|authorization|'
    r'api[_ -]?key|access[_ -]?key|credential|webhook|private[_ -]?key|'
    r'密码|口令|密钥|登录态|bearer\s|https?://[^\s/]+:[^\s/]+@|'
    r'[?&](?:key|sign|signature|auth)=|\bsk-[a-z0-9_-]{12,}|'
    r'\bgh[pousr]_[a-z0-9]{15,}|\bAKIA[A-Z0-9]{16}|'
    r'\beyJ[a-z0-9_-]+\.[a-z0-9_-]+\.[a-z0-9_-]+)'
)
PRIVATE_KEY = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')


def safe_text(text: str) -> tuple[str, bool]:
    """Suppress sensitive lines and whole multiline secret blocks; retain line numbers."""
    lines = text.splitlines()
    # A multiline value cannot safely be sanitized one line at a time.
    if PRIVATE_KEY.search(text) or any(
        SENSITIVE_LINE.search(line) and (
            '"""' in line or "'''" in line or
            line.rstrip().endswith((':', '>', '\\', '(', '[', '{', '=')) or
            (line.rstrip().endswith('|') and not line.lstrip().startswith('|'))
        )
        for line in lines
    ):
        return '\n'.join('[REDACTED]' for _ in lines), True
    changed = False
    result = []
    for line in lines:
        sensitive = bool(SENSITIVE_LINE.search(line))
        if sensitive:
            result.append('[REDACTED]')
            changed = True
        else:
            # Do not surface local user-home paths from documentation or code.
            clean = re.sub(r'/(?:Users|home)/[^/\s"\x27`]+', '<HOME>', line)
            clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', clean)
            if len(clean) > MAX_LINE_CHARS:
                clean = clean[:MAX_LINE_CHARS] + ' [LINE_TRUNCATED]'
            changed |= clean != line
            result.append(clean)
    return '\n'.join(result), changed
