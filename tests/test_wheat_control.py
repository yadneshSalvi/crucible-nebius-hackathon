"""Custody/planning regressions. Fixtures are engineering data, not results."""
import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from api.config import Settings
from api.main import create_app
from api.store import Conflict, Store, digest
from api.wheat import WheatOrchestrator
from api.wheat_protocol import FINAL_CONTROLS, STUDY_ID, initial_study


def settings(root):
    return Settings(root, "fireworks", "accounts/fireworks/models/nemotron-3-ultra-nvfp4",
                    "https://api.fireworks.ai/inference/v1", "", "", False, None)


@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUCIBLE_WHEAT_MANIFEST", str(tmp_path / "missing-assets/manifest.json"))
    monkeypatch.setenv("CRUCIBLE_WHEAT_INITIALIZATION", str(tmp_path / "missing-assets/initialization.json"))
    store = Store(tmp_path / "runtime")
    runner = WheatOrchestrator(settings(store.root), store)
    runner.ensure()
    yield runner, store
    store.close()


def completed_discovery():
    doc = initial_study()
    doc.update(prepared=True, contract_sha256="1" * 64, confirmation_split_sha256="2" * 64,
               numerical_spec_sha256="3" * 64, trusted_code_sha256="4" * 64,
               final_pixel_hashes=["5" * 64, "6" * 64], source_compilation={"status": "succeeded", "packet_sha256": "95930c9ac197c21dbd6f62326954c706630c4bbba82deec7fc19dcda51ba84a4"},
               contract={"locked": True, "metric": "descriptive_count_and_localization"})
    doc["training"].update(status="succeeded", checkpoint_sha256="7" * 64)
    doc["noop_equivalence"] = {"passed": True, "status": "passed", "scope": "Engineering fixture only"}
    doc["discovery_parents"] = {}
    for cell in doc["cells"]:
        cell.update(enabled=True, status="succeeded", aggregate={"n_images": 2, "n_sessions": 1, "count_mae": 4.0})
        doc["discovery_parents"][cell["id"]] = digest({"engineering_fixture": cell["id"]})
    return doc


def save(store, doc):
    with store.transaction():
        store._save(doc, advance=False)


def action(runner, name, **extra):
    doc = runner.public()
    return asyncio.run(runner.action(name, {"revision": doc["revision"], "idempotency_key": uuid.uuid4().hex, **extra}))


def test_missing_images_never_become_prepared_or_run(controller):
    runner, _ = controller
    doc = runner.public()
    assert not doc["prepared"] and doc["asset"] is None
    assert {"prepare", "train", "run_cell", "plan_next", "register", "evaluate"}.isdisjoint(doc["capabilities"])
    assert all(cell["metrics"] is None and cell["predictions"] == [] for cell in doc["cells"])
    with pytest.raises(Conflict) as caught:
        action(runner, "train")
    assert caught.value.code == "wheat_action_gated"


def test_preparation_preserves_only_same_released_discovery_annotations():
    from api.wheat import _preserve_released_illustration
    previous = {"id": "known", "sha256": "a" * 64, "split": "discovery", "ground_truth_released": True,
                "targets": [{"id": "target-0", "bbox": [1, 2, 3, 4]}], "license": "Original attribution"}
    prepared = {"id": "known", "sha256": "a" * 64, "split": "discovery", "ground_truth_released": False, "targets": []}
    preserved = _preserve_released_illustration(previous, prepared)
    assert preserved["ground_truth_released"] and preserved["targets"] == previous["targets"]
    assert preserved["license"] == previous["license"]
    preserved["targets"][0]["bbox"][0] = 999
    assert previous["targets"][0]["bbox"][0] == 1
    for changed in ({"id": "different"}, {"sha256": "b" * 64}, {"ground_truth_released": False}, {"split": "final"}):
        assert _preserve_released_illustration({**previous, **changed}, prepared) == prepared
    final = {**prepared, "split": "final"}
    assert _preserve_released_illustration(previous, final) == final


