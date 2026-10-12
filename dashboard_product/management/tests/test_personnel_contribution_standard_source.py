from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from dashboard_product.management.personnel_contribution import (
    build_contribution,
    load_sources,
)


def _rosters(name="留学甲", training=()):
    people = {"teams": ([{
        "team_id": "offline_market",
        "groups": [{"display_name": "大学组", "members": [
            {"display_name": person, "business_group": "大学", "status": "active"}
            for person in training
        ]}],
    }] if training else [])}
    abroad_people = {
        "people": [{"display_name": name, "business_group": "大学", "status": "active"}]
    }
    return people, abroad_people


def _bi_coverage():
    return {
        "orders_start": "2026-06-01",
        "orders_end": "2026-12-31",
        "cash_start": "2026-06-01",
        "cash_end": "2026-12-31",
    }


def _sources(*, resources=(), contracts=(), languages=()):
    return {
        "resources": list(resources),
        "contracts": list(contracts),
        "languages": list(languages),
        "resources_connected": True,
        "source_hashes": {},
    }


def _resource(*, row_number=3, resource_id=None, record_key="sha:resources:3",
              event_date="2026-06-12", owner="留学甲"):
    return {
        "source_row_number": row_number,
        "origin_row_number": row_number,
        "origin_sha256": "a" * 64,
        "origin_filename": "history.xlsx",
        "origin_sheet": "crm",
        "owner": owner,
        "source_owner": owner,
        "date": event_date,
        "event_date": event_date,
        "record_key": record_key,
        "resource_id": resource_id,
        "status": "正常",
        "consultation_type": "留学",
        "market_eligible": "true",
        "_normalized_snapshot_row": True,
    }


def _contract(*, contract_id, amount, amount_status="available", event_date="2026-10-05",
              month="2026-10", row_number=3, record_key="sha:contracts:3"):
    return {
        "source_row_number": row_number,
        "origin_row_number": row_number,
        "origin_sha256": "b" * 64,
        "origin_filename": "history.xlsx",
        "origin_sheet": "留学签约",
        "owner": "留学甲",
        "archive_date": event_date,
        "event_date": event_date,
        "record_key": record_key,
        "contract_id": contract_id,
        "month": month,
        "amount": amount,
        "amount_status": amount_status,
        "_normalized_snapshot_row": True,
    }


def _language(*, amount, event_date="2026-10-05", row_number=3,
              record_key="sha:languages:3", filename="history.xlsx"):
    return {
        "source_row_number": row_number,
        "origin_row_number": row_number,
        "origin_sha256": hashlib.sha256(filename.encode()).hexdigest(),
        "origin_filename": filename,
        "origin_sheet": "语培签约",
        "owner": "留学甲",
        "date": event_date,
        "event_date": event_date,
        "record_key": record_key,
        "resource_id": None,
        "work_order_id": None,
        "student_id": None,
        "amount": amount,
        "amount_status": "available" if amount is not None else "missing",
        "market_eligible": "true",
        "_normalized_snapshot_row": True,
    }


def _build(source_rows, months, training=()):
    people, abroad_people = _rosters(training=training)
    return build_contribution(
        [], [], people, abroad_people, source_rows, months, _bi_coverage(),
    )


def _person_rows(result, month):
    period = next(row for row in result["periods"] if row["id"] == month)
    return period, {row["name"]: row for row in period["people"]}


def test_snapshot_marker_rows_load_without_any_legacy_flow_input(tmp_path: Path) -> None:
    hash_path = tmp_path / "snapshot-source.json"
    hash_path.write_text("immutable snapshot source", encoding="utf-8")
    source_hashes = {str(hash_path): hashlib.sha256(hash_path.read_bytes()).hexdigest()}
    marker_row = _resource(event_date="2026-06-12", resource_id="1001", owner="留学甲")
    marker_row.update({
        "source_owner": "语培甲", "market_group": "国际市场",
        "segment_id": "international_market",
    })
    normalized_source = {
        "tables": {
            "resources": [marker_row],
            "contracts": [_contract(contract_id="C-1", amount="200", event_date="2026-06-13", month="2026-06")],
            "languages": [_language(amount="75", event_date="2026-06-14")],
        }
    }

    with patch(
        "dashboard_product.management.personnel_contribution.read_sources",
        side_effect=AssertionError("old reference reader must not run"),
    ):
        loaded = load_sources(
            tmp_path / "old-reference.xlsx",
            normalized_source=normalized_source,
            normalized_source_hashes=source_hashes,
        )

    assert loaded["resources_connected"] is True
    assert "transfers" not in loaded
    assert "transfers_connected" not in loaded
    assert loaded["source_hashes"] == source_hashes
    assert loaded["resources"][0]["source_row_number"] == 3
    assert loaded["resources"][0]["date"] == "2026-06-12"
    assert loaded["resources"][0]["record_key"] == "sha:resources:3"
    assert loaded["resources"][0]["origin_sha256"] == "a" * 64
    assert loaded["resources"][0]["origin_sheet"] == "crm"
    assert loaded["resources"][0]["source_owner"] == "语培甲"
    assert loaded["resources"][0]["market_group"] == "国际市场"
    assert loaded["resources"][0]["segment_id"] == "international_market"
    assert loaded["contracts"][0]["archive_date"] == "2026-06-13"
    assert loaded["contracts"][0]["month"] == "2026-06"
    assert loaded["languages"][0]["date"] == "2026-06-14"
    assert loaded["languages"][0]["origin_filename"] == "history.xlsx"


