import json
from pathlib import Path

import duckdb
import pytest


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "customers/shadow_bi_daily/Work/Bridge/reference.json"
TEAMS = ("初中", "初中国际学科")


def test_project_cash_query_groups_junior_high_in_prep():
    sql = (ROOT / "dashboard_product/management/sql/new_student_cash.sql").read_text()
    with duckdb.connect() as con:
        con.execute("CREATE SCHEMA landing")
        con.execute("""
            CREATE TABLE landing.br_cash__sheet_39b8dee2e4b3 (
                业务日期 VARCHAR, 新老生类型 VARCHAR, 团队 VARCHAR, 报入现金收入 VARCHAR
            )
        """)
        con.executemany(
            "INSERT INTO landing.br_cash__sheet_39b8dee2e4b3 VALUES ('46000', '新生', ?, '100')",
            [(team,) for team in TEAMS],
        )
        rows = con.execute(sql, ["2025-01-01", "2027-01-01"]).fetchall()
    assert [(row[1], row[2], row[3]) for row in rows] == [("新生", "留学预备", 200)]


@pytest.mark.skipif(not BRIDGE.exists(), reason="本机未安装业务工作区")
def test_workspace_cash_and_project_gross_use_confirmed_groups():
    bridge = json.loads(BRIDGE.read_text())
    rules = {rule["key"]: rule["value"] for rule in bridge["overrides"]}
    for team in TEAMS:
        assert rules["cash_business_group_mapping"][team] == "留学预备"
    assert "cash_business_group_mapping" in rules["project_gross_signed_scope"]