@pytest.mark.parametrize("mask", ["3", "GPU-assigned-fixture", ""])
def test_both_worker_hops_preserve_gpu_assignment_without_credentials(controller, monkeypatch, mask):
    from science.wheat import _minimal_environment
    runner, _ = controller
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", mask)
    monkeypatch.setenv("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    monkeypatch.setenv("NEBIUS_API_KEY", "fixture-secret-never-forward")
    captured = {}

    class CapturedEnvironment(Exception):
        pass

    async def intercept(*args, **kwargs):
        captured.update(kwargs["env"])
        raise CapturedEnvironment()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", intercept)
    runner.python = __import__("pathlib").Path(__import__("sys").executable)
    with pytest.raises(CapturedEnvironment):
        asyncio.run(runner._science({"id": "gpu-assignment-fixture", "input": {}}, "train"))
    for environment in (captured, _minimal_environment()):
        assert environment["CUDA_VISIBLE_DEVICES"] == mask
        assert environment["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
        assert "NEBIUS_API_KEY" not in environment


def test_final_family_binds_pixels_across_changed_manifests(controller):
    runner, store = controller
    save(store, completed_discovery())
    first = action(runner, "register", cell_id="retain_512")
    assert first["registration"]["configuration"]["family"] == ["retain_512", *FINAL_CONTROLS]
    assert first["registration"]["requirement"]["practitioner_threshold"] is None
    assert store.db.execute("SELECT count(*) FROM wheat_exposures").fetchone()[0] == 2
    assert {"run_cell", "plan_next", "train", "register"}.isdisjoint(first["capabilities"])
    altered = completed_discovery()
    altered["confirmation_split_sha256"] = "a" * 64
    with store.transaction(), pytest.raises(Conflict) as caught:
        runner._register(altered, "retain_256")
    assert caught.value.code == "image_already_registered"
    assert store.db.execute("SELECT count(*) FROM holdouts").fetchone()[0] == 1


def test_final_policy_idempotency_and_immutability(controller):
    runner, store = controller
    save(store, completed_discovery())
    body = {"revision": runner.public()["revision"], "idempotency_key": "one-scientific-registration", "cell_id": "native_tiles"}
    one = asyncio.run(runner.action("register", body))
    two = asyncio.run(runner.action("register", body))
    assert one["registration"] == two["registration"]
    with pytest.raises(Conflict) as caught:
        asyncio.run(runner.action("register", {**body, "cell_id": "retain_256"}))
    assert caught.value.code == "idempotency_conflict"
    assert one["registration"]["configuration"]["family"] == ["native_tiles", "native_full", "native_multiscale"]


def test_contexts_exclude_final_labels_images_and_private_receipts(controller):
    runner, _ = controller
    doc = completed_discovery()
    doc["final_evaluation"] = {"target_boxes": "SEALED-FINAL-LABELS"}
    doc["receipts"] = [{"request_payload": "SEALED-RAW-REQUEST"}]
    doc["private_image_path"] = "SEALED-FINAL-IMAGE"
    doc["cells"][4].update(status="unrun", aggregate=None)
    source = runner.source_context(doc)
    planner = runner.planner_context(doc)
    assert "SEALED-" not in json.dumps([source, planner])
    assert [cell["cell_id"] for cell in planner["unrun_candidates"]] == ["retain_256"]
    assert all("value" not in field for field in source["required_fields"])
    assert "source_fields" not in source and "executed_contract" not in source
    assert {field["field"] for field in source["required_fields"]} == {
        "original_epochs", "original_learning_rate", "original_weight_decay",
        "current_epochs", "current_learning_rate", "current_weight_decay"}


def test_planner_rejects_completed_and_disabled_cells(controller):
    runner, store = controller
    doc = completed_discovery()
    save(store, doc)
    assert "plan_next" not in runner.public()["capabilities"]
    doc["cells"][4].update(status="unrun", aggregate=None)
    doc["cells"][5].update(status="disabled", enabled=False, aggregate=None)
    save(store, doc)
    assert "plan_next" in runner.public()["capabilities"]
    assert [row["cell_id"] for row in runner.planner_context(doc)["unrun_candidates"]] == ["retain_256"]
    with pytest.raises(Conflict) as caught:
        action(runner, "run_cell", cell_id="native_full")
    assert caught.value.code == "cell_not_unrun"


def test_stale_plan_does_not_execute_after_new_evidence(controller):
    runner, store = controller
    doc = completed_discovery()
    doc["cells"][4].update(status="unrun", aggregate=None)
    context = runner.planner_context(doc)
    doc["planning"] = {"status": "proposed", "next_cell_id": "retain_256", "discovery_signature": digest(context["released_discovery_aggregates"])}
    doc["cells"][0]["aggregate"]["count_mae"] = 9.0
    save(store, doc)
    with pytest.raises(Conflict) as caught:
        action(runner, "execute_plan")
    assert caught.value.code == "planner_context_changed"


def test_opening_is_durable_and_legacy_exposure_survives(controller):
    runner, store = controller
    save(store, completed_discovery())
    with store.transaction():
        store.db.execute("INSERT INTO holdouts VALUES(?,?,?,?)", ("legacy-split", "legacy-signature", "occupancy", "{}"))
    action(runner, "register", cell_id="native_full")
    with store.transaction():
        doc = store._folio(STUDY_ID)
        job = runner._queue(doc, "evaluate")
        store._save(doc)
    runner._mark_opening(job)
    first = runner.public()["custody"]["opened_at"]
    runner._mark_opening(job)
    assert runner.public()["custody"]["opened_at"] == first
    assert store.db.execute("SELECT count(*) FROM wheat_exposures WHERE opened_at IS NOT NULL").fetchone()[0] == 2
    assert store.db.execute("SELECT signature FROM holdouts WHERE split_sha='legacy-split'").fetchone()[0] == "legacy-signature"


def test_api_blocks_arbitrary_inputs_and_keeps_wheat_out_of_legacy_history(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUCIBLE_WHEAT_MANIFEST", str(tmp_path / "no-assets/manifest.json"))
    app = create_app(settings(tmp_path / "runtime"), seed=False)
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        doc = client.get("/api/wheat").json()
        payload = {"revision": doc["revision"], "idempotency_key": "malicious-extra-field", "cell_id": "native_full",
                   "source_url": "http://169.254.169.254", "threshold": 0.1}
        response = client.post("/api/wheat/actions/run_cell", headers={"X-Crucible-Session": token}, json=payload)
        assert response.status_code == 422
        assert client.get("/api/folios").json() == {"folios": []}
        assert client.get("/api/wheat/export").status_code == 409


def test_final_requires_audited_pixel_identities(controller):
    runner, store = controller
    doc = completed_discovery()
    doc["final_pixel_hashes"] = []
    save(store, doc)
    with pytest.raises(Conflict) as caught:
        action(runner, "register", cell_id="native_full")
    assert caught.value.code == "custody_identity_missing"


def test_noop_must_pass_before_registration(controller):
    runner, store = controller
    doc = completed_discovery()
    doc["noop_equivalence"] = {"passed": False, "status": "not_established"}
    save(store, doc)
    assert "register" not in runner.public()["capabilities"]
    with pytest.raises(Conflict) as caught:
        runner._register(doc, "native_full")
    assert caught.value.code == "noop_verification_required"
    assert store.db.execute("SELECT count(*) FROM wheat_exposures").fetchone()[0] == 0


def test_unverified_discovery_is_never_released(controller):
    runner, _ = controller
    doc = completed_discovery()
    with pytest.raises(Conflict) as caught:
        runner._release_discovery(doc, {"verification": {"status": "failed"}}, "native_full")
    assert caught.value.code == "discovery_verification_required"


def test_legacy_routes_cannot_read_or_control_wheat(tmp_path):
    app = create_app(settings(tmp_path / "runtime"), seed=False)
    with TestClient(app) as client:
        doc = client.get("/api/wheat").json()
        token = client.get("/api/session").json()["token"]
        before = digest(app.state.store.get(STUDY_ID))
        for suffix in ("", "/events", "/report", "/export"):
            response = client.get("/api/folios/" + STUDY_ID + suffix)
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "legacy_adapter_required"
        for action_name in ("cancel", "resume", "reproduce", "verify"):
            response = client.post(f"/api/folios/{STUDY_ID}/actions/{action_name}", headers={"X-Crucible-Session": token},
                                   json={"revision": doc["revision"], "idempotency_key": "cross-route-" + action_name})
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "legacy_adapter_required"
        assert digest(app.state.store.get(STUDY_ID)) == before
        assert app.state.store.db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0


@pytest.mark.parametrize("verdict", ["verified", "failed"])
def test_final_flow_predicts_before_opening_and_requires_verified_result(controller, monkeypatch, verdict):
    runner, store = controller
    save(store, completed_discovery())
    action(runner, "register", cell_id="native_full")
    with store.transaction():
        doc = store._folio(STUDY_ID)
        job = runner._queue(doc, "evaluate")
        store._save(doc)
    stages = []
    async def worker(job, stage):
        stages.append(stage)
        if stage == "predict":
            assert runner.public()["custody"].get("opened_at") is None
            return {"prediction_manifest": {"engineering_fixture": True}}
        assert runner.public()["custody"]["opened_at"] is not None
        return {"verification": {"status": verdict, "metric_audit": {"final_family_frozen": True}}}
    monkeypatch.setattr(runner, "_science", worker)
    monkeypatch.setattr(runner, "_ingest", lambda job, result: result)
    asyncio.run(runner._execute(job))
    result = runner.public()
    assert stages == ["predict", "verify"]
    assert result["run"]["status"] == ("succeeded" if verdict == "verified" else "failed")
    assert (result.get("verification") is not None) == (verdict == "verified")
    assert result["custody"]["opened_at"] is not None
    if verdict == "verified":
        runner._materialize_workflow_evidence()
        evidence = json.loads((runner.case_root / "workflow/frozen-workflow.json").read_text())
        assert digest(evidence) == result["registration"]["configuration"]["workflow_evidence_sha256"]
        assert evidence["selected_parent_sha256"] == result["scientific_registration"]["parent_discovery_sha256"]
        custody = json.loads((runner.case_root / "workflow/final-custody.json").read_text())
        assert all(row["opened_at"] for row in custody["pixel_exposures"])
