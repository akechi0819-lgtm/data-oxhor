from __future__ import annotations

import hashlib

import pytest

from data_acquisition.jobs.study_abroad_identity import align_customer_keys


def _contract(customer_name: str, customer_id: str | None = None, amount: int = 100) -> dict:
    return {
        "customer_id": customer_id,
        "customer_name": customer_name,
        "amount": amount,
        "market_eligible": "true",
    }


def _language(customer_name: str, student_id: str | None = None, amount: int = 100) -> dict:
    return {
        "student_id": student_id,
        "customer_name": customer_name,
        "amount": amount,
        "market_eligible": "true",
    }


def _name_key(kind: str, name: str) -> str:
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return f"{kind}:name:{digest}"


def test_repeated_name_across_contracts_counts_as_one_customer() -> None:
    tables = {"contracts": [_contract("Same Name"), _contract("Same Name", amount=250)]}

    diagnostics = align_customer_keys(tables)

    assert tables["contracts"][0]["customer_key"] == tables["contracts"][1]["customer_key"]
    assert tables["contracts"][0]["customer_key"] == _name_key("contracts", "Same Name")
    assert [row["customer_key_basis"] for row in tables["contracts"]] == ["name", "name"]
    assert diagnostics["contracts"]["unique_customer_keys"] == 1
    assert "Same Name" not in repr(diagnostics)


def test_same_name_is_scoped_to_its_business_domain() -> None:
    tables = {
        "contracts": [_contract("Shared Name")],
        "languages": [_language("Shared Name")],
    }

    align_customer_keys(tables)

    contract_key = tables["contracts"][0]["customer_key"]
    language_key = tables["languages"][0]["customer_key"]
    assert contract_key == _name_key("contracts", "Shared Name")
    assert language_key == _name_key("languages", "Shared Name")
    assert contract_key != language_key


def test_unique_known_id_bridges_a_missing_id_by_normalized_name() -> None:
    tables = {
        "contracts": [
            _contract("  Ada   Lovelace ", customer_id="C-1"),
            _contract("Ada Lovelace"),
        ]
    }

    align_customer_keys(tables)

    assert [row["customer_key"] for row in tables["contracts"]] == [
        "contracts:C-1",
        "contracts:C-1",
    ]
    assert [row["customer_key_basis"] for row in tables["contracts"]] == ["id", "name_to_id"]
    # The source name remains available privately and is not replaced by its normalized form.
    assert tables["contracts"][0]["customer_name"] == "  Ada   Lovelace "


def test_same_name_with_multiple_known_ids_does_not_choose_either_id() -> None:
    tables = {
        "languages": [
            _language("Same Name", student_id="S-1"),
            _language("Same Name", student_id="S-2"),
            _language(" Same   Name "),
        ]
    }

    diagnostics = align_customer_keys(tables)

    rows = tables["languages"]
    assert rows[0]["customer_key"] == "languages:S-1"
    assert rows[1]["customer_key"] == "languages:S-2"
    assert rows[2]["customer_key"] == _name_key("languages", "Same Name")
    assert rows[2]["customer_key_basis"] == "name_ambiguous"
    assert rows[2]["customer_key"] not in {rows[0]["customer_key"], rows[1]["customer_key"]}
    assert diagnostics["languages"]["identity_basis_counts"]["name_ambiguous"] == 1


def test_market_eligible_positive_row_without_name_or_id_fails() -> None:
    tables = {"contracts": [_contract("  ")]}

    with pytest.raises(ValueError, match="without customer identity"):
        align_customer_keys(tables)


def test_unidentified_nonmarket_or_nonpositive_rows_remain_without_key() -> None:
    tables = {
        "contracts": [
            {**_contract(""), "market_eligible": "false", "amount": 500},
            {**_contract(""), "amount": 0},
        ]
    }

    diagnostics = align_customer_keys(tables)

    assert [row["customer_key"] for row in tables["contracts"]] == [None, None]
    assert [row["customer_key_basis"] for row in tables["contracts"]] == [None, None]
    assert diagnostics["contracts"]["identity_basis_counts"]["none"] == 2


def test_equal_language_amounts_do_not_merge_different_names() -> None:
    tables = {
        "languages": [
            _language("Person A", amount=500),
            _language("Person B", amount=500),
        ]
    }

    diagnostics = align_customer_keys(tables)

    assert tables["languages"][0]["customer_key"] != tables["languages"][1]["customer_key"]
    assert diagnostics["languages"]["unique_customer_keys"] == 2
