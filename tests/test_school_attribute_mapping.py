import pytest

from dashboard_product.management.school_attributes import (
    OTHER,
    UNIVERSITY_SCHOOLS,
    attach_school_attributes,
    canonical_university_school,
    school_attribute,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("本地大学", "本地大学"),
        ("本地其他大学", "本地大学"),
        ("归巢大学", "归巢大学"),
        ("国外大学", "国外大学"),
        ("大学已毕业", OTHER),
        ("未确认分类", OTHER),
    ],
)
def test_school_attribute_uses_confirmed_categories(value, expected):
    assert school_attribute(value) == expected


def test_canonical_university_school_matches_all_twelve_confirmed_names():
    expected_schools = (
        "天津师范大学", "天津商业大学", "天津科技大学", "天津财经大学",
        "天津理工大学", "天津美术学院", "天津城建大学", "天津外国语大学",
        "天津大学", "天津工业大学", "南开大学", "河北工业大学",
    )
    assert UNIVERSITY_SCHOOLS == expected_schools
    assert all(canonical_university_school(school) == school for school in expected_schools)


@pytest.mark.parametrize(
    "value",
    [
        "天津师范大学（津南校区）",
        "天津师范大学(津南校区)",
        "天津师范大学（津南校区",
        "天津师范大学津南校区",
        " 天津师范大学 （ 津南 校 区 ） ",
    ],
)
def test_canonical_university_school_accepts_common_campus_suffixes(value):
    assert canonical_university_school(value) == "天津师范大学"


@pytest.mark.parametrize(
    "value",
    [
        "南开大学附属中学",
        "天津大学附属小学",
        "天津大学附属学院",
        "某实验学校天津大学（北洋园校区）",
    ],
)
def test_canonical_university_school_excludes_affiliated_schools_and_unrelated_prefixes(value):
    assert canonical_university_school(value) is None


def test_cash_uses_its_source_row_and_work_orders_require_one_school_mapping():
    source_rows = [
        {"source_row_number": 11, "school_name": "同名大学", "school_attribute": "本地大学"},
        {"source_row_number": 12, "school_name": "同名大学", "school_attribute": "国外大学"},
        {"source_row_number": 21, "school_name": "唯一大学", "school_attribute": "本地其他大学"},
        {"source_row_number": 22, "school_name": "唯一大学", "school_attribute": "本地大学"},
    ]
    training_rows = [
        {"source_row_number": 11, "work_order_id": "C-11", "metric": "passive_reported_cash",
         "actual_value": 120.5, "school_name": "同名大学"},
        {"source_row_number": 12, "work_order_id": "C-12", "metric": "passive_reported_cash",
         "actual_value": -25.0, "school_name": "同名大学"},
        {"source_row_number": 31, "work_order_id": "W-unique", "metric": "work_orders",
         "actual_value": 1.0, "school_name": "唯一大学"},
        {"source_row_number": 32, "work_order_id": "W-conflict", "metric": "work_orders",
         "actual_value": 1.0, "school_name": "同名大学"},
        {"source_row_number": 33, "work_order_id": "W-unmatched", "metric": "work_orders",
         "actual_value": 1.0, "school_name": "未登记大学"},
    ]
    original_rows = [row.copy() for row in training_rows]

    attach_school_attributes(training_rows, source_rows)

    by_row = {row["source_row_number"]: row for row in training_rows}
    assert (by_row[11]["school_attribute"], by_row[11]["school_attribute_status"]) == (
        "本地大学", "现金原行"
    )
    assert (by_row[12]["school_attribute"], by_row[12]["school_attribute_status"]) == (
        "国外大学", "现金原行"
    )
    assert (by_row[31]["school_attribute"], by_row[31]["school_attribute_status"]) == (
        "本地大学", "学校唯一映射"
    )
    assert (by_row[32]["school_attribute"], by_row[32]["school_attribute_status"]) == (
        OTHER, "学校属性冲突"
    )
    assert (by_row[33]["school_attribute"], by_row[33]["school_attribute_status"]) == (
        OTHER, "学校属性未匹配"
    )

    assert len(training_rows) == len(original_rows)
    assert [row["work_order_id"] for row in training_rows if row["metric"] == "work_orders"] == [
        "W-unique", "W-conflict", "W-unmatched"
    ]
    for original, updated in zip(original_rows, training_rows):
        for field in ("source_row_number", "work_order_id", "metric", "actual_value", "school_name"):
            assert updated[field] == original[field]


def test_confirmed_university_overrides_row_mapping_without_rewriting_source_school_name():
    source_school_name = "天津大学（北洋园校区）"
    work_order_school_name = "天津大学(卫津路校区)"
    training_rows = [
        {"source_row_number": 51, "metric": "passive_reported_cash", "actual_value": 125.0,
         "school_name": source_school_name},
        {"source_row_number": 52, "metric": "work_orders", "actual_value": 1.0,
         "school_name": work_order_school_name},
    ]
    source_rows = [
        {"source_row_number": 51, "school_name": source_school_name, "school_attribute": "国外大学"},
    ]

    attach_school_attributes(training_rows, source_rows)

    assert [row["school_attribute"] for row in training_rows] == ["大学*", "大学*"]
    assert [row["channel_school_name"] for row in training_rows] == ["天津大学", "天津大学"]
    assert [row["school_attribute_status"] for row in training_rows] == [
        "重点大学名单", "重点大学名单"
    ]
    assert [row["school_name"] for row in training_rows] == [
        source_school_name, work_order_school_name
    ]
    assert [row["actual_value"] for row in training_rows] == [125.0, 1.0]
