"""正式 SQL release 中可直接导出的看板结果及筛选维度。"""
from .query.service import QueryError

TEAM_METRICS_PRIOR = "上年同期：所选期间开始日至实际截止日分别向前推一年；语培适用，留学及未来期间为 null。"

DATASETS = {
    "periods": ("看板期间、起止日、实际截至日及个人业绩窗口", "period_id kind status"),
    "scopes": ("看板组织范围。total 为市场总计，overview_* 为总览分组", "unit_id"),
    "acquisition_scopes": ("语培主被动和新老生筛选组合", "acquisition_scope"),
    "team_metrics": ("团队经营指标。orders 工单、heads 经营人头、cash 签约现金；actual 当期、prior 上年同期（所选期间开始日至实际截止日分别前移一年；语培适用，留学及未来期间为 null）、target 目标。默认 business_line=training、unit_id=total、acquisition_scope=被动（全部新老生）；对任一默认维度传入 * 可查询该维度全部值；acquisition_scope=全部仅查询“全部”汇总行。使用看板同一期间和组织范围，禁止累加已去重人头。", "period_id unit_id acquisition_scope business_line metric"),
    "team_values": ("团队当期及同期指标和留学、小语种分域人头；可用性以 team_metrics.status 为准", "period_id unit_id acquisition_scope business_line comparison"),
    "dimension_metrics": ("看板渠道、学校、年级及业务组拆解。父级人头应读取对应层级的正式结果", "period_id unit_id acquisition_scope business_line dimension_type dim1 dim2 dim3 metric"),
    "personal_metrics": ("人员业绩，使用个人业绩期间和人员资格", "period_id month_mode state name business_line metric"),
    "scoped_advertising_rollup": ("线上费用及平台产出，保留覆盖状态", "period_id acquisition_scope record_type"),
    "scoped_online_daily": ("线上分日工单、现金和费用", "period_id acquisition_scope business_line"),
    "contribution_capacity": ("按月人员产能和协作贡献", "month state"),
    "radar_axes": ("人员六维雷达及同组基准", "name"),
}


def dataset_catalog(available):
    return {name: {"description": description, "filters": fields.split()}
            for name, (description, fields) in DATASETS.items() if name in available}


def result_query(dataset, filters):
    if dataset not in DATASETS:
        raise QueryError("TABLE_NOT_FOUND", "Unknown dashboard dataset")
    fields = DATASETS[dataset][1].split()
    defaults = {"business_line": "training", "unit_id": "total", "acquisition_scope": "被动"} if dataset == "team_metrics" else {}
    filters = {**defaults, **filters}
    predicates, parameters = [], []
    for field, value in filters.items():
        if field not in fields:
            raise QueryError("INVALID_ARGUMENT", "Unsupported dashboard filter")
        if field in defaults and value == "*":
            continue
        values = value if isinstance(value, list) else [value]
        if not values or not all(isinstance(item, str) and item for item in values):
            raise QueryError("INVALID_ARGUMENT", "Expected nonempty filter values")
        predicates.append(f'"{field}" IN ({", ".join("?" for _ in values)})')
        parameters.extend(values)
    where = " WHERE " + " AND ".join(predicates) if predicates else ""
    return f'SELECT * FROM business."{dataset}"' + where, parameters
