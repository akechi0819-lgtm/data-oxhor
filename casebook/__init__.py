"""Deterministic local Casebook storage for a single customer workspace."""

from .service import (
    CasebookError,
    capture_case,
    confirm_case,
    create_case,
    reject_case,
    search_cases,
    supersede_case,
    verify_case,
)

__all__ = [
    "CasebookError",
    "capture_case",
    "confirm_case",
    "create_case",
    "reject_case",
    "search_cases",
    "supersede_case",
    "verify_case",
]
