"""Durable control plane for the fixed, trusted wheat experiment.

The model chooses an unrun discovery recipe. The numerical worker owns fitting,
box predictions and metrics; the model never receives final images or labels.
"""
from __future__ import annotations

import asyncio
import copy
import csv
import hashlib
import json
import os
import signal
import struct
import sys
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .config import PROJECT, Settings
from .orchestrator import ACTIVE, Orchestrator, ScienceError
from .providers import ProviderError
from .store import Conflict, Store, canonical, digest, now
from .wheat_protocol import FINAL_CONTROLS, LIMITATIONS, RECIPE_IDS, STUDY_ID, TILED_RECIPES, initial_study, source_fields
from .wheat_providers import SOURCE_EXTRACTION_PROFILE, SOURCE_EXTRACTION_RULES, WheatGateway, WheatPlan, WheatSources


def _require(condition, code: str, message: str):
    if not condition:
        raise Conflict(code, message)


def _preserve_released_illustration(previous: dict, prepared: dict) -> dict:
    if (previous.get("ground_truth_released") is True and previous.get("split") == "discovery" and prepared.get("split") == "discovery"
            and previous.get("id") == prepared.get("id") and previous.get("sha256") == prepared.get("sha256")):
        fields = ("ground_truth_released", "targets", "license", "attribution", "source_url", "selection_rule")
        return {**prepared, **copy.deepcopy({key: previous[key] for key in fields if key in previous})}
    return prepared


