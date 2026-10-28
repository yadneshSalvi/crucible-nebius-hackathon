"""Stable interface used by the TypeScript control plane."""

from copy import deepcopy

from .common import ScienceError, digest, finite_number
from .spec import SCHEMA, ANALYSIS, BASELINE, CANDIDATE, CONDITIONS, DEFAULT_ACTIVE, NUMERICAL_SPEC, PREPROCESSING, SEEDS, case_metadata


def numerical_spec_sha256():
    return digest(NUMERICAL_SPEC)


def get_case(adapter_id):
    """Pure metadata. Does not read files, download, import sklearn, or fit."""
    try:
        case = case_metadata(adapter_id)
    except ValueError as exc:
        raise ScienceError("UNSUPPORTED_ADAPTER", str(exc)) from exc
    case["contract"] = {
        "schema_version": SCHEMA,
        "adapter_id": adapter_id,
        "revision": 1,
        "claim": case["claim"],
        "population": case["population"],
        "candidate": deepcopy(CANDIDATE),
        "baseline": deepcopy(BASELINE),
        "metric": "balanced_accuracy",
        "practical_delta": 0.02,
        "alpha": 0.05,
        "analysis": ANALYSIS,
        "split": case["split"],
        "preprocessing": PREPROCESSING,
        "seeds": list(SEEDS),
        "allowed_conditions": deepcopy(CONDITIONS),
        "active_conditions": list(DEFAULT_ACTIVE),
        "scope": "Original sensors only. Sensor-dropout conditions are applicability tests outside the original claim.",
        "numerical_spec_sha256": numerical_spec_sha256(),
        "confirmation_split_sha256": None,
        "approval": None,
        "locked": False,
    }
    return case


PROTECTED_FIELDS = ["schema_version", "adapter_id", "candidate", "baseline", "metric", "alpha", "analysis",
                    "split", "preprocessing", "seeds", "allowed_conditions", "population", "scope", "numerical_spec_sha256"]


def validate_contract(contract, prepared, require_locked=True):
    if not isinstance(contract, dict):
        raise ScienceError("CONTRACT_REQUIRED", "A reviewed contract is required")
    expected = prepared["contract"]
    for key in PROTECTED_FIELDS:
        if contract.get(key) != expected.get(key):
            raise ScienceError("ORACLE_PROTECTED", f"Trusted numerical field cannot be changed by a proposal: {key}")
    if contract.get("confirmation_split_sha256") != prepared["confirmation_split_sha256"]:
        raise ScienceError("SPLIT_MISMATCH", "Contract does not bind the prepared confirmation split")
    delta = finite_number(contract.get("practical_delta"), "practical_delta")
    if not 0 <= delta <= 0.1:
        raise ScienceError("INVALID_CONTRACT", "practical_delta must be between 0 and 0.1")
    active = contract.get("active_conditions")
    allowed = {c["id"] for c in CONDITIONS}
    if not isinstance(active, list) or not active or len(active) != len(set(active)) or not set(active) <= allowed or "original" not in active:
        raise ScienceError("INVALID_CONTRACT", "Active conditions must be unique allowed IDs including original")
    if not isinstance(contract.get("claim"), str) or not contract["claim"].strip() or len(contract["claim"]) > 4000:
        raise ScienceError("INVALID_CONTRACT", "Claim must be nonempty and at most 4000 characters")
    if require_locked and contract.get("locked") is not True:
        raise ScienceError("CONTRACT_NOT_LOCKED", "Local operator must review and lock the contract first", True)
    return contract


def contract_signature(contract):
    """Active discovery scheduling is allowed to change within the fixed lattice."""
    fields = PROTECTED_FIELDS + ["claim", "practical_delta", "confirmation_split_sha256"]
    return digest({key: contract.get(key) for key in fields})


def prepare_case(adapter_id, root, source_zip=None):
    from .prepare import prepare_case as prepare
    return prepare(adapter_id, root, source_zip=source_zip)
