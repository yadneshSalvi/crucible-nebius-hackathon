"""Actual metered qualification of the typed advisory contract schema.

Preserves its own receipt outside application folios. Never overwrites a
historical model answer or changes a scientific contract or outcome.
"""
import asyncio
import json
from pathlib import Path

import httpx

from api.config import Settings
from api.orchestrator import Orchestrator
from api.providers import ContractProposal, Gateway


async def main():
    destination = Path(__file__).resolve().parents[1] / "runtime/qa/proposal-schema-qualification"
    destination.mkdir(parents=True, exist_ok=True)
    folio = httpx.get("http://127.0.0.1:4202/api/folios/occupancy").json()
    context = Orchestrator._model_context(folio)
    def save(receipt):
        (destination / (receipt["id"] + ".json")).write_text(json.dumps(receipt, indent=2))
    gateway = Gateway(Settings.read(), save)
    result = await gateway.model("contract_schema_v2_qualification", context, ContractProposal,
        "Clarify the authored comparison only. Follow trusted_facts exactly: Occupancy calendar-day independence is unestablished, and the three seeds only describe training variability. Never assert they justify a t interval or serve as independent units. Numerical fields cannot be changed.")
    (destination / "validated-proposal.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"status": "qualified", "block_independence_established": result["block_independence_established"], "seed_role": result["seed_role"], "receipt_id": gateway.last_receipt["id"], "estimated_cost_usd": gateway.last_receipt["estimated_cost_usd"]}))


if __name__ == "__main__":
    asyncio.run(main())