class WheatOrchestrator(Orchestrator):
    def __init__(self, settings: Settings, store: Store):
        super().__init__(settings, store)
        self.case_root = store.root / "cases" / STUDY_ID
        self.source_manifest = settings.wheat_manifest or (store.root / "wheat-assets/manifest.json")
        self.initialization_manifest = settings.wheat_initialization or (self.source_manifest.parent / "initialization.json")
        self.python = settings.wheat_python or (PROJECT / ".venv-wheat/bin/python")
        self.source_packet_path = PROJECT / "docs/wheat-source-packet.json"
        self.store.db.executescript("""
          CREATE TABLE IF NOT EXISTS wheat_exposures(
            image_sha TEXT PRIMARY KEY, signature TEXT NOT NULL, folio_id TEXT NOT NULL,
            registered_at TEXT NOT NULL, opened_at TEXT, registration TEXT NOT NULL);
        """)

    def ensure(self):
        try:
            doc = self.store.get(STUDY_ID)
        except KeyError:
            self.store.create(initial_study())
            doc = self.store.get(STUDY_ID)
        if doc.get("asset") is None:
            self._publish_discovery_illustration()
        elif (doc.get("prepared") and doc["asset"].get("ground_truth_released") is False and doc["asset"].get("split") == "discovery"
              and doc["asset"].get("sha256") == "2454d9090c4fafadd7c7d24840eb1d2e049b7c9fc2f7f4fb3fb78a84ad0fa917"
              and any(item.get("kind") == "source_selection" for item in doc.get("artifacts", []))):
            self._publish_discovery_illustration(restoring=True)
        if not doc.get("prepared") and not doc.get("source_compilation"):
            known = {field["key"] for field in doc["source_fields"]}
            additions = [field for field in source_fields() if field["key"] not in known]
            if additions:
                self.store.mutate(STUDY_ID, lambda current: current["source_fields"].extend(additions),
                                  ("source_packet_extended", "Additional primary-source ambiguity recorded before preparation or fitting."))
        if doc.get("source_compilation") and not doc["source_compilation"].get("method"):
            def label_previous(current):
                current["source_compilation"]["method"] = "audited_summary_structuring"
                current["source_compilation"]["method_label"] = "Audited-summary structuring; expected values were supplied to this historical call"
                current.setdefault("source_compilation_history", []).append(copy.deepcopy(current["source_compilation"]))
            self.store.mutate(STUDY_ID, label_previous, ("source_method_clarified", "Historical source call labeled as audited-summary structuring; its exact request, response and usage remain retained."))

    def _publish_discovery_illustration(self, restoring=False):
        """Release only the preselected discovery photo while full bytes wait."""
        assets = self.source_manifest.parent
        selection_file = assets / "illustration-selection.json"
        source_csv = assets / "primary/gwhd_2021/competition_train.csv"
        if not selection_file.is_file() or not source_csv.is_file():
            return
        selection = json.loads(selection_file.read_text())
        _require(selection.get("session_id") == "Rres_1" and selection.get("detector_outcomes_seen") is False,
                 "illustration_selection_invalid", "The pre-outcome discovery illustration selection changed.")
        _require(hashlib.sha256(source_csv.read_bytes()).hexdigest() == selection["source_csv_sha256"],
                 "illustration_source_changed", "The selected discovery annotation source failed its retained digest.")
        image_name = selection["image_id"]
        _require(Path(image_name).name == image_name, "illustration_path_invalid", "Illustration must be a fixed archive filename.")
        path = assets / "primary/gwhd_2021/images" / image_name
        if not path.is_file():
            return
        content = path.read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        _require(sha == "2454d9090c4fafadd7c7d24840eb1d2e049b7c9fc2f7f4fb3fb78a84ad0fa917",
                 "illustration_image_changed", "The designated official discovery image differs from the qualified primary bytes.")
        _require(content[:8] == b"\x89PNG\r\n\x1a\n", "illustration_format_invalid", "Qualified illustration is not a PNG.")
        width, height = struct.unpack(">II", content[16:24])
        with source_csv.open(newline="") as stream:
            selected = next((row for row in csv.DictReader(stream) if row["image_name"] == image_name), None)
        _require(selected is not None and selected["domain"] == selection["session_id"],
                 "illustration_identity_invalid", "The illustration's released session annotation did not match its selection.")
        targets = []
        if selected["BoxesString"] != "no_box":
            for index, raw in enumerate(selected["BoxesString"].split(";")):
                box = [int(value) for value in raw.split()]
                _require(len(box) == 4 and 0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height,
                         "illustration_boxes_invalid", "A selected discovery box failed the documented continuous-xyxy bounds.")
                targets.append({"id": f"target-{index}", "bbox": self._xywh(box)})
        image_artifact = self.store.artifact(content, image_name, "released_discovery_image", "image/png")
        receipt = self.store.json_artifact({**selection, "image_sha256": sha, "target_count": len(targets),
            "coordinate_schema": "Official BoxesString continuous xyxy converted to UI xywh; source values retained",
            "detection_status": "No detector predictions or experiment measurements exist"}, "wheat-discovery-illustration.json", "source_selection")
        def publish(doc):
            if restoring:
                _require(doc.get("asset", {}).get("id") == Path(image_name).stem and doc["asset"].get("sha256") == sha and doc["asset"].get("split") == "discovery",
                         "illustration_identity_invalid", "Previously released annotations cannot attach to a different prepared photograph.")
            doc["asset"] = {"id": Path(image_name).stem, "url": "/api/artifacts/" + sha, "width": width, "height": height,
                "sha256": sha, "license": "Zenodo: CC BY 4.0; WILDS description: MIT. Both source statements retained.",
                "attribution": "Global Wheat Head Dataset 2021 contributors · Rothamsted Research · Rres_1",
                "source_url": "https://zenodo.org/records/5092309", "session_id": "Rres_1", "split": "discovery",
                "ground_truth_released": True, "targets": targets, "selection_rule": selection["selection_rule"]}
            known = {item["sha256"] for item in doc["artifacts"]}
            doc["artifacts"].extend(item for item in (image_artifact, receipt) if item["sha256"] not in known)
            if not any(field.get("key") == "illustration_selection" for field in doc["source_fields"]):
                doc["source_fields"].append({"key": "illustration_selection", "label": "Preselected discovery photograph", "candidates": [],
                "status": "reviewer_chosen", "selected_value": image_name,
                "reason": "Lexicographically first image in the declared Rres_1 development session, selected before detector outcomes. Authentic source boxes are released; detector results remain unrun."})
        event = ("discovery_source_restored", "Previously released discovery annotations and attribution restored after preparation; no new labels or predictions released.") if restoring else ("discovery_source_released", "Qualified discovery photograph and its source annotations released; no predictions fabricated.")
        self.store.mutate(STUDY_ID, publish, event)

    def public(self) -> dict:
        self.ensure()
        doc = self.store.get(STUDY_ID)
        doc["capabilities"] = self.capabilities(doc)
        for artifact in doc.get("artifacts", []):
            artifact.setdefault("url", "/api/artifacts/" + artifact["sha256"])
        for receipt in doc.get("receipts", []):
            # Exact request bodies remain in immutable evidence, available on
            # demand. Keep the first screen compact and avoid leaking paths.
            receipt.pop("request_payload", None)
        if doc.get("run") and isinstance(doc["run"].get("error"), dict):
            doc["run"]["error"] = doc["run"]["error"].get("message")
        for private_key in ("final_image_hashes", "final_pixel_hashes", "source_snapshot_dir"):
            doc.pop(private_key, None)
        catalog_path = self.source_manifest.parent / "catalog.pending.json"
        if not doc.get("prepared") and catalog_path.is_file():
            catalog = json.loads(catalog_path.read_text())
            count = len(catalog.get("images", []))
            missing = len(catalog.get("missing_images", []))
            available = count > 0 and missing == 0
            doc["source_readiness"] = {"status": "available" if available else "incomplete", "required_images": count, "missing_images": missing,
                "available_images": count - missing, "detail": (
                    "All declared source photographs are available. Study preparation must recheck and freeze the source inputs before fitting. Detector training has not run."
                    if available else
                    "The full declared corpus must pass source-byte, dimension and duplicate checks before fitting. No smaller corpus is silently substituted.")}
            doc["training"]["detail"] = (
                f"All {count:,} declared source photographs are available. Study preparation and detector training remain pending."
                if available else
                f"{missing:,} of {count:,} declared source photographs are not yet available. Full-corpus preparation and real training remain gated.")
        return doc

    def capabilities(self, doc: dict) -> list[str]:
        active = bool(doc.get("run") and doc["run"]["status"] in ACTIVE)
        if active:
            return ["cancel"] if doc["run"]["status"] != "cancel_requested" else []
        allowed = []
        if doc.get("run") and doc["run"].get("can_resume"):
            allowed.append("resume")
        if self.source_packet_path.is_file() and ((doc.get("source_compilation") or {}).get("packet_sha256") != hashlib.sha256(self.source_packet_path.read_bytes()).hexdigest() or (doc.get("source_compilation") or {}).get("profile") != SOURCE_EXTRACTION_PROFILE):
            allowed.append("compile_sources")
        if doc["registration"]["status"] == "not_registered":
            if not doc.get("evidence_change"):
                allowed.append("retrieve")
            elif doc["evidence_change"]["status"] == "proposed":
                allowed += ["accept_evidence", "reject_evidence"]
        if not doc.get("prepared"):
            if self.source_manifest.is_file() and self.python.is_file():
                allowed.append("prepare")
            return allowed
        frozen = doc["registration"]["status"] != "not_registered"
        if doc["training"]["status"] != "succeeded":
            if (doc.get("source_compilation") or {}).get("profile") == SOURCE_EXTRACTION_PROFILE and self.initialization_manifest.is_file():
                allowed.append("train")
            return allowed
        if not frozen:
            unrun = [cell for cell in doc["cells"] if cell["enabled"] and cell["status"] == "unrun"]
            if unrun:
                allowed.append("run_cell")
            if unrun and any(cell["status"] == "succeeded" for cell in doc["cells"]):
                allowed.append("plan_next")
            if doc["planning"]["status"] == "proposed" and any(cell["id"] == doc["planning"]["next_cell_id"] for cell in unrun):
                allowed.append("execute_plan")
            done = {cell["id"] for cell in doc["cells"] if cell["status"] == "succeeded"}
            if set(FINAL_CONTROLS) | {"native_noop"} <= done and (doc.get("noop_equivalence") or {}).get("passed") is True:
                allowed.append("register")
        elif doc.get("verification") is None:
            allowed.append("evaluate")
        elif not doc.get("export_url"):
            allowed.append("build_export")
        return allowed

    def _queue(self, doc: dict, action: str, resume_from: dict | None = None, payload: dict | None = None) -> dict:
        payload = copy.deepcopy((resume_from or {}).get("payload", payload or {}))
        contract = copy.deepcopy(doc.get("contract", {}))
        input_data = {"root": str(self.case_root), "contract": contract, "reproduction_accepted": True,
                      "registration": doc.get("scientific_registration"), "device": self.settings.wheat_device,
                      "inference_device": self.settings.wheat_inference_device}
        if action == "prepare":
            input_data["source_manifest"] = str(self.source_manifest)
        if action == "train":
            _require(self.initialization_manifest.is_file(), "initialization_pending", "The official initialization has not yet been audited and pinned.")
            initialization = json.loads(self.initialization_manifest.read_text())
            if "path" in initialization and not Path(initialization["path"]).is_absolute():
                initialization["path"] = str((self.initialization_manifest.parent / initialization["path"]).resolve())
            input_data["initialization"] = initialization
        if action in {"run_cell", "execute_plan"}:
            input_data["recipe_ids"] = [payload["cell_id"]]
        job = {"id": uuid.uuid4().hex, "folio_id": STUDY_ID, "action": action, "payload": payload,
               "status": "queued", "fence": 1, "started_at": now(), "updated_at": now(), "heartbeat_at": now(),
               "checkpoint": "Queued; immutable action inputs retained", "completed_units": 0,
               "total_units": None, "unit_label": "stages", "attempt": (resume_from or {}).get("attempt", 0) + 1,
               "parent_attempt": (resume_from or {}).get("id"), "error": None, "can_resume": False, "input": input_data}
        self._save_job(job)
        doc.update(run=self._public_job(job), status="running")
        if action == "train":
            doc["training"]["status"] = "running"
        if action in {"run_cell", "execute_plan"}:
            next(cell for cell in doc["cells"] if cell["id"] == payload["cell_id"])["status"] = "running"
        self.store._event(STUDY_ID, "queued", action.replace("_", " ").capitalize() + " queued with frozen inputs.", job["id"])
        return job

    def _gateway(self, job: dict) -> WheatGateway:
        return WheatGateway(self.settings, lambda receipt: self.store.add_receipt(STUDY_ID, job["id"], receipt))

    @staticmethod
    def source_expectations(doc: dict) -> list[dict]:
        original = next(field for field in doc["source_fields"] if field["key"] == "original_run_identity")
        required = []
        for prefix, candidate in zip(("original", "current"), original["candidates"]):
            required += [{"field": f"{prefix}_{key}", "value": str(value), "source_id": candidate["url"], "locator": candidate["locator"]}
                         for key, value in candidate["value"].items()]
        return required

    def source_context(self, doc: dict) -> dict:
        packet_bytes = self.source_packet_path.read_bytes()
        packet_sha = hashlib.sha256(packet_bytes).hexdigest()
        _require(packet_sha == "95930c9ac197c21dbd6f62326954c706630c4bbba82deec7fc19dcda51ba84a4", "source_packet_changed", "Primary excerpt packet changed from the reviewed identity.")
        packet = json.loads(packet_bytes)
        return {
            "purpose": "Resolve original-versus-current protocol ambiguity without choosing settings by outcomes",
            "profile": SOURCE_EXTRACTION_PROFILE,
            "packet_sha256": packet_sha, "sources": packet["sources"], "required_fields": packet["required_fields"],
            "source_packet_limitations": packet["limitations"], "assets_prepared": bool(doc.get("prepared")),
            "trusted_facts": {"block_independence_established": False, "seed_role": "training_variability_only"},
            "experiment_kind": "new_source_informed_experiment", "exact_reproduction": "not_established",
            "review_status": "Automated local operator; independent reviewer/practitioner unavailable",
        }

    def validate_source_proposal(self, doc: dict, context: dict, proposal: dict):
        _require(proposal.get("conflict_classification") == "different_original_and_current_settings" and proposal.get("executed_settings") == "not_established_by_excerpts",
                 "source_scope_mismatch", "The source proposal misclassified the original/current conflict or inferred execution settings.")
        known_sources = {item["source_id"] for item in context["sources"]}
        _require(all(field["source_id"] in known_sources for field in proposal["fields"]),
                 "source_outside_packet", "The compiler cited a source outside the pinned packet.")
        actual = {field["field"]: field for field in proposal["fields"]}
        expected_fields = self.source_expectations(doc)
        _require(len(actual) == len(proposal["fields"]) == len(expected_fields),
                 "duplicate_source_field", "Source compiler returned duplicate or missing atomic fields.")
        for expected in expected_fields:
            field = actual.get(expected["field"])
            _require(field and field["source_id"] == expected["source_id"] and field["status"] == "source_supported",
                     "source_field_mismatch", "Source compiler omitted or misattributed a required original/current method field.")
            try:
                matches = Decimal(field["value"]) == Decimal(expected["value"])
            except InvalidOperation:
                matches = False
            _require(matches, "source_value_mismatch", "A proposed source value disagrees with the pinned audit.")

    @staticmethod
    def planner_context(doc: dict) -> dict:
        completed = [{"cell_id": cell["id"], "aggregate": cell["aggregate"], "recipe": cell["recipe_id"]}
                     for cell in doc["cells"] if cell["status"] == "succeeded"]
        candidates = [{"cell_id": cell["id"], "label": cell["label"], "retained_width": cell["retained_width"],
                       "recipe": next(recipe for recipe in doc["recipes"] if recipe["id"] == cell["id"])}
                      for cell in doc["cells"] if cell["enabled"] and cell["status"] == "unrun"]
        return {
            "question": doc["claim"], "experiment_kind": doc["experiment_kind"],
            "unrun_candidates": candidates, "released_discovery_aggregates": completed,
            "locked_protocol": doc["contract"], "source_fields": doc["source_fields"],
            "accepted_source_change": doc.get("evidence_change"),
            "remaining_budget": {"next_experiments": 1, "remaining_enabled_unrun": len(candidates), "policy": "One finite recipe; no metric, threshold, weights, training, or final-label changes"},
            "trusted_facts": {"block_independence_established": False, "seed_role": "training_variability_only"},
            "scope": "Fixed public discovery corpus; no independent acquisition inference, efficiency advantage, adoption, or novelty claim",
            "data_release": "Aggregates only. No final images/labels, image-level targets, credentials or arbitrary code.",
        }

    async def _science(self, job: dict, stage: str) -> dict:
        directory = self.store.root / "jobs" / job["id"]
        directory.mkdir(parents=True, exist_ok=True)
        request = directory / f"wheat-{stage}-request.json"
        result_path = directory / f"wheat-{stage}-result.json"
        request.write_bytes(canonical(job["input"]))
        _require(self.python.is_file(), "wheat_runtime_missing", "Install the pinned wheat worker runtime before execution.")
        argv = [str(self.python), "-m", "science.wheat_cli", stage, "--input", str(request), "--output", str(result_path)]
        env = {"PATH": os.environ.get("PATH", os.defpath), "LANG": "en_US.UTF-8", "TZ": "UTC",
               "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0",
               "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
               "VECLIB_MAXIMUM_THREADS": "1", "PYTORCH_ENABLE_MPS_FALLBACK": "1", "TMPDIR": str(directory)}
        env.update({key: os.environ[key] for key in ("CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER") if key in os.environ})
        started = now()
        process = await asyncio.create_subprocess_exec(*argv, cwd=PROJECT, env=env, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.PIPE, start_new_session=True)
        self.processes[job["id"]] = process
        with self.store.lock:
            current = self._current_job(job["id"])
            current["pid"] = process.pid
            self._save_job(current)
        try:
            # Explicit bounds are operational limits, never evidence against a
            # scientific hypothesis. The worker records finer measured timing.
            stdout, stderr = await asyncio.wait_for(process.communicate(), 86400 if stage == "train" else 21600)
        except (asyncio.CancelledError, TimeoutError):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
            if asyncio.current_task().cancelling():
                raise
            raise ScienceError("wheat_worker_timeout", "The frozen worker wall-time bound was exceeded. This is an execution failure, not a scientific result.")
        finally:
            self.processes.pop(job["id"], None)
        self._check_fence(job)
        def safe_log(value):
            text = value.decode(errors="replace")[-10000:]
            for path, label in ((str(self.case_root), "${CASE_ROOT}"), (str(directory), "${ATTEMPT}"),
                                (str(PROJECT), "${PROJECT}"), (str(Path.home()), "${HOME}")):
                text = text.replace(path, label)
            return text
        log = {"command": ["python", "-m", "science.wheat_cli", stage], "exit_code": process.returncode,
               "started_at": started, "finished_at": now(), "stdout": safe_log(stdout), "stderr": safe_log(stderr),
               "environment_keys": sorted(env), "isolation": "Credential-free trusted process; same OS identity; no arbitrary submitted code"}
        self._append_artifacts(STUDY_ID, [self.store.json_artifact(log, f"wheat-{stage}-execution.json", "execution")])
        result = json.loads(result_path.read_text()) if result_path.is_file() else {}
        if process.returncode != 0 or result.get("error"):
            error = result.get("error") or {}
            raise ScienceError(error.get("code", "wheat_worker_failed"), error.get("message", "The trusted wheat worker failed. Inspect the retained execution receipt."))
        return result

    def _ingest(self, job: dict, result: dict) -> dict:
        self._check_fence(job)
        metadata = []
        illustration_sha = (result.get("illustration", {}).get("image", {}).get("sha256") or
                            (self.store.get(STUDY_ID).get("asset") or {}).get("sha256"))
        for item in result.get("artifacts", []):
            # Weights stay within the trusted numerical case and portable export;
            # copying them into the browser object store wastes disk and is not
            # needed to inspect predictions. Sealed labels are never public here.
            if item.get("private") or item.get("sealed") or item.get("kind") in {"trained_detector", "initialization", "sealed_boxes"}:
                continue
            if item.get("media_type") == "application/zip" or str(item.get("path", "")).endswith((".zip", ".npz")):
                continue
            if item.get("kind") == "wheat_image" and item.get("sha256") != illustration_sha:
                continue
            relative = item.get("path")
            if not relative:
                continue
            path = (self.case_root / relative).resolve()
            if not path.is_relative_to(self.case_root.resolve()) or not path.is_file() or path.is_symlink():
                raise ScienceError("artifact_path_rejected", "Worker artifact is outside the trusted wheat case.")
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ScienceError("artifact_hash_mismatch", "Wheat evidence failed its content hash.")
            metadata.append(self.store.artifact(content, item.get("name", path.name), item.get("kind", "wheat_evidence"), item.get("media_type", "application/json")))
        released = {key: value for key, value in result.items() if key not in {"data_artifacts", "final_image_hashes", "final_pixel_hashes"}}
        metadata.append(self.store.json_artifact(released, f"wheat-{job['action']}-result.json", "result"))
        self._append_artifacts(STUDY_ID, metadata)
        for raw in result.get("receipts", []):
            receipt = {"kind": "computation", "provider": "local_python", "status": "succeeded", "purpose": job["action"],
                       "started_at": now(), **raw, "source_receipt_id": raw.get("id"), "id": str(uuid.uuid4())}
            self.store.add_receipt(STUDY_ID, job["id"], receipt)
        return result

    async def _execute(self, job: dict):
        heartbeat = None
        try:
            self._checkpoint(job, "Frozen inputs retained; " + job["action"].replace("_", " ") + " is running", 0)
            heartbeat = asyncio.create_task(self._heartbeat(job))
            action = job["action"]
            result = {}
            if action == "compile_sources":
                doc = self.store.get(STUDY_ID)
                context = self.source_context(doc)
                gateway = self._gateway(job)
                proposal = await gateway.model("wheat_primary_excerpt_extraction_v3", context, WheatSources,
                    SOURCE_EXTRACTION_RULES)
                try:
                    self.validate_source_proposal(doc, context, proposal)
                except Conflict as exc:
                    gateway.save_receipt({**gateway.last_receipt, "status": "proposal_rejected", "error": exc.message})
                    raise
                result["source_compilation"] = {"status": "succeeded", "compiled_at": now(), "context_sha256": digest(context),
                    "receipt_id": gateway.last_receipt["id"], "method": "primary_excerpt_extraction",
                    "profile": SOURCE_EXTRACTION_PROFILE,
                    "method_label": "Nemotron extracted six primary-source fields and classified the conflict; trusted code supplies execution scope",
                    "packet_sha256": context["packet_sha256"], **proposal,
                    "fields": [{**field, "locator": next(source["locator"] for source in context["sources"] if source["source_id"] == field["source_id"])} for field in proposal["fields"]],
                    "narrative_authority": "trusted_code", "experiment_kind": "new_source_informed_experiment", "reproduction_status": "not_established",
                    "conflict_resolution": "The validated original-supplement settings differ from the pinned current repository defaults. Source excerpts establish this version difference; they do not determine our executed choices. The authored training contract is separate and is frozen before fitting, with no selection by favorable outcomes.",
                    "unresolved": context["source_packet_limitations"],
                    "limitation": "This new source-informed experiment does not establish exact original commands, partitions, checkpoints, initialization or results. Independent reviewer/practitioner validation is unavailable."}
            elif action == "retrieve":
                retrieval = await self._gateway(job).retrieve_wheat()
                before = [cell["id"] for cell in self.store.get(STUDY_ID)["cells"] if cell["enabled"]]
                applicable = retrieval["source"] is not None
                result["evidence_change"] = {"id": uuid.uuid4().hex, "status": "proposed" if applicable else "context_only",
                    "query": retrieval["query"], "queried_at": retrieval["queried_at"], "source": retrieval["source"],
                    "before": before, "after": sorted(set(before) | TILED_RECIPES) if applicable else before,
                    "assumption": "A full-image resolution sweep alone cannot separate object-scale effects from pixels already discarded.",
                    "explanation": "Accepting the returned primary SAHI source enables the predeclared native and 256-pixel tiled recipes. Their actual inference compares retained detail with a known scale-processing intervention; no algorithmic novelty or pixel reconstruction is claimed." if applicable else "No returned primary source passed the fixed relevance check. Retrieval is context only; no recipe is enabled.",
                    "receipt_id": retrieval["receipt"]["id"], "decision": None}
            elif action == "plan_next":
                doc = self.store.get(STUDY_ID)
                context = self.planner_context(doc)
                gateway = self._gateway(job)
                proposal = await gateway.model("wheat_choose_unrun_experiment", context, WheatPlan,
                    "Choose exactly one cell_id from unrun_candidates. Every listed candidate is genuinely unrun; do not propose completed or disabled recipes. Record competing qualitative predictions BEFORE execution, unchanged image/weights/threshold/metric controls, resource requirement, and a reason the mechanism could remain unresolved. Source_basis must use supplied source URLs or the accepted retrieval URL. Tiling cannot recreate discarded pixels. The language model is not the detector or metric oracle. There is no efficiency evaluation or practitioner threshold; efficiency_claim must be not_established.")
                allowed = {item["cell_id"] for item in context["unrun_candidates"]}
                if proposal["cell_id"] not in allowed:
                    message = "Nemotron selected an unavailable or already-run cell. The proposal was retained but not accepted."
                    gateway.save_receipt({**gateway.last_receipt, "status": "proposal_rejected", "error": message})
                    raise Conflict("planner_selected_run_cell", message)
                result["planning"] = {"status": "proposed", "proposal": proposal["question"], "next_cell_id": proposal["cell_id"],
                    "planned_at": now(), "context_sha256": digest(context), "discovery_signature": digest(context["released_discovery_aggregates"]),
                    "rationale": proposal["rationale"], "competing_predictions": proposal["competing_predictions"],
                    "unchanged_controls": proposal["unchanged_controls"], "source_basis": proposal["source_basis"],
                    "resource_requirement": proposal["resource_requirement"], "remain_unresolved_if": proposal["remain_unresolved_if"],
                    "efficiency_claim": proposal["efficiency_claim"], "receipt_id": gateway.last_receipt["id"]}
            elif action == "evaluate":
                self._checkpoint(job, "Generating every registered final comparison; final labels have not been joined")
                prediction = self._ingest(job, await self._science(job, "predict"))
                self.store.mutate(STUDY_ID, lambda doc: doc.update(final_prediction_manifest=prediction.get("prediction_manifest")), advance=False)
                self._mark_opening(job)
                self._checkpoint(job, "Registration and prediction family sealed; separate verifier is opening final labels")
                result = self._ingest(job, await self._science(job, "verify"))
            else:
                stage = {"run_cell": "explore", "execute_plan": "explore", "build_export": "export"}.get(action, action)
                if action == "build_export":
                    self._materialize_workflow_evidence()
                result = self._ingest(job, await self._science(job, stage))
            self._complete(job, result)
        except asyncio.CancelledError:
            self._finish_failure(job, "interrupted" if self.closing else "cancelled", "cancelled",
                                 "Local operation stopped; completed immutable evidence is preserved. Remote billing/termination may be unknown.")
        except Exception as exc:
            self._finish_failure(job, "failed", getattr(exc, "code", "execution_failed"),
                                 getattr(exc, "message", "An operational step failed; inspect the retained attempt. No scientific outcome was inferred."))
            directory = self.store.root / "jobs" / job["id"]
            directory.mkdir(parents=True, exist_ok=True)
            message = str(exc).replace(str(Path.home()), "${HOME}")[:3000]
            (directory / "exception.json").write_bytes(canonical({"type": type(exc).__name__, "message": message}))
        finally:
            if heartbeat:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)

    def _finish_failure(self, job, status, code, message):
        with self.store.transaction():
            current = self._current_job(job["id"])
            current.update(status=status, updated_at=now(), heartbeat_at=now(), can_resume=True,
                           checkpoint="Attempt stopped; prior evidence and exposure history retained", error={"code": code, "message": message, "recoverable": True})
            self._save_job(current)
            doc = self.store._folio(STUDY_ID)
            if doc.get("run", {}).get("id") == job["id"]:
                doc.update(run=self._public_job(current), status=status)
                if job["action"] == "train":
                    doc["training"]["status"] = status
                if job["action"] in {"run_cell", "execute_plan"}:
                    cell = next(cell for cell in doc["cells"] if cell["id"] == job["payload"]["cell_id"])
                    cell.update(status="failed", error=message)
                self.store._save(doc)
                self.store._event(STUDY_ID, status, message, job["id"])

    def _mark_opening(self, job):
        self._check_fence(job)
        with self.store.transaction():
            doc = self.store._folio(STUDY_ID)
            opened_at = doc["custody"].get("opened_at") or now()
            self.store.db.execute("UPDATE wheat_exposures SET opened_at=COALESCE(opened_at,?) WHERE folio_id=? AND signature=?", (opened_at, STUDY_ID, doc["registration"]["signature"]))
            doc["custody"].update(status="opened_for_registered_verification", opened_at=opened_at,
                                  exposure_status="Registered public-benchmark final labels opened; never fresh or reusable for adaptive confirmation")
            self.store._save(doc)
            self.store._event(STUDY_ID, "final_labels_opening", "The full frozen family has predictions. Final-label opening recorded durably before the verifier starts.", job["id"])

    def _complete(self, job: dict, result: dict):
        self._check_fence(job)
        with self.store.transaction():
            doc = self.store._folio(STUDY_ID)
            action = job["action"]
            if action == "prepare":
                contract = copy.deepcopy(result["contract"])
                contract.update(locked=True, approval={"role": "automated_local_operator", "name": "Automated local implementation (agent)",
                    "timestamp": now(), "external_methodologist": "unavailable", "scope": "Authored fixed benchmark protocol; no independent scientific endorsement"})
                doc.update(prepared=True, contract=contract, source=result["source"], status="prepared",
                           contract_sha256=digest(contract), trusted_code=result["trusted_code"], trusted_code_sha256=result["trusted_code_sha256"],
                           numerical_spec_sha256=result["numerical_spec_sha256"], confirmation_split_sha256=result["confirmation_split_sha256"])
                for key in ("final_image_hashes", "final_pixel_hashes"):
                    doc[key] = result.get(key, [])
                doc["custody"].update(status="roles_frozen_before_fitting", dataset_fingerprint=result["manifest_sha256"],
                                     split_manifest_sha256=result["confirmation_split_sha256"], detail="Training, discovery and final roles fixed before fitting; final artifacts are not browser-accessible.")
                illustration = result.get("illustration", {})
                image = illustration.get("image", {})
                if image.get("sha256"):
                    prepared_asset = {"id": illustration["image_id"], "url": "/api/artifacts/" + image["sha256"],
                        "width": illustration["width"], "height": illustration["height"], "sha256": image["sha256"],
                        "license": str(result["source"].get("license", "Source license statements retained in audit")),
                        "attribution": str(result["source"].get("attribution", "Global Wheat Head Dataset contributors")),
                        "source_url": result["source"].get("url", "https://zenodo.org/records/5092309"),
                        "session_id": illustration["session_id"], "split": "discovery", "ground_truth_released": False,
                        "targets": [], "selection_rule": result.get("illustration_selection")}
                    doc["asset"] = _preserve_released_illustration(doc.get("asset") or {}, prepared_asset)
                training = contract.get("training", {})
                device_label = f"{self.settings.wheat_device.upper()} training / {self.settings.wheat_inference_device.upper()} inference"
                qualification = "software prepared; CUDA execution unqualified" if any(value.startswith("cuda:") for value in (self.settings.wheat_device, self.settings.wheat_inference_device)) else "actual execution receipts pending"
                doc["training"].update(detector=training.get("model", doc["training"]["detector"]), epochs=training.get("epochs", 10), device=f"{device_label} ({qualification})")
                doc["source_fields"].append({"key": "executed_training", "label": "Frozen authored detector protocol", "candidates": [],
                    "status": "reviewer_chosen", "selected_value": training,
                    "reason": "Frozen before fitting by the local automated operator. Dataset/initialization/implementation differences prevent an exact-paper reproduction claim."})
            elif action == "compile_sources":
                doc["source_compilation"] = result["source_compilation"]
                doc.setdefault("source_compilation_history", []).append(copy.deepcopy(result["source_compilation"]))
                doc["status"] = "source_contract_ready"
            elif action == "train":
                doc["training"].update(status="succeeded", checkpoint_sha256=result["checkpoint_set_sha256"],
                    checkpoint_set_sha256=result["checkpoint_set_sha256"], seeds=[row["seed"] for row in result["checkpoints"]],
                    detail="Three fixed training seeds completed. Every recipe uses the same respective final checkpoint; metrics average seeds within image. Illustration seed11 was fixed before outcomes; no ensemble or validation selection.")
                actual_receipts = list(self.store.db.execute("SELECT doc FROM receipts WHERE folio_id=? AND job_id=? ORDER BY rowid DESC", (STUDY_ID, job["id"])))
                if actual_receipts:
                    doc["training"]["receipt_id"] = json.loads(actual_receipts[0][0])["id"]
                doc["training_result"] = {key: value for key, value in result.items() if key in {"checkpoint_set_sha256", "checkpoints", "training_receipts", "replay"}}
                doc["status"] = "discovery_ready"
            elif action == "retrieve":
                doc["evidence_change"] = result["evidence_change"]
                doc["evidence_history"].append(copy.deepcopy(result["evidence_change"]))
                doc["status"] = "source_change_review"
            elif action == "plan_next":
                doc["planning"] = result["planning"]
                doc["planning_history"].append(copy.deepcopy(result["planning"]))
                doc["status"] = "next_experiment_planned"
            elif action in {"run_cell", "execute_plan"}:
                self._release_discovery(doc, result, job["payload"]["cell_id"])
                doc["status"] = "discovery_ready"
                if action == "execute_plan":
                    cell = next(cell for cell in doc["cells"] if cell["id"] == job["payload"]["cell_id"])
                    doc["planning"].update(status="executed", executed_at=now(),
                        observed_result="The selected unrun recipe has now been measured. " + json.dumps(cell.get("aggregate"), sort_keys=True),
                        result_sha256=digest(result))
                    doc["planning_history"].append(copy.deepcopy(doc["planning"]))
            elif action == "evaluate":
                _require((result.get("verification") or {}).get("status") == "verified" and (result["verification"].get("metric_audit") or {}).get("final_family_frozen") is True,
                         "verification_incomplete", "The full registered family did not pass the independent numerical verifier.")
                doc.update(verification=result.get("verification"), final_evaluation=result, status="verified")
                doc["registration"]["status"] = "evaluated"
                doc["custody"]["status"] = "registered_family_verified"
                doc["decision"] = {"status": "finite_corpus_measured", "label": "Measured here. A field policy is not established.",
                    "reason": "The registered policy and fixed controls were evaluated together on the reserved public corpus. The result is a descriptive benchmark comparison; a genuine operational requirement and independent practitioner review remain unavailable.",
                    "limitations": LIMITATIONS[:4]}
            elif action == "build_export":
                doc["export_result"] = result
                doc["export_url"] = "/api/wheat/export"
                doc["status"] = "complete"
            current = self._current_job(job["id"])
            current.update(status="succeeded", checkpoint="Immutable outputs committed", updated_at=now(), heartbeat_at=now(),
                           completed_units=1, total_units=1, can_resume=False)
            self._save_job(current)
            doc["run"] = self._public_job(current)
            self.store._save(doc)
            self.store._event(STUDY_ID, "completed", action.replace("_", " ").capitalize() + " completed with retained evidence.", job["id"])

    def _release_discovery(self, doc: dict, result: dict, cell_id: str):
        """Translate independently verified worker metrics into image-first UI data."""
        _require((result.get("verification") or {}).get("status") == "verified",
                 "discovery_verification_required", "Unverified detector outputs cannot become measured discovery cells.")
        cell = next(cell for cell in doc["cells"] if cell["id"] == cell_id)
        summaries = result.get("metrics", []) or result.get("summaries", [])
        summary = next((row for row in summaries if row.get("recipe_id", row.get("condition_id")) == cell_id), {})
        image_rows = result.get("image_records", [])
        illustration_id = doc["asset"]["id"] if doc.get("asset") else None
        row = next((row for row in image_rows if row.get("image_id") == illustration_id and row.get("recipe_id", row.get("condition_id")) == cell_id and row.get("seed") == 11), {})
        if result.get("illustration") and not row:
            row = result["illustration"]
        # No plausible values are fabricated when an adapter fails its shape.
        if not summary or not row:
            raise ScienceError("wheat_release_incomplete", "Verified discovery output omitted the registered aggregate or illustration record.")
        boxes = row.get("targets", row.get("target_boxes", []))
        targets = [{"id": f"target-{index}", "bbox": self._xywh(box.get("box", box.get("bbox")) if isinstance(box, dict) else box)} for index, box in enumerate(boxes)]
        raw_predictions = row.get("predictions", [])
        matches = {item["prediction_index"]: item["target_index"] for item in row.get("matches", [])}
        duplicates = set(row.get("duplicate_prediction_indices", []))
        predictions = [{"id": f"prediction-{index}", "bbox": self._xywh(prediction.get("box", prediction.get("bbox"))),
                        "score": prediction["score"], "match_kind": "matched" if index in matches else "duplicate" if index in duplicates else "false_positive",
                        "target_id": f"target-{matches[index]}" if index in matches else None}
                       for index, prediction in enumerate(raw_predictions)]
        if doc.get("asset"):
            doc["asset"].update(targets=targets, ground_truth_released=True)
        transform = row.get("transform", row.get("processed_image", {}))
        processed = transform.get("processed", transform.get("artifact", transform))
        if not processed.get("sha256"):
            processed = next((item for item in row.get("processed_artifacts", []) if item.get("kind") == "processed_pixels" or str(item.get("path", "")).endswith(".png")), {})
        transformed = None
        if processed.get("sha256"):
            transformed = {"url": "/api/artifacts/" + processed["sha256"], "sha256": processed["sha256"],
                "width": processed.get("width", doc["asset"]["width"]), "height": processed.get("height", doc["asset"]["height"]),
                "resampler": transform.get("resampler", "Pillow LANCZOS; common original canvas"),
                "encoding": transform.get("encoding", "Pinned upload encoding"), "coordinate_mapping": "Original image xywh; detector coordinates mapped to the original canvas"}
        target_count = row.get("target_count", len(targets))
        cell.update(status="succeeded", error=None, predictions=predictions, seed=row["seed"],
            missed_target_ids=[f"target-{index}" for index in row.get("missed_target_indices", [])], transform=transformed,
            metrics={"target_count": target_count, "predicted_count": row.get("prediction_count", len(predictions)),
                "absolute_count_error": row["absolute_count_error"], "relative_count_error": row["absolute_count_error"] / target_count if target_count else None,
                "localization_metric": "TP / (TP + FP + FN), IoU ≥ 0.5", "localization_value": row["detection_accuracy_iou50"],
                "bytes": row["upload_bytes"], "wall_ms": row["inference_seconds"] * 1000,
                "matched_count": row["tp"], "duplicate_count": row["duplicate_count"], "false_positive_count": row["fp"]},
            aggregate={"n_images": summary["images"], "n_sessions": summary["sessions"], "seeds": summary.get("seeds", doc["contract"].get("training", {}).get("seeds", [])), "count_mae": summary["count_mae"],
                "count_bias": summary["count_bias"], "localization_value": summary["detection_accuracy_iou50"],
                "total_upload_bytes": summary.get("total_upload_bytes", summary["mean_upload_bytes"] * summary["images"]),
                "total_wall_ms": summary.get("total_inference_seconds", summary["mean_inference_seconds"] * summary["images"]) * 1000})
        doc["observations"].extend(result.get("observations", []))
        doc.setdefault("discovery_parents", {})[cell_id] = digest(result)
        if "noop_equivalence" in result:
            doc["noop_equivalence"] = copy.deepcopy(result["noop_equivalence"])

    @staticmethod
    def _xywh(box):
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            raise ScienceError("wheat_box_release_invalid", "Verified original-coordinate box is missing.")
        return [box[0], box[1], box[2] - box[0], box[3] - box[1]]

    def _register(self, doc: dict, cell_id: str):
        _require((doc.get("noop_equivalence") or {}).get("passed") is True,
                 "noop_verification_required", "Native/no-op equivalence across the full discovery corpus must pass before final registration.")
        packet = self.source_packet_path.read_bytes()
        _require(hashlib.sha256(packet).hexdigest() == (doc.get("source_compilation") or {}).get("packet_sha256"),
                 "source_packet_changed", "Final registration requires the exact source packet that passed extraction validation.")
        family = list(dict.fromkeys([cell_id, *FINAL_CONTROLS]))
        workflow = {"schema_version": "crucible.wheat.frozen-workflow.v1", "study_id": STUDY_ID,
            "source_packet": json.loads(packet),
            "source_compilation": doc.get("source_compilation"), "source_compilation_history": doc.get("source_compilation_history", []),
            "source_fields": doc["source_fields"], "evidence_history": doc["evidence_history"],
            "planning_history": doc["planning_history"], "provider_qualifications": doc.get("provider_qualifications", []),
            "discovery_parents": doc["discovery_parents"], "selected_parent_sha256": doc["discovery_parents"][cell_id],
            "provider_receipts": [json.loads(row[0]) for row in self.store.db.execute("SELECT doc FROM receipts WHERE folio_id=? ORDER BY rowid", (STUDY_ID,))
                                  if json.loads(row[0]).get("kind") in {"inference", "retrieval"}],
            "scope": "Frozen before final opening. Model/retrieval proposals and failures are evidence of workflow, not independent scientific validation."}
        inputs = {"family": family, "policy_id": cell_id, "split": doc["confirmation_split_sha256"],
                  "contract": doc["contract_sha256"], "checkpoint_set_sha256": doc["training"]["checkpoint_sha256"],
                  "code": doc["trusted_code_sha256"], "metric": doc["numerical_spec_sha256"],
                  "noop_equivalence_sha256": digest(doc["noop_equivalence"]),
                  "workflow_evidence_sha256": digest(workflow), "parent_discovery_sha256": doc["discovery_parents"][cell_id],
                  "analysis": "descriptive finite corpus; no acceptance threshold or sampling inference"}
        signature = digest(inputs)
        split_sha = doc["confirmation_split_sha256"]
        prior = self.store.db.execute("SELECT * FROM holdouts WHERE split_sha=?", (split_sha,)).fetchone()
        _require(not prior or prior["signature"] == signature, "holdout_already_used", "These final labels are already bound to a different analysis. A new folio or folder does not reset exposure.")
        hashes = doc.get("final_pixel_hashes") or doc.get("final_image_hashes")
        _require(bool(hashes), "custody_identity_missing", "Final pixel identities must be audited before registration can bind exposure across folders.")
        for sha in hashes:
            exposure = self.store.db.execute("SELECT signature FROM wheat_exposures WHERE image_sha=?", (sha,)).fetchone()
            _require(not exposure or exposure[0] == signature, "image_already_registered", "A final photograph is already registered for a different analysis. Changing a manifest or folder cannot make it untouched.")
        registered = now()
        scientific = {"policy_id": cell_id, "comparison_recipe_ids": family, "registered_at": registered,
                      "reviewer_name": "Automated local implementation (agent)", "parent_discovery_sha256": doc["discovery_parents"][cell_id]}
        registration = {"status": "registered", "registered_at": registered, "cell_id": cell_id, "signature": signature,
                        "configuration": inputs, "requirement": {"kind": "descriptive_benchmark", "practitioner_threshold": None},
                        "review_status": "Automated local operator; independent methodological and practitioner review unavailable",
                        "holdout_status": "reproducibility_replay" if prior else "first_registered_local_use_of_public_data",
                        "detail": "One immutable comparison family. No adaptive expansion after registration; no fresh field-data claim."}
        registration["sha256"] = digest(registration)
        workflow_artifact = self.store.json_artifact(workflow, "wheat-frozen-workflow.json", "registered_workflow")
        _require(workflow_artifact["sha256"] == inputs["workflow_evidence_sha256"], "workflow_digest_mismatch", "Frozen workflow bytes did not match registration.")
        doc["workflow_evidence_artifact"] = workflow_artifact
        doc["artifacts"].append(workflow_artifact)
        for sha in hashes:
            self.store.db.execute("INSERT OR IGNORE INTO wheat_exposures VALUES(?,?,?,?,NULL,?)", (sha, signature, STUDY_ID, registered, canonical(registration).decode()))
        if not prior:
            self.store.db.execute("INSERT INTO holdouts VALUES(?,?,?,?)", (split_sha, signature, STUDY_ID, canonical(registration).decode()))
        doc.update(registration=registration, scientific_registration=scientific, status="final_registered")
        doc["custody"].update(status="registered_before_opening", exposure_status=registration["holdout_status"])

    def _materialize_workflow_evidence(self):
        doc = self.store.get(STUDY_ID)
        _require((doc.get("verification") or {}).get("status") == "verified", "verification_required", "Workflow export requires final verification.")
        frozen = doc["workflow_evidence_artifact"]
        _require(frozen["sha256"] == doc["registration"]["configuration"]["workflow_evidence_sha256"],
                 "workflow_digest_mismatch", "Registration's frozen workflow evidence changed.")
        rows = [dict(row) for row in self.store.db.execute("SELECT * FROM wheat_exposures WHERE folio_id=? ORDER BY image_sha", (STUDY_ID,))]
        custody = self.store.json_artifact({"schema_version": "crucible.wheat.final-custody.v1", "registration": doc["registration"],
            "scientific_registration": doc["scientific_registration"], "custody": doc["custody"], "pixel_exposures": rows,
            "limitation": "Local durable public-data custody; shared OS identity, no independent human custodian or historically untouched-data claim."},
            "wheat-final-custody.json", "final_custody")
        folder = self.case_root / "workflow"
        folder.mkdir(parents=True, exist_ok=True)
        for record, filename in ((frozen, "frozen-workflow.json"), (custody, "final-custody.json")):
            source, _ = self.store.get_artifact(record["sha256"])
            target = folder / filename
            if not target.exists():
                os.link(source, target)
            _require(not target.is_symlink() and hashlib.sha256(target.read_bytes()).hexdigest() == record["sha256"],
                     "workflow_artifact_changed", "Retained workflow/custody bytes failed their immutable hash.")

    async def action(self, action: str, body: dict) -> dict:
        self.ensure()
        _require(action in {"prepare", "compile_sources", "train", "run_cell", "retrieve", "accept_evidence", "reject_evidence",
                            "plan_next", "execute_plan", "register", "evaluate", "build_export", "cancel", "resume"},
                 "unsupported_action", "Unsupported wheat action; no arbitrary recipe, model, code, or URL can execute.")
        key = body["idempotency_key"]
        fingerprint = digest({"study": STUDY_ID, "action": action, "body": {k: v for k, v in body.items() if k not in {"revision", "idempotency_key"}}})
        queued, cancel = None, None
        with self.store.transaction():
            previous = self.store.db.execute("SELECT * FROM idempotency WHERE key=?", (key,)).fetchone()
            if previous:
                _require(previous["fingerprint"] == fingerprint, "idempotency_conflict", "This request key is already bound to different action inputs.")
                return self.public()
            doc = self.store._folio(STUDY_ID)
            _require(doc["revision"] == body["revision"], "stale_revision", "The saved wheat study changed. Refresh before applying the action.")
            _require(action in self.capabilities(doc), "wheat_action_gated", "This action is not available at the current evidence/custody checkpoint. Inspect the prerequisites and retained attempt.")
            if action == "cancel":
                cancel = self._current_job(doc["run"]["id"])
                cancel.update(status="cancel_requested", fence=cancel["fence"] + 1, updated_at=now())
                self._save_job(cancel)
                doc.update(status="cancel_requested", run=self._public_job(cancel))
            elif action == "resume":
                previous_job = self._current_job(doc["run"]["id"])
                queued = self._queue(doc, previous_job["action"], previous_job)
            elif action in {"accept_evidence", "reject_evidence"}:
                evidence = doc["evidence_change"]
                evidence["status"] = "accepted" if action == "accept_evidence" else "rejected"
                evidence["decision"] = {"timestamp": now(), "role": "local_operator", "name": body.get("operator_name", "Local operator"),
                                        "reason": body.get("reason", "Apply the sourced recipe to the frozen finite discovery family."), "independent_review": False}
                if action == "accept_evidence":
                    for cell in doc["cells"]:
                        if cell["id"] in evidence["after"]:
                            cell.update(enabled=True, disabled_reason=None)
                            if cell["status"] == "disabled":
                                cell["status"] = "unrun"
                doc["evidence_history"].append(copy.deepcopy(evidence))
                doc["status"] = "discovery_ready"
            elif action == "register":
                cell_id = body.get("cell_id")
                _require(any(cell["id"] == cell_id and cell["status"] == "succeeded" for cell in doc["cells"]), "unobserved_policy", "Register one actually measured discovery policy.")
                self._register(doc, cell_id)
            else:
                payload = {}
                if action in {"run_cell", "execute_plan"}:
                    cell_id = body.get("cell_id") if action == "run_cell" else doc["planning"]["next_cell_id"]
                    _require(any(cell["id"] == cell_id and cell["enabled"] and cell["status"] == "unrun" for cell in doc["cells"]),
                             "cell_not_unrun", "Select an enabled, genuinely unrun cell. Completed measurements are immutable recorded evidence.")
                    if action == "execute_plan":
                        _require(digest(self.planner_context(doc)["released_discovery_aggregates"]) == doc["planning"]["discovery_signature"],
                                 "planner_context_changed", "Discovery evidence changed after the proposal. Ask for a new plan before executing it.")
                    payload["cell_id"] = cell_id
                queued = self._queue(doc, action, payload=payload)
            self.store._save(doc)
            self.store._event(STUDY_ID, action, action.replace("_", " ").capitalize() + " recorded.")
            self.store.db.execute("INSERT INTO idempotency VALUES(?,?,?)", (key, fingerprint, STUDY_ID))
        if cancel and self.tasks.get(cancel["id"]):
            self.tasks[cancel["id"]].cancel()
        if queued:
            self._schedule(queued)
        return self.public()

    def export_path(self) -> Path:
        doc = self.store.get(STUDY_ID)
        _require(doc.get("verification") is not None and doc.get("export_url"), "verification_required", "Build the portable export after registered final verification.")
        for item in (doc.get("export_result") or {}).get("artifacts", []):
            if item.get("media_type") == "application/zip" or str(item.get("path", "")).endswith(".zip"):
                path = (self.case_root / item["path"]).resolve()
                _require(path.is_relative_to(self.case_root.resolve()) and path.is_file(), "export_missing", "The recorded portable ZIP is unavailable.")
                with path.open("rb") as stream:
                    actual = hashlib.file_digest(stream, "sha256").hexdigest()
                _require(actual == item["sha256"], "export_hash_mismatch", "Portable ZIP digest no longer matches the recorded artifact.")
                return path
        raise Conflict("export_missing", "The worker did not return a portable ZIP.")
