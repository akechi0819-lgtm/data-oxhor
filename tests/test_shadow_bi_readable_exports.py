import sys
import types
from io import BytesIO

import pytest

pd = pytest.importorskip('pandas', reason='导出转换测试使用 Superset 运行时的 pandas')
from openpyxl import Workbook, load_workbook

from dashboard_product.shadow_bi.p35 import readable_exports
from dashboard_product.shadow_bi.p35.readable_exports import readable_export_dataframe


def test_html_tree_expands_each_level_and_keeps_numeric_metrics():
    tree = '''<div><details><summary>
      <span>总渠道<span>自然流量</span></span>
      <span><span>现金</span><strong>1,200.00</strong><span>同期 1,000.00 · +20.0%</span>
        <span>占本业务线现金 40.0%</span><span>占本渠道现金 50.0%</span></span>
      <span><span>工单</span><strong>12</strong><span>同期 10 · +20.0%</span><span>占本业务线工单 30.0%</span></span>
      <span><span>人头</span><strong>—</strong><span>同期 — · —</span></span>
    </summary><div role="row">
      <span>学校组</span>
      <span><span>现金</span><strong>—</strong><span>同期 100.00 · -100.0%</span></span>
      <span><span>工单</span><strong>2</strong><span>同期 1 · +100.0%</span></span>
      <span><span>人头</span><strong>1</strong></span>
    </div></details></div>'''
    source = pd.DataFrame([{"学生ID": "000123", "原始计数": 7, "原始比例": 0.25, "渠道表现": tree}])

    result = readable_export_dataframe(source)

    assert result["学生ID"].tolist() == ["000123", "000123"]
    assert result["原始计数"].tolist() == [7, 7]
    assert pd.api.types.is_integer_dtype(result["原始计数"].dtype)
    assert result.loc[0, "原始比例"] == 0.25
    assert result["节点名称"].tolist() == ["总渠道", "学校组"]
    assert result["层级"].tolist() == [0, 1]
    assert result.loc[1, "父级路径"] == "总渠道"
    assert result.loc[0, "现金"] == 1200
    assert result.loc[0, "现金同期"] == 1000
    assert result.loc[0, "现金同比"] == 0.2
    assert result.loc[0, "现金占本业务线"] == 0.4
    assert result.loc[0, "现金占本渠道"] == 0.5
    assert result.loc[0, "人头"] is None or pd.isna(result.loc[0, "人头"])
    assert result.loc[1, "现金"] is None or pd.isna(result.loc[1, "现金"])
    assert result.loc[1, "现金同比"] == -1


def test_nested_school_attribute_and_classification_note_are_exported():
    tree = '''<div><details><summary><span>大学渠道<span>自然流量</span></span></summary>
      <details><summary><span>学校属性<span>公立</span></span></summary>
        <div role="row"><span>示例大学<span>归类说明</span><span>来源字段确认的学校归类</span></span>
          <span><span>现金（元）</span><strong>2,345.50</strong><span>同期 2,000.00 · +17.3%</span><span>占比 12.5%</span></span>
          <span><span>工单</span><strong>—</strong><span>同期 — · —</span></span>
          <span><span>人头</span><strong>4</strong><span>同期 3 · +33.3%</span></span>
        </div>
      </details>
    </details></div>'''
    result = readable_export_dataframe(pd.DataFrame([{"学校表现": tree}]))

    assert result["节点名称"].tolist() == ["大学渠道", "学校属性", "示例大学"]
    leaf = result.iloc[2]
    assert leaf["父级路径"] == "大学渠道 / 学校属性"
    assert pd.isna(leaf["节点属性"])
    assert leaf["归类说明"] == "来源字段确认的学校归类"
    assert leaf["现金"] == 2345.5
    assert leaf["现金同期"] == 2000
    assert round(leaf["现金同比"], 3) == 0.173
    assert leaf["现金占比"] == 0.125
    assert leaf["工单"] is None or pd.isna(leaf["工单"])


