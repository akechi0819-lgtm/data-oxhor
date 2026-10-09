"""Align customer identities for study-abroad signing rows."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import re


_IDENTITY_FIELDS = {
    "contracts": "customer_id",
    "languages": "student_id",
}


def _identifier(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    if text in {"", "/", "None", "null"}:
        return None
    return text


def _customer_name(value: object) -> str | None:
    if value is None:
        return None
    # Only trim and collapse whitespace. Keep spelling, punctuation, and
    # internal spaces so that this remains an exact, auditable name match.
    text = re.sub(r"\s+", " ", str(value).strip())
    return text or None


def _is_market_eligible(value: object) -> bool:
    if value is True:
        return True
    return isinstance(value, str) and value.strip().casefold() == "true"


def _is_positive_amount(value: object) -> bool:
    if value is None or value == "":
        return False
    try:
        amount = Decimal(str(value).replace(",", "").replace("￥", "").replace("¥", ""))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("study-abroad identity alignment requires normalized amounts") from exc
    if not amount.is_finite():
        raise ValueError("study-abroad identity alignment requires finite amounts")
    return amount > 0


def _name_key(kind: str, name: str) -> str:
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return f"{kind}:name:{digest}"


def align_customer_keys(tables: dict) -> dict:
    """Set domain-scoped customer keys and return aggregate identity counts.

    ``tables`` is mutated in place. Contracts and language rows are aligned
    separately, using their respective source ID and the private
    ``customer_name`` field. Names are never returned in diagnostics or used
    directly in a generated key.
    """
    diagnostics = {}
    for kind, id_field in _IDENTITY_FIELDS.items():
        rows = tables.get(kind, [])
        if not isinstance(rows, list):
            raise TypeError(f"{kind} must be a list of normalized rows")

        ids_by_name: dict[str, set[str]] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError(f"{kind} contains a non-dictionary row")
            name = _customer_name(row.get("customer_name"))
            customer_id = _identifier(row.get(id_field))
            if name and customer_id:
                ids_by_name.setdefault(name, set()).add(customer_id)

        planned = []
        basis_counts = {"id": 0, "name": 0, "name_to_id": 0, "name_ambiguous": 0, "none": 0}
        positive_market_rows = 0
        for row in rows:
            name = _customer_name(row.get("customer_name"))
            customer_id = _identifier(row.get(id_field))
            market_positive = (
                _is_market_eligible(row.get("market_eligible"))
                and _is_positive_amount(row.get("amount"))
            )
            positive_market_rows += int(market_positive)

            if customer_id:
                customer_key = f"{kind}:{customer_id}"
                basis = "id"
            elif name:
                known_ids = ids_by_name.get(name, set())
                if len(known_ids) == 1:
                    customer_key = f"{kind}:{next(iter(known_ids))}"
                    basis = "name_to_id"
                elif len(known_ids) > 1:
                    customer_key = _name_key(kind, name)
                    basis = "name_ambiguous"
                else:
                    customer_key = _name_key(kind, name)
                    basis = "name"
            else:
                customer_key = None
                basis = None

            if market_positive and customer_key is None:
                raise ValueError(f"{kind} has a market-eligible positive-amount row without customer identity")

            basis_counts[basis or "none"] += 1
            planned.append((customer_key, basis))

        for row, (customer_key, basis) in zip(rows, planned):
            row["customer_key"] = customer_key
            row["customer_key_basis"] = basis

        diagnostics[kind] = {
            "rows": len(rows),
            "market_eligible_positive_rows": positive_market_rows,
            "identity_basis_counts": basis_counts,
            "unique_customer_keys": len({key for key, _basis in planned if key is not None}),
        }

    return diagnostics
