"""Versioned, host-independent company bridge contracts."""

from workspace_modeling.company_bridge.service import (
    BridgeError,
    build_bridge,
    default_candidate_path,
    load_bridge,
    load_candidate_set,
    validate_bridge,
    validate_candidate_set,
)

__all__ = [
    "BridgeError",
    "build_bridge",
    "default_candidate_path",
    "load_bridge",
    "load_candidate_set",
    "validate_bridge",
    "validate_candidate_set",
]
