"""以原查询服务身份核验切换后的五张公开表及分页／导出。"""
import argparse
import json
from pathlib import Path
import uuid

from business_data_mcp.query import BusinessDataQuery, TABLES


def verify(current, result_root, expected_release):
    worker = BusinessDataQuery(Path(current), Path(result_root)/('verify_'+uuid.uuid4().hex),
                               capacity_root=Path(result_root))
    overview = worker.describe(expected_release=expected_release)
    checks = []
    for domain, tables in TABLES.items():
        for table in tables:
            description = worker.describe(domain=domain, table=table['id'], expected_release=expected_release)
            result = worker.query(domain=domain, sql='SELECT COUNT(*) AS row_count FROM '+table['relation'],
                                  expected_release=expected_release, page_size=1)
            page = worker.read_page(result['result_id'], offset=0, limit=1)
            exported = worker.export_csv(result['result_id'], offset=0, limit=1)
            expected_csv = '"row_count"\r\n"'+str(result['rows'][0][0])+'"\r\n'
            if (result['snapshot_id'] != overview['snapshots'][domain] or page['rows'] != result['rows']
                    or not description['table']['columns'] or not exported['complete']
                    or exported['csv_text'] != expected_csv):
                raise ValueError('切换后的公开表查询或导出不一致')
            checks.append({'domain': domain, 'table': table['id'], 'count': result['rows'][0][0],
                           'columns': len(description['table']['columns']), 'snapshot_id': result['snapshot_id']})
    return {'status': 'passed', 'release': expected_release, 'tables': 5, 'checks': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current', type=Path, default=Path('/var/lib/shadow-bi/current'))
    parser.add_argument('--result-root', type=Path, default=Path('/var/lib/business-data-mcp/results'))
    parser.add_argument('--expected-release', required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.current, args.result_root, args.expected_release), ensure_ascii=False))


if __name__ == '__main__':
    main()
