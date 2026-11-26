"""Generate public and local metric documentation from the approved registry."""
import json
from pathlib import Path


def documents(root: Path):
    registry = json.loads((root / 'config/metrics.yaml').read_text(encoding='utf-8'))
    if registry['schema_version'] != 1:
        raise ValueError('指标注册表版本无效')
    header = '<!-- 由 config/metrics.yaml 生成，使用 ops render-rules 更新。 -->'
    initial = [header, '# ' + registry['heading'], registry['intro']]
    for section in registry['sections']:
        initial.extend(('## ' + section['title'], *section['paragraphs']))
    fields = ('title', 'authority_view', 'evidence_view', 'scope', 'date_field', 'limitation')
    table = '| 指标 | 经营汇总关系 | 明细证据关系 | 默认范围 | 日期 | 限制 |\n'
    table += '| --- | --- | --- | --- | --- | --- |\n'
    for metric in registry['metrics']:
        table += '| ' + ' | '.join(metric[field].replace('|', '\\|') for field in fields) + ' |\n'
    return {
        root / 'business_data_mcp/dashboard_business_rules.md': '\n\n'.join(
            [*initial, '## 指标与证据关系',
             '下列明细证据关系通过本地封存仓入口查询。远程 Business Data MCP 继续使用现有数据集与受控工具。',
             table.rstrip()]) + '\n',
        root / 'docs/metrics-reference.md': '\n\n'.join(
            [header, '# 经营分析指标索引',
             '用 ./oxhor status 查看版本，再以 ./oxhor query --release-id 显式绑定同一封存仓。'
             '需要底层来源明细时使用 --layer raw 与 --snapshot-id。', table.rstrip()]) + '\n',
    }


def render(root: Path, *, check=False) -> None:
    for path, expected in documents(root).items():
        if check:
            if not path.is_file() or path.read_text(encoding='utf-8') != expected:
                raise ValueError(f'生成文档已偏离指标注册表：{path.relative_to(root)}')
        else:
            path.write_text(expected, encoding='utf-8')
