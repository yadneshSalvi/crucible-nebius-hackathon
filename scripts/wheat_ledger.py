"""Export observed service usage separately from estimated provider charges."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("runtime/wheat-service-ledger.json"))
    args = parser.parse_args()
    response = httpx.get("http://127.0.0.1:4202/api/wheat", timeout=30)
    response.raise_for_status()
    study = response.json()
    keys = ["id", "kind", "provider", "model", "returned_model", "purpose", "status", "started_at", "elapsed_ms",
            "request_id", "http_status", "input_tokens", "output_tokens", "estimated_cost_usd", "cost_basis", "credits",
            "request_sha256", "context_sha256", "response_sha256", "finish_reason", "error", "validation_error"]
    receipts = [{key: row.get(key) for key in keys} for row in study["receipts"] if row.get("kind") in {"inference", "retrieval"}]
    providers = {}
    for row in receipts:
        provider = providers.setdefault(row["provider"], {"attempts": 0, "successful": 0, "known_input_tokens": 0, "known_output_tokens": 0,
            "known_token_attempts": 0, "unknown_token_attempts": 0, "known_estimated_cost_usd": 0.0,
            "unknown_cost_attempts": 0, "actual_billed_charge_usd": None})
        provider["attempts"] += 1
        provider["successful"] += row["status"] == "succeeded"
        if isinstance(row.get("input_tokens"), int) and isinstance(row.get("output_tokens"), int):
            provider["known_input_tokens"] += row["input_tokens"]
            provider["known_output_tokens"] += row["output_tokens"]
            provider["known_token_attempts"] += 1
        else:
            provider["unknown_token_attempts"] += 1
        if row.get("estimated_cost_usd") is None:
            provider["unknown_cost_attempts"] += 1
        else:
            provider["known_estimated_cost_usd"] += row["estimated_cost_usd"]
    for value in providers.values():
        value["known_estimated_cost_usd"] = round(value["known_estimated_cost_usd"], 8)
        value["estimated_cost_usd"] = value["known_estimated_cost_usd"] if not value["unknown_cost_attempts"] else None
        value["input_tokens"] = value["known_input_tokens"] if not value["unknown_token_attempts"] else None
        value["output_tokens"] = value["known_output_tokens"] if not value["unknown_token_attempts"] else None
    ledger = {"schema_version": "crucible.service-ledger.v1", "generated_at": datetime.now(timezone.utc).isoformat(),
        "study_id": study["id"], "revision": study["revision"], "receipts": receipts, "providers": providers,
        "billing_status": "Observed request identities/token usage are real. Dollar amounts are receipt estimates, not billing statements; unknown charges stay null.",
        "nebius_transport_qualified": any(row["provider"] == "nebius" and row["http_status"] == 200 and row["returned_model"] == "nvidia/Nemotron-3-Ultra-550b-a55b" and row["finish_reason"] == "stop" for row in receipts),
        "nebius_source_role_qualified": any(row.get("provider") == "nebius" and row.get("status") == "succeeded" for row in study.get("provider_qualifications", [])),
        "provider_qualifications": study.get("provider_qualifications", []),
        "science_status": {"prepared": study.get("prepared"), "training": study["training"]["status"],
            "executed_discovery_cells": [cell["id"] for cell in study["cells"] if cell["status"] == "succeeded"],
            "final_registration": study["registration"]["status"], "verification": study.get("verification")}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(ledger, indent=2) + "\n")
    print(json.dumps({"ledger": str(args.output), "providers": providers,
        "nebius_transport_qualified": ledger["nebius_transport_qualified"], "nebius_source_role_qualified": ledger["nebius_source_role_qualified"]}, indent=2))


if __name__ == "__main__":
    main()
