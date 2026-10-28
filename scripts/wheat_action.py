"""Explicit local API actions; never silently retries a metered request."""
import argparse
import json
import time
import uuid

import httpx

ACTIONS = ["status", "compile_sources", "retrieve", "accept_evidence", "reject_evidence", "prepare", "train",
           "run_cell", "plan_next", "execute_plan", "register", "evaluate", "build_export", "cancel", "resume"]


def summary(doc):
    return {"study": doc["id"], "revision": doc["revision"], "status": doc["status"], "prepared": doc.get("prepared", False),
            "capabilities": doc["capabilities"], "source_readiness": doc.get("source_readiness"),
            "run": doc.get("run"), "training": doc["training"],
            "cells": [{"id": cell["id"], "status": cell["status"], "aggregate": cell.get("aggregate")} for cell in doc["cells"]],
            "registration": doc["registration"], "export_url": doc.get("export_url")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--cell", choices=["native_full", "native_noop", "retain_768", "retain_512", "retain_256", "native_tiles", "degraded_tiles256", "native_multiscale"])
    parser.add_argument("--operator", default="Local command-line operator")
    parser.add_argument("--reason")
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()
    if args.action in {"run_cell", "register"} and not args.cell:
        parser.error("This action requires --cell with an explicit declared recipe")
    with httpx.Client(base_url="http://127.0.0.1:4202", timeout=30) as client:
        response = client.get("/api/wheat")
        response.raise_for_status()
        doc = response.json()
        if args.action != "status":
            token = client.get("/api/session").json()["token"]
            body = {"revision": doc["revision"], "idempotency_key": uuid.uuid4().hex, "operator_name": args.operator}
            if args.cell:
                body["cell_id"] = args.cell
            if args.reason:
                body["reason"] = args.reason
            response = client.post("/api/wheat/actions/" + args.action, headers={"X-Crucible-Session": token}, json=body)
            if response.status_code >= 400:
                raise SystemExit(json.dumps(response.json(), indent=2))
            doc = response.json()
        print(json.dumps(summary(doc), indent=2), flush=True)
        last = time.monotonic()
        while args.wait and doc.get("run", {}) and doc["run"]["status"] in {"queued", "running", "cancel_requested"}:
            time.sleep(2)
            response = client.get("/api/wheat")
            response.raise_for_status()
            doc = response.json()
            if time.monotonic() - last > 30:
                print(json.dumps({"status": doc["run"]["status"], "checkpoint": doc["run"]["checkpoint"]}), flush=True)
                last = time.monotonic()
        if args.wait:
            print(json.dumps(summary(doc), indent=2), flush=True)
            if (doc.get("run") or {}).get("status") in {"failed", "cancelled", "interrupted"}:
                raise SystemExit(2)


if __name__ == "__main__":
    main()