def test_json_tree_keeps_json_types_and_maps_classification_note():
    value = '''{"name":"总渠道","cash":123.5,"classification_note":"根节点说明","children":[
      {"name":"学校属性","school_attribute":"公立","schools":[
        {"name":"示例大学","id":"000042","cash":null,"cash_prior":25,"classification_note":"人工确认归类"}
      ]}
    ]}'''
    result = readable_export_dataframe(pd.DataFrame([{"学生ID": "000007", "表现": value}]))

    assert result["学生ID"].tolist() == ["000007"] * 3
    assert result["节点名称"].tolist() == ["总渠道", "学校属性", "示例大学"]
    assert result.loc[1, "节点属性"] == "公立"
    assert result.loc[2, "现金同期"] == 25
    assert pd.isna(result.loc[2, "现金"])
    assert result.loc[2, "归类说明"] == "人工确认归类"
    assert result.loc[2, "id"] == "000042"


def test_json_nested_metric_objects_keep_metric_prefixes():
    value = '''{"name":"渠道A","metrics":{"cash":{"actual":12.5,"prior":10},
      "orders":{"actual":4,"prior":2}}}'''
    result = readable_export_dataframe(pd.DataFrame([{"展示": value}]))

    assert result.loc[0, "现金"] == 12.5
    assert result.loc[0, "现金同期"] == 10
    assert result.loc[0, "工单"] == 4
    assert result.loc[0, "工单同期"] == 2


def test_platform_tree_keeps_composite_fields_and_metric_specific_prior():
    tree = '''<div><details><summary>
      <span>平台A<span>被动</span><span>本期花费 100.00</span></span>
      <span><span>同窗投入 / 收入（元）</span><strong>90.00 / 200.00</strong><span>ROI 2.2 · 单条成本 20.00</span></span>
      <span><span>本期工单 / 现金（元）</span><strong>10 / 300.00</strong><span>工单同期 8 · +25.0%</span><span>现金同期 200 · +50.0%</span></span>
      <span><span>占本业务组工单</span><strong>50.0%</strong><span>截止日新增 2</span><span>同窗工单 10</span></span>
    </summary></details></div>'''
    result = readable_export_dataframe(pd.DataFrame([{"平台投入产出": tree}]))
    row = result.iloc[0]

    assert row["花费"] == 100
    assert row["同窗费用"] == 90
    assert row["同窗收入"] == 200
    assert row["回收倍数"] == 2.2
    assert row["单条工单成本"] == 20
    assert row["工单"] == 10
    assert row["现金"] == 300
    assert row["工单同期"] == 8
    assert row["工单同比"] == 0.25
    assert row["现金同期"] == 200
    assert row["现金同比"] == 0.5
    assert row["工单占比"] == 0.5


def test_country_tree_reads_online_and_offline_pairs_in_one_cell():
    def tree(online, offline):
        return f'''<div><details><summary><span>语培</span>
          <span><span>合计工单</span><strong>100</strong></span>
          <span><span>线上工单</span><strong>{online}</strong><span>线下工单</span><strong>{offline}</strong></span>
          <span><span>待确认工单</span><strong>—</strong></span>
        </summary></details></div>'''

    result = readable_export_dataframe(pd.DataFrame({"条线工单": [tree("30", "10"), tree("—", "8")]}))

    assert result["线上工单"].iloc[0] == 30
    assert result["线下工单"].iloc[0] == 10
    assert pd.isna(result["线上工单"].iloc[1])
    assert result["线下工单"].iloc[1] == 8
    assert pd.isna(result["待确认工单"].iloc[0])


