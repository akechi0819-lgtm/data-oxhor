from copy import deepcopy
from importlib import import_module
import sys
from types import ModuleType, SimpleNamespace

from dashboard_product.shadow_bi.sql_warehouse.catalog import _metadata

_metadata()
bootstrap = import_module('dashboard_product.shadow_bi.p35.bootstrap_native')
configure_overview_student_filter = bootstrap.configure_overview_student_filter


def test_overview_student_filter_patches_only_live_cash_and_personal_charts(monkeypatch):
    keys = {
        'native_overview_training','native_overview_groups',
        'native_overview_cash_lines','native_overview_cash_groups','native_overview_targets',
        'native_overview_grades_training','native_overview_channel_tree_training',
        'native_overview_schools_training','overview_people','native_overview_people',
    }
    base_views=[SimpleNamespace(key='overview_people',page='overview',title='title overview_people')]
    native=[SimpleNamespace(key=key,page='overview',title='title '+key)
            for key in keys-{'overview_people'}]
    contracts={view.key:view for view in [*base_views,*native]}
    monkeypatch.setattr(bootstrap,'VIEWS',base_views)
    monkeypatch.setattr(bootstrap,'native_views',lambda:native)

    class SqlaTable:
        def __init__(self, table_name, database_id, schema, owners):
            self.table_name=table_name;self.database_id=database_id
            self.schema=schema;self.owners=owners;self.id=len(tables)+100
            self.perm=f'{database_id}.{schema}.{table_name}';self.sql='';self.columns=[]

        def fetch_metadata(self):
            self.columns=['新老生']

    class Query:
        def __init__(self):self.criteria={}
        def filter_by(self, **criteria):self.criteria=criteria;return self
        def first(self):
            return next((table for table in tables if all(
                getattr(table,key)==value for key,value in self.criteria.items())),None)
        def all(self):
            return [table for table in tables if all(
                getattr(table,key)==value for key,value in self.criteria.items())]

    class Session:
        def query(self, _model):return Query()
        def add(self, table):
            if table not in tables:tables.append(table)
        def flush(self):pass

    tables=[]
    names={key:'市场总览 · '+contracts[key].title for key in keys}
    for index,name in enumerate(names.values()):
        tables.append(SqlaTable(name,12,'queries',[]))
    grants=[];role=object()

    class SecurityManager:
        def find_role(self, name):
            assert name=='ShadowReaderData';return role
        def find_permission_view_menu(self, *_args):return None
        def add_permission_view_menu(self, permission, view_menu):
            return SimpleNamespace(permission_name=permission,view_menu_name=view_menu)
        def add_permission_role(self, granted_role, permission):grants.append((granted_role,permission))

    superset=ModuleType('superset');superset.__path__=[]
    superset.db=SimpleNamespace(session=Session());superset.security_manager=SecurityManager()
    connectors=ModuleType('superset.connectors');connectors.__path__=[]
    sqla=ModuleType('superset.connectors.sqla');sqla.__path__=[]
    models=ModuleType('superset.connectors.sqla.models');models.SqlaTable=SqlaTable
    for name,module in {'superset':superset,'superset.connectors':connectors,
                        'superset.connectors.sqla':sqla,
                        'superset.connectors.sqla.models':models}.items():
        monkeypatch.setitem(sys.modules,name,module)

    chart_ids={name:index+1 for index,name in enumerate(names)}
    dashboard=SimpleNamespace(
        owners=[object()],
        slices=[SimpleNamespace(id=chart_ids[name],datasource_type='table',datasource_id=table.id)
                for name,table in zip(names,tables)],
    )
    # A separate abroad chart remains outside the student filter.
    dashboard.slices.append(SimpleNamespace(id=999,datasource_type='table',datasource_id=9999))
    positions={'training-tab':{'type':'TAB'},'cash-tab':{'type':'TAB'},
               **{f'chart-{i}':{'type':'CHART','meta':{'chartId':i},
                                'parents':['ROOT_ID','training-tab','cash-tab']}
                  for i in [*chart_ids.values(),999]}}
    metadata={'native_filter_configuration':[
        {'id':'scope','name':'语培统计范围','targets':[{'column':{'name':'语培统计范围'}}]},
        {'id':'existing','name':'期间','targets':[{'column':{'name':'期间'}}]},
    ]}
    original=deepcopy(metadata)

    database=SimpleNamespace(id=12)
    option=configure_overview_student_filter(metadata,positions,dashboard,database)

    assert option.table_name=='p35_overview_student_options'
    assert option.sql=="SELECT unnest(['全部','新生','老生']) AS 新老生"
    assert len(grants)==1 and grants[0][0] is role
    assert metadata['native_filter_configuration'][0]==original['native_filter_configuration'][0]
    assert metadata['native_filter_configuration'][2]==original['native_filter_configuration'][1]
    student=metadata['native_filter_configuration'][1]
    assert student['name']=='新老生'
    assert student['defaultDataMask']['filterState']['value']==['全部']
    assert student['chartsInScope']==sorted(chart_ids.values())
    assert student['scope']['excluded']==[999]
    assert student['tabsInScope']==['cash-tab']
