"""Inject one real API crash during trusted fitting on isolated port 4203.

No inference/retrieval calls. Does not stop the production API or other projects.
"""
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

project = Path(__file__).resolve().parents[1]
root = project / "runtime" / ("restart-qa-" + uuid.uuid4().hex[:8])
root.mkdir(parents=True)
env = {"PATH": os.environ.get("PATH", os.defpath), "LANG": "en_US.UTF-8", "CRUCIBLE_RUNTIME": str(root), "PYTHONUNBUFFERED": "1"}
log = (root / "service.log").open("w")
process = None
client = httpx.Client(base_url="http://127.0.0.1:4203/api", timeout=10)


def launch():
    child = subprocess.Popen([sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "4203", "--no-access-log"], cwd=project, env=env, stdout=log, stderr=log)
    for _ in range(100):
        if child.poll() is not None:
            raise RuntimeError("Isolated API exited before startup; inspect its bounded service log")
        try:
            if client.get("/health").status_code == 200:
                client.headers["X-Crucible-Session"] = client.get("/session").json()["token"]
                return child
        except httpx.HTTPError:
            pass
        time.sleep(.05)
    raise RuntimeError("Isolated API startup timed out")


def get():
    response = client.get("/folios/synthetic")
    response.raise_for_status()
    return response.json()


def wait():
    for _ in range(300):
        doc = get()
        if doc["run"]["status"] not in {"queued", "running", "cancel_requested"}:
            return doc
        time.sleep(.05)
    raise RuntimeError("Bounded recovery test wait expired")


def action(name, **fields):
    doc = get()
    response = client.post("/folios/synthetic/actions/" + name, json={"revision": doc["revision"], "idempotency_key": uuid.uuid4().hex, **fields})
    response.raise_for_status()
    return response.json()


try:
    process = launch()
    wait()
    action("lock_contract", reviewer_name="Automated restart QA (agent)", review_note="Operational crash recovery test; no external scientific approval.")
    queued = action("reproduce")
    time.sleep(.2)
    assert get()["run"]["status"] in {"queued", "running"}
    os.kill(process.pid, signal.SIGKILL)
    process.wait(timeout=5)
    process = launch()
    recovered = get()
    assert recovered["run"]["id"] == queued["run"]["id"]
    assert recovered["status"] == "interrupted"
    assert not recovered["observations"]
    action("resume")
    completed = wait()
    assert completed["status"] == "baseline_review", completed["run"]
    assert completed["run"]["attempt"] == 2
    assert completed["reproduction"]["identical_predictions"]
    record = {"test": "Real isolated API SIGKILL during trusted reproduction; restart reconciliation and deliberate resume", "port": 4203,
              "interrupted_attempt": recovered["run"], "resumed_attempt": completed["run"],
              "observations_before_resume": len(recovered["observations"]), "reproduction": completed["reproduction"],
              "attempt_statuses": [a["status"] for a in completed["attempts"]], "provider_calls": len([r for r in completed["receipts"] if r["kind"] == "inference"])}
    (project / "runtime/qa/restart-recovery.json").write_text(json.dumps(record, indent=2))
    print(json.dumps(record, indent=2))
finally:
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    client.close()
    log.close()
