from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import resource
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .config import PROJECT, Settings
from .providers import ChallengeResponse, ContractProposal, Gateway, ProviderError
from .store import Conflict, Store, canonical, digest, now

ACTIVE = {"queued", "running", "cancel_requested"}
LIMITATIONS = [
    "An authored comparison on a trusted adapter; not a replication of the original paper's protocol.",
    "Reviewed by a local operator. External methodologist review, participant research and a frozen benchmark study are pending.",
    "Public benchmark labels may be historically known. The planner receives no sealed confirmation labels in this workflow.",
    "Predictor and verifier are separate trusted processes under the same local OS user, not a hardened untrusted-code sandbox. Arbitrary code imports are disabled.",
    "Descriptive confidence intervals are not multiplicity-adjusted. Registered directional tests use Holm adjustment.",
]


class ScienceError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message


class Orchestrator:
    def __init__(self, settings: Settings, store: Store):
        self.settings, self.store = settings, store
        self.tasks: dict[str, asyncio.Task] = {}
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.closing = False

    @staticmethod
    def _orphan_command_matches(command: str, directory: Path) -> bool:
        module = re.search(r"(?:^|\s)-m\s+(?:science\.cli|science\.wheat_cli)(?:\s|$)", command)
        output = re.search(r"(?:^|\s)--output\s+[\"']?" + re.escape(str(directory.resolve()) + os.sep), command)
        return bool(module and output)

    def _stop_orphan(self, pid: int, directory: Path) -> tuple[str, bool]:
        """Stop only the exact retained module/job process group; fence PID reuse."""
        def owned():
            try:
                command = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True, timeout=2)
                return self._orphan_command_matches(command, directory)
            except (ProcessLookupError, subprocess.CalledProcessError):
                return False
        try:
            if not owned():
                return "not_running_or_pid_reused", True
            if os.getpgid(pid) != pid:
                return "matching_worker_has_unrecognized_process_group", False
            os.killpg(pid, signal.SIGTERM)
            for _ in range(20):
                if not owned():
                    return "terminated_exact_job_group", True
                time.sleep(.05)
            if owned() and os.getpgid(pid) == pid:
                os.killpg(pid, signal.SIGKILL)
            for _ in range(20):
                if not owned():
                    return "killed_exact_job_group", True
                time.sleep(.05)
            return "worker_termination_unconfirmed", False
        except ProcessLookupError:
            return "already_exited", True
        except (subprocess.SubprocessError, PermissionError):
            return "worker_identity_or_cleanup_unconfirmed", False

    async def startup(self):
        with self.store.transaction():
            for row in self.store.db.execute("SELECT doc FROM jobs WHERE status IN ('queued','running','cancel_requested')").fetchall():
                job = json.loads(row[0])
                pid = job.get("pid")
                # Reconcile only a process whose command still names this exact
                # job directory; never terminate a recycled PID blindly.
                cleanup, resumable = self._stop_orphan(pid, self.store.root / "jobs" / job["id"]) if pid else ("no_worker_pid", True)
                job.update(status="interrupted", fence=job["fence"] + 1, updated_at=now(), can_resume=resumable, orphan_cleanup=cleanup,
                           error="The service restarted before this attempt committed. Completed immutable artifacts are retained; resume creates a new attempt.")
                if not resumable:
                    job["error"] = "Worker cleanup could not be confirmed. Resume is blocked to prevent a second fit colliding with the retained attempt."
                self._save_job(job)
                doc = self.store._folio(job["folio_id"])
                if (doc.get("run") or {}).get("id") == job["id"]:
                    doc.update(run=self._public_job(job), status="interrupted")
                    self.store._save(doc)
                    self.store._event(doc["id"], "interrupted", job["error"], job["id"])
            for row in self.store.db.execute("SELECT id,doc FROM receipts").fetchall():
                receipt = json.loads(row["doc"])
                if receipt.get("status") == "pending":
                    receipt.update(status="interrupted", error="Service restarted during the external request. Provider billing/usage may be unknown; no blind resubmission.")
                    self.store.db.execute("UPDATE receipts SET doc=? WHERE id=?", (canonical(receipt).decode(), row["id"]))
        if not self.store.list():
            for adapter in ("occupancy", "synthetic"):
                await self.create(adapter, id=adapter)

    async def shutdown(self):
        self.closing = True
        for task in list(self.tasks.values()):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)

    async def create(self, adapter_id: str, title: str | None = None, claim: str | None = None, id: str | None = None) -> dict:
        from science.api import get_case
        meta = get_case(adapter_id)
        contract = copy.deepcopy(meta["contract"])
        claim_text = claim or contract.get("claim") or meta.get("claim") or "An authored method comparison under the registered protocol."
        contract.update(claim=claim_text, locked=False, approval=None, model_proposal=None, revision=1)
        doc = {
            "id": id or uuid.uuid4().hex[:16], "adapter_id": adapter_id,
            "title": title or meta.get("title") or ("When the room goes dark" if adapter_id == "occupancy" else "A nonlinear signal, under scrutiny"),
            "claim": claim_text, "case_kind": "authored_public_data" if adapter_id == "occupancy" else "controlled_synthetic",
            "created_at": now(), "updated_at": now(), "revision": 1,
            "stage": "contract", "status": "draft", "source": None, "contract": contract,
            "run": None, "evidence_change": None, "observations": [], "proposals": [],
            "registration": None, "verification": None, "conclusion": None,
            "artifacts": [], "limitations": LIMITATIONS.copy(),
            "reproduction_accepted": False, "exploration_complete": False,
        }
        self.store.create(doc)
        await self._launch(doc["id"], "prepare")
        return self.store.get(doc["id"])

    def _save_job(self, job: dict):
        self.store.db.execute("INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?,?)", (job["id"], job["folio_id"], job["action"], job["status"], job["fence"], canonical(job).decode()))

    @staticmethod
    def _public_job(job: dict) -> dict:
        return {k: v for k, v in job.items() if k not in {"input", "pid", "fence", "folio_id"}}

    def _current_job(self, id: str) -> dict:
        with self.store.lock:
            row = self.store.db.execute("SELECT doc FROM jobs WHERE id=?", (id,)).fetchone()
        if not row:
            raise KeyError(id)
        return json.loads(row[0])

    def _check_fence(self, job: dict):
        current = self._current_job(job["id"])
        if current["fence"] != job["fence"] or current["status"] not in ACTIVE:
            raise asyncio.CancelledError()

    async def _launch(self, folio_id: str, action: str, resume_from: dict | None = None):
        with self.store.transaction():
            doc = self.store._folio(folio_id)
            if doc.get("run") and doc["run"]["status"] in ACTIVE:
                raise Conflict("run_in_progress", "This folio already has an active attempt.")
            job = self._queue(doc, action, resume_from)
            self.store._save(doc)
        self._schedule(job)

    def _queue(self, doc: dict, action: str, resume_from: dict | None = None) -> dict:
        """Called inside the same durable transaction as action/idempotency."""
        folio_id = doc["id"]
        job = {
                "id": uuid.uuid4().hex, "folio_id": folio_id, "action": action,
                "status": "queued", "fence": 1, "started_at": now(), "updated_at": now(),
                "heartbeat_at": now(), "checkpoint": "Queued; immutable inputs saved",
                "completed_units": 0, "total_units": None, "unit_label": "stages",
                "attempt": (resume_from or {}).get("attempt", 0) + 1,
                "parent_attempt": (resume_from or {}).get("id"), "error": None, "can_resume": False,
                "input": {"root": str(self.store.root / "cases" / folio_id), "contract": doc["contract"],
                          "active_conditions": (doc.get("exploration_plan") or {}).get("conditions", doc["contract"].get("active_conditions", [])), "registration": doc.get("registration"),
                          "reproduction_accepted": doc["reproduction_accepted"]},
            }
        self._save_job(job)
        doc.update(run=self._public_job(job), status="running")
        self.store._event(folio_id, "queued", f"{action.replace('_', ' ').capitalize()} queued as attempt {job['attempt']}.", job["id"])
        return job

    def _schedule(self, job: dict):
        task = asyncio.create_task(self._execute(job), name="crucible:" + job["id"])
        self.tasks[job["id"]] = task
        task.add_done_callback(lambda _: self.tasks.pop(job["id"], None))

    def _checkpoint(self, job: dict, message: str, completed: int | None = None, total: int | None = None, event: bool = True):
        self._check_fence(job)
        with self.store.transaction():
            current = self._current_job(job["id"])
            current.update(status="running", checkpoint=message, heartbeat_at=now(), updated_at=now())
            if completed is not None:
                current["completed_units"] = completed
            if total is not None:
                current["total_units"] = total
            self._save_job(current)
            doc = self.store._folio(job["folio_id"])
            doc["run"] = self._public_job(current)
            self.store._save(doc, advance=False)
            if event:
                self.store._event(doc["id"], "checkpoint", message, job["id"])

    async def _heartbeat(self, job: dict):
        while True:
            await asyncio.sleep(3)
            current = self._current_job(job["id"])
            self._checkpoint(job, current["checkpoint"], event=False)

    def _science_working_directory(self, job: dict, stage: str) -> Path:
        """Use the retained package; never silently replace historical code."""
        if stage == "prepare":
            return PROJECT
        doc = self.store.get(job["folio_id"])
        source_dir, expected = doc.get("source_snapshot_dir"), doc.get("trusted_code")
        if not source_dir or not isinstance(expected, dict) or not expected:
            raise ScienceError("frozen_source_required", "The prepared case has no complete trusted source identity. Current code cannot silently replace it.")
        root = Path(job["input"]["root"]).resolve()
        snapshot = (root / source_dir).resolve()
        package = snapshot / "science"
        if not snapshot.is_relative_to(root) or not package.is_dir() or package.is_symlink():
            raise ScienceError("frozen_source_missing", "The retained numerical package is unavailable or outside its case.")
        if {path.name for path in package.glob("*.py")} != set(expected):
            raise ScienceError("frozen_source_changed", "The retained module set changed. No replacement source is authorized.")
        for name, sha in expected.items():
            path = package / name
            if Path(name).name != name or path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ScienceError("frozen_source_changed", "A retained numerical module failed its exact source hash.")
        return snapshot

    async def _science(self, job: dict, stage: str) -> dict:
        directory = self.store.root / "jobs" / job["id"]
        directory.mkdir(parents=True, exist_ok=True)
        request = directory / f"{stage}-request.json"
        result_path = directory / f"{stage}-result.json"
        request.write_bytes(canonical(job["input"]))
        argv = [sys.executable, "-m", "science.cli", stage]
        if stage == "prepare":
            doc = self.store.get(job["folio_id"])
            argv += ["--adapter", doc["adapter_id"], "--root", job["input"]["root"]]
            if self.settings.source_zip and doc["adapter_id"] == "occupancy":
                argv += ["--source-zip", str(self.settings.source_zip)]
        else:
            argv += ["--input", str(request)]
        argv += ["--output", str(result_path)]
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "en_US.UTF-8", "PYTHONUNBUFFERED": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1", "TMPDIR": str(directory)}
        def limits():
            resource.setrlimit(resource.RLIMIT_CPU, (240, 245))
            resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024 * 1024, 256 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        working_directory = self._science_working_directory(job, stage)
        process = await asyncio.create_subprocess_exec(*argv, cwd=working_directory, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True, preexec_fn=limits)
        self.processes[job["id"]] = process
        with self.store.lock:
            current = self._current_job(job["id"])
            current["pid"] = process.pid
            self._save_job(current)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=360)
        except (asyncio.CancelledError, TimeoutError):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
            if asyncio.current_task().cancelling():
                raise
            raise ScienceError("worker_timeout", "The trusted worker exceeded the 360 second wall-time bound. It was terminated; this is an execution failure, not a scientific outcome.")
        finally:
            self.processes.pop(job["id"], None)
        self._check_fence(job)
        if result_path.is_file():
            try:
                result = json.loads(result_path.read_text())
            except (ValueError, OSError) as exc:
                raise ScienceError("invalid_worker_output", "The worker did not produce valid result JSON.") from exc
        else:
            result = {}
        def portable_log(raw: bytes) -> str:
            value = raw.decode(errors="replace")[-4000:]
            for path, label in [(str(directory), "${ATTEMPT}"), (job["input"]["root"], "${CASE_ROOT}"), (str(PROJECT), "${PROJECT}"), (sys.prefix, "${PYTHON_ENV}"), (str(Path.home()), "${HOME}")]:
                value = value.replace(path, label)
            return value
        log = {"command": ["python", "-m", "science.cli", stage], "exit_code": process.returncode,
               "source_execution": "current trusted preparation package" if stage == "prepare" else "hash-verified retained frozen numerical package",
               "stdout": portable_log(stdout), "stderr": portable_log(stderr), "path_normalization": "Local paths replaced with named placeholders at receipt creation; numerical artifacts are unchanged",
               "isolation": "Trusted authored code; separate process, filtered environment without provider keys, CPU/file/wall-time limits. Same OS identity; no kernel network/filesystem sandbox."}
        log_artifact = self.store.json_artifact(log, f"{stage}-execution.json", "execution")
        self._append_artifacts(job["folio_id"], [log_artifact])
        if process.returncode != 0 or result.get("error"):
            error = result.get("error") or {}
            raise ScienceError(error.get("code", "worker_failed"), error.get("message", "The trusted worker failed. Inspect its execution receipt; no scientific conclusion was assigned."))
        return result

    def _append_artifacts(self, folio_id: str, artifacts: list[dict]):
        def append(doc):
            existing = {a["sha256"] for a in doc["artifacts"]}
            doc["artifacts"].extend(a for a in artifacts if a["sha256"] not in existing)
        self.store.mutate(folio_id, append, advance=False)

    def _ingest(self, job: dict, result: dict) -> dict:
        self._check_fence(job)
        metadata = []
        root = Path(job["input"]["root"]).resolve()
        for item in result.get("artifacts", []):
            if item.get("private") or item.get("sealed"):
                continue
            relative = item.get("path")
            if relative:
                path = (root / relative).resolve()
                if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
                    raise ScienceError("artifact_path_rejected", "A worker artifact was outside the trusted case directory.")
                data = path.read_bytes()
                sha = hashlib.sha256(data).hexdigest()
                if item.get("sha256") and item["sha256"] != sha:
                    raise ScienceError("artifact_hash_mismatch", "A worker artifact failed content-hash verification.")
                metadata.append(self.store.artifact(data, item.get("name", path.name), item.get("kind", "computation"), item.get("media_type", "application/json")))
        result_artifact = self.store.json_artifact(result, f"{job['action']}-result.json", "result")
        metadata.append(result_artifact)
        self._append_artifacts(job["folio_id"], metadata)
        for raw in result.get("receipts", []):
            receipt = {"kind": "computation", "provider": "local_python", "model": None,
                       "status": "succeeded", "started_at": now(), "purpose": job["action"], "estimated_cost_usd": None,
                       **raw, "source_receipt_id": raw.get("id"), "id": str(uuid.uuid4())}
            self.store.add_receipt(job["folio_id"], job["id"], receipt)
        for observation in result.get("observations", []):
            observation.setdefault("artifact_sha256", result_artifact["sha256"])
            observation.setdefault("id", digest(observation)[:20])
        return result

    def _progress_result(self, job: dict, result: dict):
        self._check_fence(job)
        def update(doc):
            known = {o["id"] for o in doc["observations"]}
            doc["observations"].extend(o for o in result.get("observations", []) if o["id"] not in known)
            if job["action"] == "explore":
                doc["exploration_complete"] = True
        self.store.mutate(job["folio_id"], update, advance=False)

    def _gateway(self, job: dict) -> Gateway:
        return Gateway(self.settings, lambda receipt: self.store.add_receipt(job["folio_id"], job["id"], receipt))

    @staticmethod
    def _model_context(doc: dict, include_discovery: bool = False) -> dict:
        source = doc.get("source") or {}
        context = {"case_kind": doc["case_kind"], "claim": doc["claim"], "source": {k: source.get(k) for k in ("title", "url", "license", "attribution", "source_span", "description", "audit")},
                   "locked_protocol": {k: doc["contract"].get(k) for k in ("population", "candidate", "baseline", "metric", "practical_delta", "analysis", "split", "preprocessing", "scope", "seeds", "allowed_conditions", "active_conditions")},
                   "review_status": "Local operator review only; external methodologist review pending."}
        context["reviewed_exploration_schedule"] = (doc.get("exploration_plan") or {}).get("conditions", doc["contract"].get("active_conditions", []))
        context["trusted_facts"] = {
            "block_independence_established": doc["adapter_id"] == "synthetic",
            "seed_role": "training_variability_only",
            "uncertainty_basis": "Seed-average paired effects within each usable block first; the interval and tests use block effects, never seeds as independent observations.",
            "occupancy_limit": "Adjacent calendar-day independence is unestablished; the UCI verdict stays inconclusive in this release." if doc["adapter_id"] == "occupancy" else "Groups have separate authored pseudorandom streams; inference conditions on the fixed training data.",
        }
        if include_discovery:
            context["discovery_aggregates"] = [{k: o.get(k) for k in ("condition_id", "condition_label", "scope", "candidate", "baseline", "effect", "ci_low", "ci_high", "blocks", "rows", "warning")} for o in doc["observations"] if o["phase"] in {"reproduction", "discovery"}]
            context["evidence_change"] = doc.get("evidence_change")
        return context

    async def _execute(self, job: dict):
        heartbeat = None
        try:
            self._checkpoint(job, "Inputs frozen; starting " + job["action"].replace("_", " "), 0)
            heartbeat = asyncio.create_task(self._heartbeat(job))
            action = job["action"]
            result: dict[str, Any] = {}
            if action == "propose_contract":
                self._checkpoint(job, "NVIDIA Nemotron is proposing a contract from released source context")
                result["model_proposal"] = await self._gateway(job).model("propose_contract", self._model_context(self.store.get(job["folio_id"])), ContractProposal,
                    "State an authored comparison of the exact candidate and baseline on this named data. You may clarify claim wording, assumptions and limitations only. Do not change the fixed metric, split, methods, practical margin or analysis. Do not say the source claims the candidate is superior.")
            elif action == "retrieve":
                self._checkpoint(job, "Tavily is retrieving primary-source context for an inspectable intervention change")
                retrieval = await self._gateway(job).retrieve()
                doc = self.store.get(job["folio_id"])
                before = doc["contract"].get("active_conditions", [])
                light = [c["id"] for c in doc["contract"].get("allowed_conditions", []) if str(c.get("feature", "")).lower() == "light"]
                applicable = retrieval["source"] is not None and doc["adapter_id"] == "occupancy" and bool(light)
                result["evidence_change"] = {
                    "id": uuid.uuid4().hex, "status": "proposed" if applicable else "context_only",
                    "query": retrieval["query"], "queried_at": retrieval["queried_at"], "source": retrieval["source"],
                    "assumption": "The discovery schedule currently examines CO₂ availability. Light is also a documented predictor.",
                    "before": before, "after": list(dict.fromkeys(before + light)) if applicable else before,
                    "explanation": "The retrieved primary source documents Light among the measured sensors. Accepting this proposal adds the registered Light-dropout conditions to the actual discovery schedule. This tests sensor availability; it is not a claimed correction to, or refutation of, the original paper." if applicable else "No source supporting a material adapter-specific change was returned. Retrieval is context only and the experiment schedule stays unchanged.",
                    "decision": None, "receipt_id": retrieval["receipt"]["id"],
                }
            else:
                stage = "predict" if action == "confirm" else action
                self._checkpoint(job, {
                    "prepare": "Auditing licensed data, file hashes and disjoint splits before model fitting",
                    "reproduce": "Training both fixed pipelines and replaying the original condition on discovery data",
                    "explore": "Executing the finite, reviewed discovery schedule; confirmation labels remain sealed",
                    "confirm": "Generating paired predictions for the single registered confirmation condition",
                    "verify": "Independent verifier is joining sealed labels and recomputing metrics and decisions",
                }.get(action, action))
                result = self._ingest(job, await self._science(job, stage))
                if action == "explore":
                    self._progress_result(job, result)
                    self._checkpoint(job, "Discovery artifacts committed. NVIDIA Nemotron is ranking informative registered conditions", len(result.get("observations", [])))
                    planner_gateway = self._gateway(job)
                    try:
                        proposal = await planner_gateway.model("rank_challenges", self._model_context(self.store.get(job["folio_id"]), True), ChallengeResponse,
                            "Rank at most three actually observed discovery condition IDs. Prefer smaller single-axis changes when comparably informative. Original is valid if no intervention is informative. Expected information is a qualitative hypothesis, never measured gain. Scope must exactly match the trusted condition. Do not use or invent confirmation results.")
                        doc = self.store.get(job["folio_id"])
                        allowed = {c["id"]: c for c in doc["contract"]["allowed_conditions"]}
                        observed = {o["condition_id"] for o in doc["observations"]}
                        ids = [p["condition_id"] for p in proposal["proposals"]]
                        if len(ids) != len(set(ids)) or any(p["condition_id"] not in observed or p["condition_id"] not in allowed or p["scope"] != allowed[p["condition_id"]]["scope"] for p in proposal["proposals"]):
                            raise ProviderError("proposal_outside_lattice", "The planner proposed an unobserved condition or an incorrect scope. Its proposal was rejected; the measured discovery artifacts remain available.")
                        result["proposals"] = sorted(proposal["proposals"], key=lambda x: x["rank"])
                        result["planner_limitation"] = proposal["limitation"]
                    except ProviderError as exc:
                        if planner_gateway.last_receipt and planner_gateway.last_receipt["status"] == "succeeded":
                            rejected = {**planner_gateway.last_receipt, "status": "proposal_rejected", "error": exc.message}
                            self.store.add_receipt(job["folio_id"], job["id"], rejected)
                        result["proposals"] = []
                        result["planner_error"] = exc.message
            self._check_fence(job)
            self._complete(job, result)
        except asyncio.CancelledError:
            with self.store.transaction():
                current = self._current_job(job["id"])
                current.update(status="interrupted" if self.closing else "cancelled", updated_at=now(), heartbeat_at=now(), can_resume=True,
                               checkpoint="Trusted local worker stopped; stale completion is fenced" if not self.closing else "Service stopped before completion",
                               error="External provider requests cannot guarantee remote cancellation or known final usage." if job["action"] in {"propose_contract", "retrieve", "explore"} else None)
                self._save_job(current)
                doc = self.store._folio(job["folio_id"])
                if doc.get("run", {}).get("id") == job["id"]:
                    doc.update(run=self._public_job(current), status=current["status"])
                    self.store._save(doc)
                    self.store._event(doc["id"], current["status"], current["checkpoint"], job["id"])
        except Exception as exc:
            error = {"code": getattr(exc, "code", "execution_failed"), "message": getattr(exc, "message", "An operational step failed. Inspect retained execution artifacts; no scientific outcome was inferred."), "recoverable": True}
            with self.store.transaction():
                current = self._current_job(job["id"])
                if current["fence"] == job["fence"]:
                    current.update(status="failed", error=error, can_resume=True, updated_at=now(), checkpoint="Attempt failed; prior immutable evidence preserved")
                    self._save_job(current)
                    doc = self.store._folio(job["folio_id"])
                    doc.update(run=self._public_job(current), status="failed")
                    self.store._save(doc)
                    self.store._event(doc["id"], "failed", error["message"], job["id"])
            # Bounded local diagnostic has no environment or provider response.
            diagnostic = self.store.root / "jobs" / job["id"]
            diagnostic.mkdir(exist_ok=True, parents=True)
            (diagnostic / "exception.json").write_bytes(canonical({"type": type(exc).__name__, "message": str(exc)[:2000]}))
        finally:
            if heartbeat:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)

    def _complete(self, job: dict, result: dict):
        self._check_fence(job)
        action = job["action"]
        with self.store.transaction():
            doc = self.store._folio(job["folio_id"])
            known = {o["id"] for o in doc["observations"]}
            doc["observations"].extend(o for o in result.get("observations", []) if o["id"] not in known)
            if action == "prepare":
                pending = doc["contract"]
                contract = result["contract"]
                contract.update(claim=doc["claim"], revision=pending.get("revision", 1), locked=False, approval=None, model_proposal=None)
                doc.update(source=result["source"], contract=contract, status="draft", stage="contract")
                doc["limitations"] = list(dict.fromkeys(LIMITATIONS + result.get("limitations", [])))
                for key in ("manifest_sha256", "confirmation_split_sha256", "numerical_spec_sha256", "trusted_code", "trusted_code_sha256", "source_snapshot_dir"):
                    if key in result:
                        doc[key] = result[key]
            elif action == "propose_contract":
                doc["contract"]["model_proposal"] = result["model_proposal"]
                doc["contract"]["claim"] = result["model_proposal"]["claim"]
                doc["claim"] = result["model_proposal"]["claim"]
                doc.update(status="draft", stage="contract")
            elif action == "reproduce":
                doc.update(reproduction=result.get("replay", {}), status="baseline_review", stage="reproduction")
            elif action == "retrieve":
                doc.update(evidence_change=result["evidence_change"], status="evidence_review", stage="challenge")
            elif action == "explore":
                doc.update(status="explored", stage="challenge", proposals=result.get("proposals", []), exploration_complete=True, planner_error=result.get("planner_error"), planner_limitation=result.get("planner_limitation"))
            elif action == "confirm":
                doc.update(status="confirmation_ready", stage="confirmation", prediction_manifest=result.get("prediction_manifest"))
            elif action == "verify":
                doc.update(verification=result["verification"], conclusion=result.get("conclusion"), status="review_ready", stage="folio")
            current = self._current_job(job["id"])
            current.update(status="succeeded", checkpoint="Verified stage outputs committed", updated_at=now(), heartbeat_at=now(), completed_units=max(1, len(result.get("observations", []))), can_resume=False)
            doc["run"] = self._public_job(current)
            self._save_job(current)
            self.store._save(doc)
            self.store._event(doc["id"], "completed", f"{action.replace('_', ' ').capitalize()} completed; immutable outputs committed.", job["id"])

    async def action(self, folio_id: str, action: str, body: dict) -> dict:
        supported = {"update_contract", "lock_contract", "propose_contract", "reproduce", "accept_reproduction", "retrieve", "accept_evidence", "reject_evidence", "explore", "register_confirmation", "confirm", "verify", "review_conclusion", "cancel", "resume"}
        if action not in supported:
            raise Conflict("unsupported_action", "This action is not supported by the trusted adapter.")
        key = body.get("idempotency_key")
        if not isinstance(key, str) or not 8 <= len(key) <= 128:
            raise Conflict("idempotency_required", "Provide a unique idempotency key for this action.")
        fingerprint = digest({"folio_id": folio_id, "action": action, "body": {k: v for k, v in body.items() if k not in {"revision", "idempotency_key"}}})
        long_action = None
        resume_from = None
        cancel_job = None
        queued_job = None
        with self.store.transaction():
            prior = self.store.db.execute("SELECT * FROM idempotency WHERE key=?", (key,)).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise Conflict("idempotency_conflict", "This idempotency key already belongs to different action inputs.")
                return self.store.get(prior["folio_id"])
            doc = self.store._folio(folio_id)
            if body.get("revision") != doc["revision"]:
                raise Conflict("stale_revision", "This folio changed. Refresh its current revision before applying the action.")
            active = doc.get("run") and doc["run"]["status"] in ACTIVE
            if active and action != "cancel":
                raise Conflict("run_in_progress", "Wait for or cancel the current attempt before changing its inputs.")
            contract = doc["contract"]
            reviewer = str(body.get("reviewer_name", "")).strip()
            def require(condition: bool, code: str, message: str):
                if not condition:
                    raise Conflict(code, message)
            def review() -> dict:
                require(1 <= len(reviewer) <= 100, "reviewer_required", "Enter the local operator's name to record this review.")
                return {"reviewer_name": reviewer, "role": "local_operator", "timestamp": now(), "note": str(body.get("review_note") or body.get("reason") or "")[:2000], "external_methodologist": "pending"}
            if action in {"update_contract", "propose_contract", "lock_contract"}:
                require(not contract.get("locked") and not doc.get("registration"), "contract_locked", "This contract is locked. Create a new folio to propose another claim; prior results keep their original contract.")
                require(doc.get("source") is not None, "source_not_ready", "Wait for the source and split audit to finish.")
            if action == "update_contract":
                claim = body.get("claim", doc["claim"])
                title = body.get("title", doc["title"])
                delta = body.get("practical_delta", contract["practical_delta"])
                require(isinstance(claim, str) and 20 <= len(claim.strip()) <= 800, "invalid_claim", "The authored claim must contain 20–800 characters.")
                require(isinstance(title, str) and 3 <= len(title.strip()) <= 120, "invalid_title", "The title must contain 3–120 characters.")
                require(isinstance(delta, (float, int)) and not isinstance(delta, bool) and 0 <= delta <= 0.1, "invalid_margin", "Practical margin must be between 0 and 0.10.")
                contract.update(claim=claim.strip(), practical_delta=float(delta), revision=contract.get("revision", 1) + 1)
                doc.update(claim=claim.strip(), title=title.strip())
            elif action == "lock_contract":
                approval = review()
                approval["approval_scope"] = "Authored claim and trusted numerical specification only. Model-supplied assumptions remain advisory and are not endorsed by locking."
                contract["locked"] = True
                contract["approval"] = approval
                contract.pop("sha256", None)
                contract["sha256"] = digest(contract)
                self.store.db.execute("INSERT INTO contracts VALUES(?,?,?)", (contract["sha256"], folio_id, canonical(contract).decode()))
                doc.update(status="reviewed", stage="reproduction")
            elif action == "accept_reproduction":
                require(doc["status"] == "baseline_review", "reproduction_required", "Complete the original-condition replay before accepting it.")
                require(bool(doc.get("reproduction")), "reproduction_not_verified", "The worker did not return a verified deterministic replay.")
                doc["reproduction_review"] = review()
                doc.update(reproduction_accepted=True, status="reproduced", stage="challenge")
            elif action in {"accept_evidence", "reject_evidence"}:
                evidence = doc.get("evidence_change")
                require(bool(evidence) and evidence.get("status") == "proposed", "no_proposed_change", "There is no pending material evidence change to review.")
                require(not doc["exploration_complete"] and not doc.get("registration"), "exploration_frozen", "The discovery schedule cannot change after exploration.")
                decision = review()
                evidence["status"] = "accepted" if action == "accept_evidence" else "rejected"
                evidence["decision"] = decision
                if action == "accept_evidence":
                    # Active schedule is a reviewed plan within the already locked
                    # allowance; it is not a change to the numerical oracle.
                    doc["exploration_plan"] = {"conditions": evidence["after"], "review": decision, "contract_sha256": contract["sha256"], "sha256": digest({"conditions": evidence["after"], "review": decision})}
                doc["status"] = "reproduced"
            elif action == "register_confirmation":
                require(doc["reproduction_accepted"] and doc["exploration_complete"], "exploration_required", "Accept reproduction and finish discovery before registration.")
                require(not doc.get("registration"), "confirmation_already_registered", "This folio already froze its one confirmation test. Its condition cannot be changed.")
                condition_id = body.get("condition_id")
                allowed = {c["id"]: c for c in contract["allowed_conditions"]}
                observed = {o["condition_id"] for o in doc["observations"]}
                require(condition_id in allowed and condition_id in observed, "unobserved_condition", "Select a completed condition from the registered finite lattice.")
                reviewer_info = review()
                split_sha = contract.get("confirmation_split_sha256") or doc.get("confirmation_split_sha256")
                require(isinstance(split_sha, str) and len(split_sha) == 64, "split_hash_missing", "The sealed confirmation split digest is missing.")
                signature = digest({"split": split_sha, "condition_id": condition_id, "numerical_spec": contract.get("numerical_spec_sha256"), "trusted_implementation": doc.get("trusted_code"), "practical_delta": contract["practical_delta"], "alpha": contract["alpha"]})
                prior_holdout = self.store.db.execute("SELECT * FROM holdouts WHERE split_sha=?", (split_sha,)).fetchone()
                require(not prior_holdout or prior_holdout["signature"] == signature, "holdout_already_used", "These confirmation labels were already registered for a different analysis across this workspace. A new folio cannot reset that exposure. New confirmatory inference requires fresh held-out data or a predeclared joint family.")
                registration = {"condition_id": condition_id, "registered_at": now(), "reviewer_name": reviewer,
                                "review": reviewer_info, "contract_sha256": contract["sha256"], "analysis": contract["analysis"],
                                "confirmation_split_sha256": split_sha, "numerical_spec_sha256": contract.get("numerical_spec_sha256"),
                                "trusted_code_sha256": digest(doc.get("trusted_code")),
                                "signature": signature, "holdout_status": "reproducibility_replay" if prior_holdout else "first_registered_use", "prior_folio_id": prior_holdout["folio_id"] if prior_holdout else None}
                registration["sha256"] = digest(registration)
                if not prior_holdout:
                    self.store.db.execute("INSERT INTO holdouts VALUES(?,?,?,?)", (split_sha, signature, folio_id, canonical(registration).decode()))
                doc.update(registration=registration, status="confirmation_locked", stage="confirmation")
            elif action == "review_conclusion":
                require(doc.get("verification") is not None and doc.get("conclusion") is not None, "verification_required", "Complete independent verification before acknowledging the conclusion.")
                doc["conclusion"]["review"] = review()
                doc["status"] = "complete"
            elif action == "cancel":
                require(bool(active), "nothing_running", "There is no active attempt to cancel.")
                cancel_job = self._current_job(doc["run"]["id"])
                cancel_job.update(fence=cancel_job["fence"] + 1, status="cancel_requested", updated_at=now())
                self._save_job(cancel_job)
                doc.update(status="cancel_requested", run=self._public_job(cancel_job))
            elif action == "resume":
                require(bool(doc.get("run")) and doc["run"]["status"] in {"failed", "cancelled", "interrupted"}, "not_resumable", "Only an interrupted, failed or cancelled operational attempt can be resumed.")
                resume_from = self._current_job(doc["run"]["id"])
                long_action = resume_from["action"]
            else:
                long_action = action
                if action == "reproduce":
                    require(contract.get("locked") and not doc["reproduction_accepted"] and not doc.get("registration"), "review_required", "Lock the contract before original-condition reproduction; accepted reproduction is immutable.")
                elif action in {"retrieve", "explore"}:
                    require(doc["reproduction_accepted"] and not doc.get("registration") and not doc["exploration_complete"], "discovery_gate", "Accept reproduction before discovery; a completed search or registered confirmation cannot be expanded.")
                    if action == "retrieve":
                        require(doc.get("evidence_change") is None, "retrieval_recorded", "This folio already contains a retrieval decision. Inspect its retained receipt.")
                    elif doc.get("evidence_change"):
                        require(doc["evidence_change"]["status"] != "proposed", "evidence_review_required", "Accept or reject the proposed evidence change before executing discovery.")
                elif action == "confirm":
                    require(doc.get("registration") is not None and not doc.get("prediction_manifest") and not doc.get("verification"), "registration_required", "Register one confirmation condition before prediction. Completed confirmation is not rerun as new inference.")
                elif action == "verify":
                    require(doc.get("prediction_manifest") is not None and not doc.get("verification"), "predictions_required", "Generate registered confirmation predictions before verification.")
            if long_action:
                queued_job = self._queue(doc, long_action, resume_from)
            self.store._save(doc)
            self.store._event(folio_id, action, action.replace("_", " ").capitalize() + " recorded.", detail={"reviewer_name": reviewer or None})
            self.store.db.execute("INSERT INTO idempotency VALUES(?,?,?)", (key, fingerprint, folio_id))
        if cancel_job:
            task = self.tasks.get(cancel_job["id"])
            if task:
                task.cancel()
        if queued_job:
            self._schedule(queued_job)
        return self.store.get(folio_id)
