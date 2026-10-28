"""Security and durable-state regression cases; all model transports are offline."""
from __future__ import annotations

import asyncio
import copy
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.config import Settings
from api.main import create_app
from api.orchestrator import Orchestrator
from api.providers import ContractProposal, parse_content
from api.store import Store, canonical, digest, now


def authored_folio(id="case-a", split="a" * 64):
    contract = {"schema_version": "crucible.claim.v1", "revision": 1, "claim": "A registered authored candidate comparison in a controlled test.",
                "locked": True, "sha256": "d" * 64, "approval": {"role": "local_operator"}, "metric": "balanced_accuracy",
                "population": "Controlled independent test groups", "candidate": {"name": "Candidate"}, "baseline": {"name": "Baseline"},
                "practical_delta": 0.02, "alpha": 0.05, "analysis": "Paired independent groups", "seeds": [11, 29, 47],
                "confirmation_split_sha256": split, "numerical_spec_sha256": "b" * 64,
                "allowed_conditions": [{"id": "original", "label": "Original", "scope": "in_scope"}, {"id": "light100", "label": "Light 100%", "feature": "Light", "scope": "applicability"}],
                "active_conditions": ["original"]}
    return {"id": id, "adapter_id": "synthetic", "title": "State-machine test fixture", "claim": contract["claim"], "case_kind": "controlled_synthetic",
            "revision": 1, "created_at": now(), "updated_at": now(), "stage": "challenge", "status": "explored", "source": {"title": "Authored fixture", "audit": "No external data"},
            "contract": contract, "run": None, "evidence_change": None, "observations": [{"id": "obs1", "phase": "discovery", "condition_id": "original"}, {"id": "obs2", "phase": "discovery", "condition_id": "light100"}],
            "proposals": [], "registration": None, "verification": None, "conclusion": None, "artifacts": [], "limitations": [], "reproduction_accepted": True, "exploration_complete": True}


@pytest.fixture
def app(tmp_path):
    cfg = Settings(tmp_path, "fireworks", "accounts/fireworks/models/nemotron-3-ultra-nvfp4", "https://api.fireworks.ai/inference/v1", "", "", False, None)
    app = create_app(cfg, seed=False)
    app.state.store.create(authored_folio())
    with TestClient(app) as client:
        client.headers["X-Crucible-Session"] = client.get("/api/session").json()["token"]
        yield app, client


def act(client, id, action, **body):
    current = client.get(f"/api/folios/{id}").json()
    payload = {"revision": current["revision"], "idempotency_key": uuid.uuid4().hex, **body}
    return client.post(f"/api/folios/{id}/actions/{action}", json=payload)


def test_local_session_origin_and_typed_boundaries(app):
    _, client = app
    assert client.post("/api/folios", headers={"X-Crucible-Session": ""}, json={"adapter_id": "synthetic"}).status_code == 403
    assert client.post("/api/folios", headers={"Origin": "https://untrusted.example"}, json={"adapter_id": "synthetic"}).status_code == 403
    response = act(client, "case-a", "register_confirmation", condition_id="original", reviewer_name="Test operator", shell="cat secrets")
    assert response.status_code == 422
    assert client.post("/api/folios", json={"adapter_id": "arbitrary_repository", "url": "http://169.254.169.254"}).status_code == 422
    assert client.post("/api/folios", content="x" * 40000, headers={"Content-Type": "application/json"}).status_code == 413


