"""One explicit, bounded source-role replay; never repeats a failed paid attempt."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values
from api.config import PROJECT, Settings
from api.orchestrator import ACTIVE
from api.providers import ProviderError
from api.store import Conflict, Store, canonical, digest, now
from api.wheat import WheatOrchestrator
from api.wheat_protocol import STUDY_ID
from api.wheat_providers import SOURCE_EXTRACTION_PROFILE, SOURCE_EXTRACTION_RULES, WheatGateway, WheatSources

AUTHORIZED_USD = Decimal("10")
REQUEST_RESERVATION_USD = Decimal("0.12")
QUALIFICATION_KEY = "nebius-ultra-primary-excerpts-v3"


def sqlite_rows(path: Path, query: str) -> list[dict]:
    if not path.is_file():
        raise ValueError(f"Canonical usage source is unavailable: {path}")
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as db:
        return [json.loads(row[0]) for row in db.execute(query)]


def budget_snapshot(runtime: Path) -> dict:
    """Audit canonical actual ledgers; a fresh checkout cannot inherit consent."""
    workspace = PROJECT.parent
    items, sources = {}, []

    def add(source, rows, adapter):
        sources.append({"source": str(source), "rows_sha256": digest(rows), "rows": len(rows)})
        for raw in rows:
            row = adapter(raw)
            if row is None:
                continue
            ident = row["request_id"] or row["receipt_id"]
            if ident in items:
                if items[ident]["estimated_cost_usd"] != row["estimated_cost_usd"]:
                    raise ValueError("Duplicate provider request has conflicting cost evidence")
                items[ident]["sources"].append(str(source))
            else:
                items[ident] = {**row, "sources": [str(source)]}

    def passage(row):
        if row.get("provider", "nebius") != "nebius":
            return None
        if not str(row.get("model", "")).lower().startswith("nvidia/"):
            raise ValueError("Legacy Passage route cannot be assigned to Nebius safely")
        return {"receipt_id": row["id"], "request_id": row.get("requestId"), "project": "Passage",
                "estimated_cost_usd": row.get("chargedUsd"), "usage_known": row.get("state") == "complete" and row.get("chargedUsd") is not None}

    for relative in (".passage/runs.db", ".passage/nebius-qualification/runs.db", ".passage/nebius-journey-qualification/runs.db"):
        path = workspace / "passage" / relative
        add(path, sqlite_rows(path, "SELECT data FROM usage"), passage)

    def common_ground(raw):
        row = raw.get("receipt", raw)
        if str(row.get("provider_id", row.get("provider", ""))).lower() != "nebius":
            return None
        return {"receipt_id": row.get("receipt_id", row.get("id")), "request_id": row.get("request_id"), "project": "CommonGround",
                "estimated_cost_usd": row.get("estimated_cost_usd"), "usage_known": row.get("usage_known") is True and row.get("estimated_cost_usd") is not None}

    for relative in ("evidence/provider-usage.json", "evidence/living-provider-usage.json"):
        path = workspace / "common-ground" / relative
        add(path, json.loads(path.read_text())["receipts"], common_ground)

    def ordinary(project):
        def adapt(row):
            if str(row.get("provider", "")).lower() != "nebius":
                return None
            return {"receipt_id": row.get("id", row.get("request_id")), "request_id": row.get("request_id"), "project": project,
                    "estimated_cost_usd": row.get("estimated_cost_usd"), "usage_known": row.get("estimated_cost_usd") is not None}
        return adapt

    path = workspace / "forge/data/forge.sqlite3"
    add(path, sqlite_rows(path, "SELECT summary FROM provider_calls"), ordinary("Forge"))
    path = runtime / "crucible.sqlite3"
    add(path, sqlite_rows(path, "SELECT doc FROM receipts"), ordinary("Crucible"))
    key_test = json.loads((workspace / "artifacts/nebius-key-test.json").read_text())
    if key_test.get("inference_requested") is not False:
        raise ValueError("Root key-test inference status changed; review separate usage before admission")
    total = sum((Decimal(str(row["estimated_cost_usd"])) for row in items.values() if row["estimated_cost_usd"] is not None), Decimal(0))
    total = total.quantize(Decimal("0.00000001"))
    unknown = sum(not row["usage_known"] for row in items.values())
    return {"schema_version": "crucible.nebius-budget.v1", "generated_at": now(), "sources": sources,
            "deduplication": "Provider request ID, falling back to receipt ID; exported copies are not counted again",
            "scope": "Canonical actual four-project ledgers plus Passage qualification stores. Root listing had no inference; inspected root provider smoke contains Fireworks/Together only.",
            "receipts": list(items.values()), "known_estimated_cost_usd": str(total), "unknown_usage_attempts": unknown,
            "authorized_usd": str(AUTHORIZED_USD), "request_reservation_usd": str(REQUEST_RESERVATION_USD),
            "headroom_after_reservation_usd": str(AUTHORIZED_USD - total - REQUEST_RESERVATION_USD),
            "admitted": unknown == 0 and total + REQUEST_RESERVATION_USD <= AUTHORIZED_USD,
            "billing_status": "Retained application estimates, not invoices. No top-up or provider billing cap is implied."}


async def qualify(execute: bool):
    base = Settings.read()
    store = Store(base.root)
    runner = WheatOrchestrator(base, store)
    runner.ensure()
    doc = store.get(STUDY_ID)
    budget = budget_snapshot(base.root)
    if not execute:
        print(json.dumps({key: value for key, value in budget.items() if key not in {"receipts", "sources"}}, indent=2))
        return
    if not budget["admitted"]:
        raise ValueError("Cumulative budget admission failed; no Nebius request was transmitted")
    if any(item["key"] == QUALIFICATION_KEY for item in doc.get("provider_qualifications", [])):
        raise ValueError("Qualification already reserved or attempted. Inspect its receipt; there is no automatic retry")
    if doc.get("run") and doc["run"]["status"] in ACTIVE:
        raise ValueError("Wait for the active local job before this explicit provider replay")
    if (doc.get("source_compilation") or {}).get("profile") != SOURCE_EXTRACTION_PROFILE:
        raise ValueError("The revised atomic source task must pass actual development qualification first")
    values = dotenv_values(PROJECT.parent / ".env")
    key = os.environ.get("NEBIUS_API_KEY", str(values.get("NEBIUS_API_KEY") or ""))
    if not key:
        raise ValueError("Nebius key is unavailable; no request was transmitted")
    settings = replace(base, provider="nebius", model="nvidia/Nemotron-3-Ultra-550b-a55b",
                       base_url="https://api.tokenfactory.us-central1.nebius.com/v1", api_key=key, allow_nebius=True)
    context = runner.source_context(doc)
    qualification = {"key": QUALIFICATION_KEY, "id": uuid.uuid4().hex, "status": "reserved", "started_at": now(),
                     "provider": "nebius", "model": settings.model, "endpoint": settings.base_url,
                     "role": "primary_excerpt_source_extraction", "deliberate_replay": True,
                     "profile": SOURCE_EXTRACTION_PROFILE,
                     "packet_sha256": context["packet_sha256"], "context_sha256": digest(context),
                     "nominal_ceiling_usd": float(REQUEST_RESERVATION_USD),
                     "limitation": "Source role only. Detector fitting, unrun-experiment planning and final scientific evaluation remain pending."}
    budget_artifact = store.json_artifact(budget, "wheat-nebius-budget-admission.json", "budget_admission")

    def reserve(current):
        if any(item["key"] == QUALIFICATION_KEY for item in current.get("provider_qualifications", [])):
            raise ValueError("Concurrent qualification reservation already exists")
        current.setdefault("provider_qualifications", []).append(qualification.copy())
        current["artifacts"].append(budget_artifact)
    store.mutate(STUDY_ID, reserve, ("provider_qualification_reserved", "One Nebius source-role replay reserved after four-project budget audit; scientific state is unchanged."))
    gateway = WheatGateway(settings, lambda receipt: store.add_receipt(STUDY_ID, qualification["id"], receipt))
    error = None
    try:
        proposal = await gateway.model("wheat_nebius_primary_excerpt_replay_v3", context, WheatSources,
                                       SOURCE_EXTRACTION_RULES, nominal_ceiling_usd=float(REQUEST_RESERVATION_USD))
        runner.validate_source_proposal(doc, context, proposal)
        qualification.update(status="succeeded", validated_fields=len(proposal["fields"]))
    except (ProviderError, Conflict, ValueError) as exc:
        error = getattr(exc, "message", str(exc))
        qualification.update(status="failed", error=error)
        if isinstance(exc, Conflict) and gateway.last_receipt:
            gateway.save_receipt({**gateway.last_receipt, "status": "proposal_rejected", "error": error})
    finally:
        qualification.update(completed_at=now(), receipt_id=(gateway.last_receipt or {}).get("id"))
        def complete(current):
            for item in current["provider_qualifications"]:
                if item["id"] == qualification["id"]:
                    item.update(qualification)
        store.mutate(STUDY_ID, complete, ("provider_qualification_completed", "Nebius source-role replay " + qualification["status"] + "; source compilation and scientific outcomes were not replaced."))
        (base.root / (QUALIFICATION_KEY + "-budget.json")).write_bytes(canonical(budget) + b"\n")
        (base.root / (QUALIFICATION_KEY + ".json")).write_bytes(canonical(qualification) + b"\n")
    print(json.dumps(qualification, indent=2))
    if error:
        raise SystemExit(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Transmit the one authorized replay; default only audits usage")
    args = parser.parse_args()
    asyncio.run(qualify(args.execute))