def test_platform_composite_pairs_keep_missing_side_position():
    def tree(investment, operation):
        return f'''<div><details><summary><span>平台A</span>
          <span><span>同窗投入 / 收入（元）</span><strong>{investment}</strong></span>
          <span><span>本期工单 / 现金（元）</span><strong>{operation}</strong></span>
        </summary></details></div>'''

    result = readable_export_dataframe(pd.DataFrame({
        "平台投入产出": [tree("— / 200.00", "— / 300.00"), tree("90.00 / —", "10 / —")],
    }))

    assert pd.isna(result["同窗费用"].iloc[0])
    assert result["同窗收入"].iloc[0] == 200
    assert result["工单"].iloc[0] is None or pd.isna(result["工单"].iloc[0])
    assert result["现金"].iloc[0] == 300
    assert result["同窗费用"].iloc[1] == 90
    assert pd.isna(result["同窗收入"].iloc[1])
    assert result["工单"].iloc[1] == 10
    assert pd.isna(result["现金"].iloc[1])


def test_export_hook_matches_manifest_dataset_id_not_chart_id(monkeypatch):
    manifest_ids = readable_exports._dataset_ids_from_manifest({
        "datasets": {"tree": 302}, "charts": {"tree": 401},
    })
    assert manifest_ids == {"302"}

    superset = types.ModuleType("superset")
    superset.__path__ = []
    common = types.ModuleType("superset.common")
    common.__path__ = []
    chart_data = types.ModuleType("superset.common.chart_data")
    chart_data.ChartDataResultFormat = types.SimpleNamespace(CSV="csv", XLSX="xlsx")
    processor_module = types.ModuleType("superset.common.query_context_processor")

    class Processor:
        def get_data(self, df, coltypes):
            if self._query_context.result_format == "xlsx":
                return b"native-xlsx"
            if hasattr(self, "csv_result"):
                return self.csv_result
            if getattr(self, "capture_csv", False):
                self.received = (df, coltypes)
                return "native-csv"
            return df, coltypes

    processor_module.QueryContextProcessor = Processor
    utils = types.ModuleType("superset.utils")
    utils.__path__ = []
    core = types.ModuleType("superset.utils.core")
    core.extract_dataframe_dtypes = lambda df, datasource: ["numeric"] * len(df.columns)
    for name, module in {
        "superset": superset,
        "superset.common": common,
        "superset.common.chart_data": chart_data,
        "superset.common.query_context_processor": processor_module,
        "superset.utils": utils,
        "superset.utils.core": core,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(readable_exports, "_visible_dataset_ids", lambda: manifest_ids)

    readable_exports.install_readable_exports()
    markup = '<div><details><summary><span>渠道</span></summary><div role="row"><span>学校</span></div></details></div>'

    dataset_query = Processor()
    dataset_query._query_context = types.SimpleNamespace(result_format="csv")
    dataset_query._qc_datasource = types.SimpleNamespace(id=302)
    dataset_query.capture_csv = True
    assert dataset_query.get_data(pd.DataFrame([{"表现": markup}]), []) == "\ufeffnative-csv"
    converted, coltypes = dataset_query.received
    assert converted.loc[0, "节点名称"] == "渠道"
    assert coltypes == ["numeric"] * len(converted.columns)

    chart_query = Processor()
    chart_query._query_context = types.SimpleNamespace(result_format="csv")
    chart_query._qc_datasource = types.SimpleNamespace(id=401)
    original = pd.DataFrame([{"表现": markup}])
    unchanged, _ = chart_query.get_data(original, [])
    assert unchanged is original

    json_query = Processor()
    json_query._query_context = types.SimpleNamespace(result_format="json")
    json_query._qc_datasource = types.SimpleNamespace(id=302)
    unchanged_json, _ = json_query.get_data(original, [])
    assert unchanged_json is original

    csv_query = Processor()
    csv_query._query_context = types.SimpleNamespace(result_format="csv")
    csv_query._qc_datasource = types.SimpleNamespace(id=302)
    csv_query.csv_result = "姓名,金额\n小王,12\n"
    csv_result = csv_query.get_data(pd.DataFrame({"姓名": ["小王"]}), [])
    assert csv_result == "\ufeff姓名,金额\n小王,12\n"
    assert csv_result.count("\ufeff") == 1

    existing_bom_query = Processor()
    existing_bom_query._query_context = types.SimpleNamespace(result_format="csv")
    existing_bom_query._qc_datasource = types.SimpleNamespace(id=302)
    existing_bom_query.csv_result = "\ufeff姓名,金额\n小王,12\n"
    existing_bom_result = existing_bom_query.get_data(pd.DataFrame({"姓名": ["小王"]}), [])
    assert existing_bom_result == "\ufeff姓名,金额\n小王,12\n"
    assert existing_bom_result.count("\ufeff") == 1

    csv_chart_query = Processor()
    csv_chart_query._query_context = types.SimpleNamespace(result_format="csv")
    csv_chart_query._qc_datasource = types.SimpleNamespace(id=401)
    csv_chart_query.csv_result = "姓名\n小王\n"
    assert csv_chart_query.get_data(pd.DataFrame({"姓名": ["小王"]}), []) == "姓名\n小王\n"

    json_result_query = Processor()
    json_result_query._query_context = types.SimpleNamespace(result_format="json")
    json_result_query._qc_datasource = types.SimpleNamespace(id=302)
    json_result_query.csv_result = '{"姓名":"小王"}'
    assert json_result_query.get_data(pd.DataFrame({"姓名": ["小王"]}), []) == '{"姓名":"小王"}'

    formatted = []
    monkeypatch.setattr(readable_exports, "_format_xlsx_export", lambda content: formatted.append(content) or b"styled-xlsx")
    xlsx_query = Processor()
    xlsx_query._query_context = types.SimpleNamespace(result_format="xlsx")
    xlsx_query._qc_datasource = types.SimpleNamespace(id=302)
    plain = pd.DataFrame({"指标": ["现金"], "现金": [12.5]})
    assert xlsx_query.get_data(plain, []) == b"styled-xlsx"
    assert formatted == [b"native-xlsx"]


def test_xlsx_layout_sets_filter_freeze_widths_headers_and_formats():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["说明", "同比", "现金", "工单"])
    sheet.append(["学校属性说明很长很长", 0.125, 1234.5, 1200.5])
    source = BytesIO()
    workbook.save(source)

    result = readable_exports._format_xlsx_export(source.getvalue())
    output = load_workbook(BytesIO(result))
    sheet = output.active

    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:D2"
    assert sheet["A1"].font.bold is True
    assert sheet["A1"].fill.fgColor.rgb.endswith("DCEAF7")
    assert sheet.column_dimensions["A"].width > sheet.column_dimensions["B"].width
    assert sheet.column_dimensions["A"].width <= 48
    assert sheet["B2"].number_format == "0.0%"
    assert sheet["C2"].number_format == "#,##0.00"
    assert sheet["D2"].number_format == "#,##0.##"


def test_plain_table_and_unstructured_strings_are_unchanged():
    source = pd.DataFrame({"学生ID": ["000123"], "人数": [3], "展示说明": ["—"]})

    result = readable_export_dataframe(source)

    assert result is source
    assert result.loc[0, "学生ID"] == "000123"
    assert result.loc[0, "人数"] == 3
    assert result.loc[0, "展示说明"] == "—"


def test_missing_platform_operational_fields_keep_their_columns():
    value = '''<div><div><span>平台</span>
      <span><span>同窗投入 / 收入（元）</span><strong>— / 200.00</strong><span>ROI — · 单条成本 —</span></span>
      <span><span>本期工单 / 现金（元）</span><strong>10 / 300.00</strong></span>
      <span><span>占本业务线工单</span><strong>50.0%</strong><span>截止日新增 —</span><span>同窗工单 —</span></span>
    </div></div>'''
    result = readable_export_dataframe(pd.DataFrame([{'平台投入产出': value}]))
    for field in ('截止日新增', '同窗工单', '回收倍数', '单条工单成本'):
        assert field in result.columns
        assert result.loc[0, field] is None or pd.isna(result.loc[0, field])