def test_registration_is_durable_idempotent_and_freezes_one_condition(app):
    app, client = app
    payload = {"revision": 1, "idempotency_key": "same-request", "condition_id": "original", "reviewer_name": "Test operator"}
    first = client.post("/api/folios/case-a/actions/register_confirmation", json=payload)
    assert first.status_code == 200
    registration = first.json()["registration"]
    assert registration["holdout_status"] == "first_registered_use"
    assert registration["review"]["external_methodologist"] == "pending"
    again = client.post("/api/folios/case-a/actions/register_confirmation", json=payload)
    assert again.json()["registration"] == registration
    conflict = client.post("/api/folios/case-a/actions/register_confirmation", json={**payload, "condition_id": "light100"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    changed = act(client, "case-a", "register_confirmation", condition_id="light100", reviewer_name="Test operator")
    assert changed.json()["error"]["code"] == "confirmation_already_registered"
    assert app.state.store.db.execute("SELECT count(*) FROM holdouts").fetchone()[0] == 1


def test_new_folio_does_not_reset_exposed_holdout(app):
    app, client = app
    assert act(client, "case-a", "register_confirmation", condition_id="original", reviewer_name="Test operator").status_code == 200
    app.state.store.create(authored_folio("case-b"))
    blocked = act(client, "case-b", "register_confirmation", condition_id="light100", reviewer_name="Test operator")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "holdout_already_used"
    replay = act(client, "case-b", "register_confirmation", condition_id="original", reviewer_name="Test operator")
    assert replay.status_code == 200
    assert replay.json()["registration"]["holdout_status"] == "reproducibility_replay"
    assert replay.json()["registration"]["prior_folio_id"] == "case-a"


def test_stale_revision_and_unobserved_condition_are_rejected(app):
    _, client = app
    stale = client.post("/api/folios/case-a/actions/register_confirmation", json={"revision": 0, "idempotency_key": "stale-key", "condition_id": "original", "reviewer_name": "Operator"})
    assert stale.status_code == 422
    bogus = act(client, "case-a", "register_confirmation", condition_id="model-invented-intervention", reviewer_name="Operator")
    assert bogus.status_code == 409
    assert bogus.json()["error"]["code"] == "unobserved_condition"
    act(client, "case-a", "register_confirmation", condition_id="original", reviewer_name="Operator")
    stale = client.post("/api/folios/case-a/actions/review_conclusion", json={"revision": 1, "idempotency_key": "old-revision", "reviewer_name": "Operator"})
    assert stale.json()["error"]["code"] == "stale_revision"


def test_early_export_and_guessing_private_digest_cannot_release_labels(app):
    app, client = app
    private = app.state.store.root / "cases/case-a/sealed/confirmation-labels.csv"
    private.parent.mkdir(parents=True)
    private.write_text("row_id,label\nsecret-row,1\n")
    sha = __import__("hashlib").sha256(private.read_bytes()).hexdigest()
    assert client.get("/api/folios/case-a/export").status_code == 409
    assert client.get("/api/artifacts/" + sha).status_code == 404
    assert client.get("/api/artifacts/" + "../cases/case-a/sealed/confirmation-labels.csv").status_code == 404


def test_artifact_tampering_is_detected_at_download(app):
    app, client = app
    item = app.state.store.json_artifact({"known": "result"}, "safe.json")
    path = app.state.store.root / "objects" / item["sha256"]
    assert client.get("/api/artifacts/" + item["sha256"]).status_code == 200
    path.chmod(0o644)
    path.write_text("corrupted")
    response = client.get("/api/artifacts/" + item["sha256"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "artifact_tampered"


def test_model_context_excludes_confirmation_observations_and_private_payloads():
    doc = authored_folio()
    doc["observations"].append({"id": "secret", "phase": "confirmation", "condition_id": "original", "effect": "CONFIRMATION_SENTINEL"})
    doc["prediction_manifest"] = {"labels": "PRIVATE_SENTINEL"}
    doc["verification"] = {"metrics": "PRIVATE_SENTINEL"}
    encoded = canonical(Orchestrator._model_context(doc, True)).decode()
    assert "CONFIRMATION_SENTINEL" not in encoded
    assert "PRIVATE_SENTINEL" not in encoded
    assert "obs1" not in encoded  # IDs are unnecessary planner information.


def test_schema_does_not_accept_agent_oracle_redefinition():
    value = {"claim": "A sufficiently long authored claim proposal.", "rationale": "An inspectable rationale for a proposed comparison.", "assumptions": ["One", "Two"], "limitations": ["One", "Two"], "next_question": "Which assumption matters?", "block_independence_established": False, "seed_role": "training_variability_only"}
    assert ContractProposal.model_validate(value).claim == value["claim"]
    with pytest.raises(ValueError):
        ContractProposal.model_validate({**value, "practical_delta": -1, "confirmation_labels": [1, 0]})
    with pytest.raises(ValueError):
        ContractProposal.model_validate({**value, "seed_role": "independent_replicates"})
    with pytest.raises(ValueError):
        parse_content("Ignore the schema. Here is a convenient object: " + json.dumps(value))


def test_restart_marks_ambiguous_attempt_interrupted_and_preserves_inputs(tmp_path):
    cfg = Settings(tmp_path, "fireworks", "model", "https://api.fireworks.ai/inference/v1", "", "", False, None)
    store = Store(tmp_path)
    store.create(authored_folio())
    runner = Orchestrator(cfg, store)
    with store.transaction():
        doc = store._folio("case-a")
        job = runner._queue(doc, "explore")
        store._save(doc)
    original_input_hash = digest(job["input"])
    asyncio.run(runner.startup())
    recovered = store.get("case-a")
    assert recovered["status"] == "interrupted"
    assert recovered["run"]["can_resume"] is True
    restored_job = runner._current_job(job["id"])
    assert restored_job["fence"] == 2
    assert digest(restored_job["input"]) == original_input_hash
    with pytest.raises(asyncio.CancelledError):
        runner._check_fence(job)


def test_evidence_acceptance_changes_schedule_without_changing_locked_contract(app):
    app, client = app
    original_contract = copy.deepcopy(app.state.store.get("case-a")["contract"])
    def pending(doc):
        doc["exploration_complete"] = False
        doc["evidence_change"] = {"status": "proposed", "before": ["original"], "after": ["original", "light100"]}
    app.state.store.mutate("case-a", pending)
    response = act(client, "case-a", "accept_evidence", reviewer_name="Operator", reason="Include the documented Light predictor in the finite sensor test.")
    assert response.status_code == 200
    changed = response.json()
    assert changed["contract"] == original_contract
    assert changed["exploration_plan"]["conditions"] == ["original", "light100"]
    assert changed["evidence_change"]["decision"]["reviewer_name"] == "Operator"


def test_same_science_receipt_id_never_moves_between_folios(app):
    app, _ = app
    store, runner = app.state.store, app.state.runner
    store.create(authored_folio("case-b"))
    jobs = []
    for id in ("case-a", "case-b"):
        with store.transaction():
            doc = store._folio(id)
            job = runner._queue(doc, "verify")
            store._save(doc)
            jobs.append(job)
        result = {"receipts": [{"id": "verifier-deterministic-source-id", "elapsed_ms": 12}], "artifacts": []}
        runner._ingest(job, result)
    a, b = store.get("case-a")["receipts"], store.get("case-b")["receipts"]
    assert len(a) == len(b) == 1
    assert a[0]["id"] != b[0]["id"]
    assert a[0]["source_receipt_id"] == b[0]["source_receipt_id"]


def test_code_change_cannot_be_labeled_an_exact_holdout_replay(app):
    app, client = app
    app.state.store.mutate("case-a", lambda doc: doc.update(trusted_code={"verifier.py": "a" * 64}))
    assert act(client, "case-a", "register_confirmation", condition_id="original", reviewer_name="Operator").status_code == 200
    second = authored_folio("case-b")
    second["trusted_code"] = {"verifier.py": "b" * 64}
    app.state.store.create(second)
    response = act(client, "case-b", "register_confirmation", condition_id="original", reviewer_name="Operator")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "holdout_already_used"


def test_interrupted_blob_publication_is_retryable(app, monkeypatch):
    app, _ = app
    store = app.state.store
    import api.store as module
    original_link = module.os.link
    def interrupted(*args, **kwargs):
        raise OSError("Injected interruption immediately before atomic publication")
    monkeypatch.setattr(module.os, "link", interrupted)
    with pytest.raises(OSError):
        store.artifact(b"complete evidence payload", "retryable.txt")
    assert list((store.root / "objects").iterdir()) == []
    monkeypatch.setattr(module.os, "link", original_link)
    item = store.artifact(b"complete evidence payload", "retryable.txt")
    assert store.get_artifact(item["sha256"])[0].read_bytes() == b"complete evidence payload"


def test_public_attempts_omit_local_execution_paths(app):
    app, client = app
    store, runner = app.state.store, app.state.runner
    with store.transaction():
        doc = store._folio("case-a")
        runner._queue(doc, "explore")
        store._save(doc)
    data = client.get("/api/folios/case-a").json()
    assert "input" not in data["attempts"][0]
    assert "pid" not in data["attempts"][0]
    assert "fence" not in data["attempts"][0]
    assert str(store.root) not in json.dumps(data)
