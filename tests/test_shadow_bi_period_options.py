import copy
import json
import sys
from types import ModuleType, SimpleNamespace

import duckdb

from dashboard_product.shadow_bi.p35.bootstrap_native import (
    prep_filter_option_sql,
    prep_period_option_sql,
)
from data_platform.business_library import execute_library_query, read_library_result
from data_platform.query.evidence import file_ref
from dashboard_product.shadow_bi.p35.bootstrap_native import attach_prep_filter_options


def _business_library(tmp_path):
    batch_id = 'run_period_options_fixture'
    library = tmp_path / 'library'
    library.mkdir()
    database = library / 'business.duckdb'
    with duckdb.connect(str(database)) as connection:
        connection.execute('CREATE SCHEMA queries')
        connection.execute('CREATE TABLE queries.batch AS SELECT ? AS batch_id', [batch_id])
        connection.execute('''
            CREATE TABLE queries.scoped_selection_team_periods AS
            SELECT * FROM (VALUES
                ('1', 'FY26', '被动'),
                ('2', 'FY27', '被动'),
                ('4', 'FY27', '被动'),
                ('7', '2026-10', '被动'),
                ('7', '2026-10', '主动')
            ) periods(selection, period_id, acquisition_scope)
        ''')

    manifest = {
        'schema_version': 'business_query_library.v1',
        'batch_id': batch_id,
        'binding': {'inputs': {'fixture': 'a' * 64}, 'rules': {'fixture': 'b' * 64}},
        'snapshots': {'training': 'snapshot_period_options_fixture'},
        'source_queries': [{'snapshot_ref': {'snapshot_id': 'snapshot_period_options_fixture'}}],
        'tables': {'scoped_selection_team_periods': {'rows': 5}},
        'database': file_ref(database, library, 'application/vnd.duckdb'),
    }
    (library / 'library_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return library, batch_id


def _query_option(library, batch_id, sql, name, tmp_path):
    output_root = tmp_path / f'query-output-{name}'
    response = execute_library_query(
        library=library,
        batch_id=batch_id,
        sql=sql,
        run_id=f'run_period_options_{name}',
        output_root=output_root,
    )
    return read_library_result(response, output_root=output_root)


def test_prep_period_options_are_independent_and_read_nonempty_selection_periods(tmp_path):
    library, batch_id = _business_library(tmp_path)
    sql = prep_period_option_sql()
    assert sql == (
        "SELECT DISTINCT period_id AS 期间 FROM queries.scoped_selection_team_periods "
        "WHERE acquisition_scope='被动'"
    )
    assert 'filter_values' not in sql

    result = _query_option(library, batch_id, sql, 'period', tmp_path)

    assert result['columns'] == ['期间']
    assert sorted(row[0] for row in result['rows']) == ['2026-10', 'FY26', 'FY27']


def test_prep_filter_options_return_finite_independent_sql_results(tmp_path):
    library, batch_id = _business_library(tmp_path)
    options = prep_filter_option_sql()

    assert list(options) == ['期间', '月模式', '含删除回收', '含死单']
    assert options['月模式'] == "SELECT unnest(['绩效月','自然月']) AS 月模式"
    assert options['含删除回收'] == "SELECT unnest(['不含','包含']) AS 含删除回收"
    assert options['含死单'] == "SELECT unnest(['不含','包含']) AS 含死单"
    assert all('filter_values' not in sql for sql in options.values())

    expected = {
        '期间': ['2026-10', 'FY26', 'FY27'],
        '月模式': ['绩效月', '自然月'],
        '含删除回收': ['不含', '包含'],
        '含死单': ['不含', '包含'],
    }
    for index, (name, sql) in enumerate(options.items()):
        result = _query_option(library, batch_id, sql, f'filter_{index}', tmp_path)
        assert result['columns'] == [name]
        assert sorted(row[0] for row in result['rows']) == sorted(expected[name])


def test_attach_prep_filter_options_grants_reader_access_and_rebinds_targets(monkeypatch):
    datasets = []
    grants = []
    role = object()
    user = object()

    class SqlaTable:
        def __init__(self, table_name, database_id, schema, owners):
            self.table_name = table_name
            self.database_id = database_id
            self.schema = schema
            self.owners = owners
            self.id = len(datasets) + 101
            self.perm = f'{database_id}.{schema}.{table_name}'
            self.sql = ''
            self.columns = []

        def fetch_metadata(self):
            self.columns = ['metadata-loaded']

    class Query:
        def filter_by(self, **_criteria):
            return self

        def first(self):
            return None

    class Session:
        def query(self, _model):
            return Query()

        def add(self, dataset):
            datasets.append(dataset)

        def flush(self):
            pass

    class SecurityManager:
        def find_role(self, name):
            assert name == 'ShadowReaderData'
            return role

        def find_permission_view_menu(self, permission_name, view_menu_name):
            return None

        def add_permission_view_menu(self, permission_name, view_menu_name):
            return SimpleNamespace(permission_name=permission_name, view_menu_name=view_menu_name)

        def add_permission_role(self, granted_role, permission):
            grants.append((granted_role, permission))

    superset = ModuleType('superset')
    superset.__path__ = []
    superset.db = SimpleNamespace(session=Session())
    superset.security_manager = SecurityManager()
    connectors = ModuleType('superset.connectors')
    connectors.__path__ = []
    sqla = ModuleType('superset.connectors.sqla')
    sqla.__path__ = []
    models = ModuleType('superset.connectors.sqla.models')
    models.SqlaTable = SqlaTable
    for name, module in {
        'superset': superset,
        'superset.connectors': connectors,
        'superset.connectors.sqla': sqla,
        'superset.connectors.sqla.models': models,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    options = prep_filter_option_sql()
    filters = [
        {'id': f'NATIVE_FILTER-p3-prep-{index}', 'targets': [
            {'column': {'name': name}, 'datasetId': -1}
        ]}
        for index, name in enumerate(options)
    ]
    unrelated = [
        {'id': 'NATIVE_FILTER-p3-overview-period', 'targets': [
            {'column': {'name': '期间'}, 'datasetId': 77}
        ]},
        {'id': 'NATIVE_FILTER-p3-prep-extra', 'targets': [
            {'column': {'name': '平台'}, 'datasetId': 88}
        ]},
    ]
    filters.extend(copy.deepcopy(unrelated))
    unrelated_before = copy.deepcopy(unrelated)

    attach_prep_filter_options(filters, database_id=12, user=user)

    assert len(datasets) == len(options) == len(grants) == 4
    dataset_ids = {dataset.table_name: dataset.id for dataset in datasets}
    expected_tables = {
        '期间': 'p35_prep_period_options',
        '月模式': 'p35_prep_control_options_1',
        '含删除回收': 'p35_prep_control_options_2',
        '含死单': 'p35_prep_control_options_3',
    }
    for item, name in zip(filters[:4], options):
        assert item['targets'][0]['datasetId'] == dataset_ids[expected_tables[name]]
    assert filters[4:] == unrelated_before

    granted_permissions = {
        (granted_role, permission.permission_name, permission.view_menu_name)
        for granted_role, permission in grants
    }
    assert granted_permissions == {
        (role, 'datasource_access', dataset.perm) for dataset in datasets
    }