def test_normalized_international_resource_uses_source_owner_and_has_zero_without_cash() -> None:
    row = _resource(resource_id="1001", owner="留学甲")
    row.update({
        "source_owner": "语培甲", "market_group": "国际市场",
        "source_group": "国际市场", "segment_id": "international_market",
        "personal_eligible": "true", "campaign": "语培甲（留学甲）",
    })
    source_rows = _sources(resources=[row])

    result, details = _build(source_rows, ["2026-06"], training=["语培甲"])

    _, people = _person_rows(result, "2026-06")
    assert people["语培甲"]["output"]["orders"] == 0.5
    assert people["留学甲"]["received"]["orders"] == 0.5
    assert people["留学甲"]["self"]["cash"] == 0
    marker_record = next(record for record in details["records"]
                         if record["key"] == "resources:1001" and record["bucket"] == "output")
    assert marker_record["cross_business_marker"]["direction"] == "training_to_abroad"
    assert marker_record["marker_source_owner"] == "语培甲"
    assert marker_record["marker_source_row_number"] == 3


def test_canonical_group_wins_over_conflicting_raw_source_group() -> None:
    row = _resource(resource_id="1002", owner="留学甲")
    row.update({
        "source_owner": "语培甲", "market_group": "线下组",
        "source_group": "国际市场", "segment_id": "study_abroad_offline",
        "personal_eligible": "true", "campaign": "",
    })

    result, details = _build(_sources(resources=[row]), ["2026-06"], training=["语培甲"])

    _, people = _person_rows(result, "2026-06")
    assert people["留学甲"]["self"]["orders"] == 1
    assert people["留学甲"]["received"]["orders"] == 0
    assert people["语培甲"]["output"]["orders"] == 0
    assert details["diagnostics"]["international_marker_mapping_conflicts"] == 1
    assert all(record["cross_business_marker"] is None for record in details["records"])


def test_linked_international_marker_does_not_bypass_ssc_cash_exclusion() -> None:
    resource_row = _resource(resource_id="1003", owner="留学甲", event_date="2026-10-05")
    resource_row.update({
        "source_owner": "语培甲", "market_group": "国际市场",
        "segment_id": "international_market", "personal_eligible": "true",
    })
    cash_row = _contract(contract_id="C-SSC", amount="900")
    cash_row.update({
        "resource_id": "1003", "segment_id": "ssc",
        "personal_eligible": "true", "market_eligible": "true",
    })

    result, details = _build(
        _sources(resources=[resource_row], contracts=[cash_row]),
        ["2026-10"], training=["语培甲"],
    )

    _, people = _person_rows(result, "2026-10")
    assert people["语培甲"]["output"]["orders"] == 1
    assert people["留学甲"]["received"]["orders"] == 0
    assert people["留学甲"]["self"]["cash"] == 0
    assert people["留学甲"]["received"]["cash"] == 0
    assert people["语培甲"]["output"]["cash"] == 0
    assert not any(record["source"] == "contracts" for record in details["records"])


