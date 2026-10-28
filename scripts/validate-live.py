"""Run actual authorized inference, retrieval and numerical workflow acceptance.

Reviews are explicitly automated local QA, not human scientific sign-off.
The synthetic original condition is chosen before its measured outcomes. The
public-data challenge follows the validated planner ranking, not a desired verdict.
"""
import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--base", default="http://127.0.0.1:4202/api")
parser.add_argument("--folio", default="both")
parser.add_argument("--skip-model-contract", action="store_true")
parser.add_argument("--condition", help="Explicit registered condition for a reproducibility replay")
parser.add_argument("--require-evidence-change", action="store_true")
args = parser.parse_args()
out = Path(__file__).resolve().parents[1] / "runtime" / "qa"
out.mkdir(parents=True, exist_ok=True)
client = httpx.Client(base_url=args.base, timeout=60)
client.headers["X-Crucible-Session"] = client.get("/session").json()["token"]
review = {"reviewer_name": "Automated local QA (agent)", "review_note": "Scripted local workflow acceptance. Not a human participant study or external methodologist sign-off."}


def get(id):
    response = client.get("/folios/" + id)
    response.raise_for_status()
    return response.json()


def wait(id):
    start, prior = time.monotonic(), None
    while time.monotonic() - start < 600:
        doc = get(id)
        run = doc.get("run") or {}
        state = (doc["status"], run.get("checkpoint"))
        if state != prior:
            print(id, *state, flush=True)
            prior = state
        if run.get("status") not in {"queued", "running", "cancel_requested"}:
            if run.get("status") in {"failed", "interrupted", "cancelled"}:
                raise RuntimeError(json.dumps({"id": id, "action": run.get("action"), "error": run.get("error")}))
            return doc
        time.sleep(1)
    raise RuntimeError("Timed out waiting for a bounded job")


def action(id, name, **body):
    doc = get(id)
    response = client.post(f"/folios/{id}/actions/{name}", json={"revision": doc["revision"], "idempotency_key": uuid.uuid4().hex, **body})
    if response.status_code >= 400:
        raise RuntimeError(f"{name}: {response.status_code} {response.text}")
    print(id, "action", name, flush=True)
    return wait(id)


for id in (["occupancy", "synthetic"] if args.folio == "both" else [args.folio]):
    doc = wait(id)
    adapter = doc["adapter_id"]
    if not doc["contract"]["locked"]:
        if not args.skip_model_contract and not doc["contract"].get("model_proposal"):
            doc = action(id, "propose_contract")
        doc = action(id, "lock_contract", **review)
    if not any(o["phase"] == "reproduction" for o in doc["observations"]):
        doc = action(id, "reproduce")
    if not doc["reproduction_accepted"]:
        doc = action(id, "accept_reproduction", **review)
    if not doc["exploration_complete"]:
        if adapter == "occupancy" and not doc["evidence_change"]:
            doc = action(id, "retrieve")
        if doc.get("evidence_change") and doc["evidence_change"]["status"] == "proposed":
            doc = action(id, "accept_evidence", **review, reason="Include documented Light-sensor availability within the registered finite lattice. This is an authored applicability test, not a claimed paper correction.")
        if adapter == "occupancy" and args.require_evidence_change and (doc.get("evidence_change") or {}).get("status") != "accepted":
            raise RuntimeError("No meaningful retrieval change was accepted. Preserve the receipt and inspect the source before exploration.")
        doc = action(id, "explore")
    if not doc["registration"]:
        condition = args.condition or ("original" if adapter == "synthetic" else (doc["proposals"][0]["condition_id"] if doc["proposals"] else "co2_25"))
        doc = action(id, "register_confirmation", condition_id=condition, **review)
    if not doc.get("prediction_manifest"):
        doc = action(id, "confirm")
    if not doc["verification"]:
        doc = action(id, "verify")
    if not doc["conclusion"].get("review"):
        doc = action(id, "review_conclusion", **review)
    package = client.get(f"/folios/{id}/export")
    package.raise_for_status()
    (out / f"{id}-evidence.zip").write_bytes(package.content)
    (out / f"{id}-report.html").write_text(client.get(f"/folios/{id}/report").text)
    (out / f"{id}-acceptance.json").write_text(json.dumps(doc, indent=2))
    print(json.dumps({"folio": id, "outcome": doc["conclusion"]["outcome"], "condition": doc["registration"]["condition_id"], "observations": len(doc["observations"]), "checks": len(doc["verification"]["checks"]), "zip_sha256": hashlib.sha256(package.content).hexdigest(), "zip_bytes": len(package.content), "inference_calls": len([r for r in doc["receipts"] if r["kind"] == "inference"]), "estimated_inference_cost_usd": sum(r.get("estimated_cost_usd") or 0 for r in doc["receipts"] if r["kind"] == "inference")}), flush=True)