def test_ineligible_international_resource_cannot_mark_associated_cash() -> None:
    resource_row = _resource(resource_id="1004", owner="留学甲")
    resource_row.update({
        "source_owner": "语培甲", "market_group": "国际市场",
        "segment_id": "international_market", "personal_eligible": "false",
    })
    cash_row = _contract(contract_id="C-NO-MARKER", amount="900")
    cash_row.update({
        "resource_id": "1004", "market_group": "线下组",
        "segment_id": "study_abroad_offline", "personal_eligible": "true",
    })

    result, details = _build(
        _sources(resources=[resource_row], contracts=[cash_row]),
        ["2026-10"], training=["语培甲"],
    )

    _, people = _person_rows(result, "2026-10")
    assert people["留学甲"]["self"]["cash"] == 900
    assert people["语培甲"]["output"]["cash"] == 0
    cash_event = next(record for record in details["records"] if record["source"] == "contracts")
    assert cash_event["cross_business_marker"] is None


def test_anonymous_crm_record_key_counts_as_one_resource_without_fake_resource_id() -> None:
    source_rows = _sources(resources=[_resource()])

    result, details = _build(source_rows, ["2026-06"])

    period, people = _person_rows(result, "2026-06")
    assert people["留学甲"]["self"]["orders"] == 1
    assert period["coverage"]["abroad"]["orders_through"] == "2026-06-12"
    assert len(details["records"]) == 1
    event = details["records"][0]
    assert event["resource_id"] is None
    assert event["record_key"] == "sha:resources:3"
    assert event["origin_sheet"] == "crm"


def test_language_rows_with_same_origin_row_but_different_record_keys_both_count() -> None:
    source_rows = _sources(languages=[
        _language(amount="125", record_key="archive-a:languages:3", filename="june.xlsx"),
        _language(amount="125", record_key="archive-b:languages:3", filename="july.xlsx"),
    ])

    result, details = _build(source_rows, ["2026-10"])

    _period, people = _person_rows(result, "2026-10")
    assert people["留学甲"]["self"]["cash"] == 250
    language_events = [row for row in details["records"] if row["source"] == "languages"]
    assert len(language_events) == 2
    assert [row["source_row_number"] for row in language_events] == [3, 3]
    assert {row["record_key"] for row in language_events} == {
        "archive-a:languages:3", "archive-b:languages:3",
    }


def test_missing_standard_amount_is_skipped_and_does_not_change_known_cash() -> None:
    source_rows = _sources(contracts=[
        _contract(contract_id="C-MISSING", amount=None, amount_status="missing"),
        _contract(contract_id="C-AVAILABLE", amount="300", record_key="sha:contracts:4", row_number=4),
    ])

    result, details = _build(source_rows, ["2026-10"])

    _period, people = _person_rows(result, "2026-10")
    assert people["留学甲"]["self"]["cash"] == 300
    assert details["diagnostics"]["diagnostics_missing_amount"] == 1
    assert [row["key"] for row in details["records"] if row["source"] == "contracts"] == [
        "contracts:C-AVAILABLE",
    ]


def test_current_month_small_language_cash_enters_personnel_events() -> None:
    source_rows = _sources(languages=[_language(amount="725", event_date="2026-10-08")])

    result, details = _build(source_rows, ["2026-10"])

    _period, people = _person_rows(result, "2026-10")
    assert people["留学甲"]["breakdowns"]["small_language"]["self"]["cash"] == 725
    language_events = [row for row in details["records"] if row["source"] == "languages"]
    assert len(language_events) == 1
    assert language_events[0]["month"] == "2026-10"
    assert language_events[0]["source_value"] == "725"


def test_latest_cross_month_resource_date_wins_and_same_day_conflict_still_fails() -> None:
    source_rows = _sources(resources=[
        _resource(resource_id="1001", record_key="june:resources:3", event_date="2026-06-12"),
        _resource(resource_id="1001", record_key="july:resources:3", event_date="2026-07-12"),
    ])

    result, details = _build(source_rows, ["2026-06", "2026-07"])

    _june, june_people = _person_rows(result, "2026-06")
    _july, july_people = _person_rows(result, "2026-07")
    assert june_people["留学甲"]["self"]["orders"] == 0
    assert july_people["留学甲"]["self"]["orders"] == 1
    assert len([row for row in details["records"] if row["source"] == "resources"]) == 1
    assert details["diagnostics"]["superseded_abroad_resource_rows"] == 1

    conflicting_rows = _sources(resources=[
        _resource(resource_id="1002", record_key="same-day-a", event_date="2026-07-12"),
        {**_resource(resource_id="1002", record_key="same-day-b", event_date="2026-07-12"), "campaign": "冲突活动"},
    ])
    with pytest.raises(ValueError, match="同一留学记录存在冲突"):
        _build(conflicting_rows, ["2026-07"])
