"""Bounded trusted subprocess orchestration. Provider secrets are never inherited."""

import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .api import contract_signature, validate_contract
from .common import ScienceError, artifact, atomic_result, digest, file_hash, immutable_bytes, immutable_json, inside, read_json, source_digests, utc_now, verify_file
from .prepare import load_prepared
from .spec import CONDITIONS, NUMERICAL_SPEC


def minimal_environment():
    return {"PATH": os.defpath, "PYTHONPATH": str(Path(__file__).parent.parent), "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1", "PYTHONHASHSEED": "0", "LANG": "en_US.UTF-8", "TZ": "UTC",
            "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "BLIS_NUM_THREADS": "1"}


def _limits():
    cpu = NUMERICAL_SPEC["worker"]["cpu_seconds"]
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    size = NUMERICAL_SPEC["worker"]["max_output_bytes"]
    resource.setrlimit(resource.RLIMIT_FSIZE, (size, size))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))


def _run(module, args, work_dir, receipt_path):
    command = [sys.executable, "-m", module, *map(str, args)]
    portable_command = ["python", "-m", module] + [os.path.relpath(str(value), work_dir) if Path(str(value)).is_absolute() else str(value) for value in args]
    def safe_log(value):
        value = value.decode(errors="replace")[-2000:]
        for absolute, replacement in [(str(Path(__file__).parent.parent), "<source>"), (str(Path(work_dir).resolve()), "<worker-cwd>"), (str(Path.home()), "<home>")]:
            value = value.replace(absolute, replacement)
        return value
    portable = {"command": portable_command, "cwd": ".", "command_representation": "Portable: interpreter named python, path arguments relative to worker cwd. Runtime Python version is retained in training receipts."}
    started_at, started = utc_now(), time.perf_counter()
    # Keep the parent's process group so API cancellation also kills descendants.
    child = subprocess.Popen(command, cwd=work_dir, env=minimal_environment(), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, preexec_fn=_limits)
    old_handlers = {}

    def stop(signum, frame):
        child.terminate()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        raise ScienceError("CANCELLED", "Trusted numerical worker stopped; incomplete output is not scientific evidence", True)

    for signum in [signal.SIGTERM, signal.SIGINT]:
        old_handlers[signum] = signal.signal(signum, stop)
    try:
        stdout, stderr = child.communicate(timeout=NUMERICAL_SPEC["worker"]["wall_seconds"])
    except subprocess.TimeoutExpired as exc:
        child.kill()
        stdout, stderr = child.communicate()
        immutable_json(receipt_path, {**portable, "status": "timeout", "started_at": started_at,
                                     "elapsed_seconds": time.perf_counter() - started,
                                     "stdout": safe_log(stdout), "stderr": safe_log(stderr)})
        raise ScienceError("WORKER_TIMEOUT", "Registered wall-time bound exceeded; no scientific conclusion", True) from exc
    finally:
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)
    immutable_json(receipt_path, {**portable, "status": "succeeded" if child.returncode == 0 else "failed",
                                 "exit_code": child.returncode, "pid": child.pid, "started_at": started_at,
                                 "elapsed_seconds": time.perf_counter() - started,
                                 "stdout": safe_log(stdout), "stderr": safe_log(stderr),
                                 "environment_keys": sorted(minimal_environment()), "isolation": "Same OS identity; trusted authored code only; no kernel filesystem/network sandbox"})
    if child.returncode:
        # A structured worker error can be relayed, never its arbitrary traceback.
        try:
            parsed = json.loads(stdout.decode().strip().splitlines()[-1])
            error = parsed.get("error", {})
        except (ValueError, IndexError):
            error = {}
        raise ScienceError(error.get("code", "WORKER_FAILED"), error.get("message", "Trusted numerical subprocess failed; inspect its execution receipt"), True)


def _new_attempt(root, label):
    path = root / "attempts" / f"{label}-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def _prediction(root, prepared, manifest, contract, split, condition_ids, label):
    attempt = _new_attempt(root, label)
    capsule = attempt / "input"
    capsule.mkdir()
    for src, name in [(manifest["splits"]["train"]["features"], "train.csv"),
                      (manifest["splits"][split]["features"], "evaluation.csv")]:
        immutable_bytes(capsule / name, verify_file(root, src).read_bytes())
    task = {"schema_version": "crucible.predictor-task.v1", "numerical_spec_sha256": prepared["numerical_spec_sha256"],
            "source_code": prepared["trusted_code"], "contract_signature": contract_signature(contract),
            "split": split, "condition_ids": condition_ids,
            "training": {"name": "train.csv", "sha256": manifest["splits"]["train"]["features"]["sha256"]},
            "evaluation": {"name": "evaluation.csv", "sha256": manifest["splits"][split]["features"]["sha256"]}}
    immutable_json(capsule / "task.json", task)
    output = attempt / "output"
    _run("science.predictor", ["--manifest", capsule / "task.json", "--output-dir", output], capsule, attempt / "execution.json")
    receipt = read_json(output / "receipt.json")
    predictions = artifact(root, output / "predictions.csv", "unlabeled_predictions", "text/csv")
    if predictions["sha256"] != receipt["predictions"]["sha256"]:
        raise ScienceError("ARTIFACT_TAMPERED", "Worker prediction receipt hash mismatch")
    envelope = {"schema_version": "crucible.prediction-envelope.v1", "split": split,
                "condition_ids": condition_ids, "contract_signature": contract_signature(contract),
                "predictions": predictions, "receipt": artifact(root, output / "receipt.json", "training_receipt"),
                "input_manifest": artifact(root, capsule / "task.json", "prediction_input_manifest"),
                "execution": artifact(root, attempt / "execution.json", "execution_receipt")}
    receipts = [{"id": f"cpu-{predictions['sha256'][:18]}-{attempt.name[-8:]}", "kind": "training", "provider": "local CPU",
                 "model": "RandomForestClassifier / LogisticRegression", "status": "succeeded", "started_at": receipt["started_at"],
                 "elapsed_ms": round(receipt["wall_seconds"] * 1000), "purpose": label,
                 "cpu_seconds": receipt["cpu_seconds"], "peak_rss_bytes": receipt["peak_rss_bytes"],
                 "fit_count": len(receipt["fit_receipts"]), "threads": 1}]
    return envelope, receipts


def _oracle(root, request):
    attempt = _new_attempt(root, f"verify-{request['phase']}")
    request = {**request, "root": os.path.relpath(root, attempt)}
    immutable_json(attempt / "request.json", request)
    output = attempt / "result.json"
    try:
        _run("science.verifier", ["--request", attempt / "request.json", "--output", output], attempt, attempt / "execution.json")
    except ScienceError:
        if output.exists():
            result = read_json(output)
            if result.get("error"):
                error = result["error"]
                raise ScienceError(error["code"], error["message"], error.get("recoverable", False))
        raise
    result = read_json(output)
    if result.get("error"):
        error = result["error"]
        raise ScienceError(error["code"], error["message"], error.get("recoverable", False))
    result["artifacts"].append(artifact(root, attempt / "execution.json", "verifier_execution"))
    return result


def _context(request):
    if not request.get("root"):
        raise ScienceError("ROOT_REQUIRED", "A prepared case root is required")
    root = Path(request["root"]).resolve()
    prepared, manifest = load_prepared(root)
    contract = validate_contract(request.get("contract"), prepared)
    return root, prepared, manifest, contract


def _public_prediction_artifacts(envelope):
    return [envelope[key] for key in ["predictions", "receipt", "input_manifest", "execution"]]


def reproduce(request):
    root, prepared, manifest, contract = _context(request)
    saved = root / "reproduction-result.json"
    if saved.exists():
        result = read_json(saved)
        if result["contract_signature"] != contract_signature(contract):
            raise ScienceError("CONTRACT_MISMATCH", "Reproduction is bound to another contract")
        for record in result["artifacts"]:
            verify_file(root, record)
        return {**result, "replay": {**result["replay"], "cached": True}}
    first, receipts = _prediction(root, prepared, manifest, contract, "discovery", ["original"], "reproduction")
    second, replay_receipts = _prediction(root, prepared, manifest, contract, "discovery", ["original"], "deterministic-replay")
    first_receipt = read_json(inside(root, first["receipt"]["path"]))
    second_receipt = read_json(inside(root, second["receipt"]["path"]))
    identical = (first["predictions"]["sha256"] == second["predictions"]["sha256"] and
                 [r["fitted_state_sha256"] for r in first_receipt["fit_receipts"]] ==
                 [r["fitted_state_sha256"] for r in second_receipt["fit_receipts"]])
    if not identical:
        raise ScienceError("REPRODUCTION_DISAGREEMENT", "Two clean fixed-seed subprocess fits disagreed; no challenge confirmation is justified")
    result = _oracle(root, {"contract": contract, "phase": "reproduction", "condition_ids": ["original"], "prediction_manifest": first})
    result.update({"contract_signature": contract_signature(contract), "prediction_manifest": first,
                   "replay_prediction_manifest": second,
                   "replay": {"identical_predictions": True, "identical_fitted_states": True,
                              "first_sha256": first["predictions"]["sha256"], "replay_sha256": second["predictions"]["sha256"],
                              "scope": "Two separate clean subprocesses in the same installed environment; not two independently provisioned environments", "cached": False}})
    result["receipts"] = receipts + replay_receipts + result["receipts"]
    result["artifacts"] += _public_prediction_artifacts(first) + _public_prediction_artifacts(second)
    immutable_json(saved, result)
    return result


def explore(request):
    root, prepared, manifest, contract = _context(request)
    if request.get("reproduction_accepted") is not True or not (root / "reproduction-result.json").exists():
        raise ScienceError("REPRODUCTION_REQUIRED", "Accept the completed original reproduction before discovery exploration", True)
    if (root / "confirmation-registration.json").exists():
        raise ScienceError("CONFIRMATION_FROZEN", "Discovery cannot be expanded after confirmation registration")
    conditions = request.get("active_conditions", contract["active_conditions"])
    allowed = {c["id"] for c in CONDITIONS}
    if not isinstance(conditions, list) or not conditions or len(conditions) != len(set(conditions)) or "original" not in conditions or not set(conditions) <= allowed:
        raise ScienceError("INVALID_CONDITION", "Reviewed discovery schedule must be unique IDs in the finite lattice, including original")
    schedule = {"condition_ids": conditions, "contract_signature": contract_signature(contract)}
    saved = root / "discovery" / f"{digest(schedule)}.json"
    if saved.exists():
        result = read_json(saved)
        for record in result["artifacts"]:
            verify_file(root, record)
        return {**result, "replay": True}
    envelope, receipts = _prediction(root, prepared, manifest, contract, "discovery", conditions, "finite-discovery")
    result = _oracle(root, {"contract": contract, "phase": "discovery", "condition_ids": conditions, "prediction_manifest": envelope})
    result["prediction_manifest"] = envelope
    result["receipts"] = receipts + result["receipts"]
    result["artifacts"] += _public_prediction_artifacts(envelope)
    result["schedule"] = {**schedule, "stopping_rule": "Run every reviewed active condition and every declared seed once; no adaptive lattice expansion"}
    immutable_json(saved, result)
    return result


def _freeze_registration(root, request, prepared, contract):
    incoming = request.get("registration") or {}
    condition_id = request.get("condition_id") or incoming.get("condition_id")
    if condition_id not in {c["id"] for c in CONDITIONS}:
        raise ScienceError("REGISTRATION_REQUIRED", "Register one allowed condition before confirmation", True)
    if not incoming.get("registered_at") or not incoming.get("reviewer_name"):
        raise ScienceError("REGISTRATION_REQUIRED", "Confirmation registration needs the local reviewer's name and timestamp", True)
    body = {"schema_version": "crucible.confirmation-registration.v1", "condition_id": condition_id,
            "registered_at": incoming["registered_at"], "reviewer_name": incoming["reviewer_name"],
            "contract_signature": contract_signature(contract), "analysis": contract["analysis"],
            "practical_delta": contract["practical_delta"], "numerical_spec_sha256": prepared["numerical_spec_sha256"],
            "trusted_code_sha256": prepared["trusted_code_sha256"],
            "confirmation_split_sha256": prepared["confirmation_split_sha256"]}
    registration = {**body, "sha256": digest(body)}
    saved = root / "confirmation-registration.json"
    if saved.exists():
        existing = read_json(saved)
        stable = ["condition_id", "contract_signature", "analysis", "practical_delta", "numerical_spec_sha256", "trusted_code_sha256", "confirmation_split_sha256"]
        if any(existing.get(key) != registration.get(key) for key in stable):
            raise ScienceError("HOLDOUT_ALREADY_REGISTERED", "This holdout was already registered to another condition/analysis; adaptive reuse is forbidden")
        return existing
    immutable_json(saved, registration)
    return registration


def predict(request):
    root, prepared, manifest, contract = _context(request)
    if request.get("reproduction_accepted") is not True or not (root / "reproduction-result.json").exists():
        raise ScienceError("REPRODUCTION_REQUIRED", "Accept deterministic reproduction before registered confirmation", True)
    registration = _freeze_registration(root, request, prepared, contract)
    saved = root / "confirmation-prediction.json"
    if saved.exists():
        result = read_json(saved)
        if result["prediction_manifest"]["registration_sha256"] != registration["sha256"]:
            raise ScienceError("REGISTRATION_MISMATCH", "Cached prediction belongs to a different registration")
        for record in result["artifacts"]:
            verify_file(root, record)
        return {**result, "replay": True}
    envelope, receipts = _prediction(root, prepared, manifest, contract, "confirmation", [registration["condition_id"]], "registered-confirmation")
    envelope["registration_sha256"] = registration["sha256"]
    result = {"prediction_manifest": envelope, "artifacts": _public_prediction_artifacts(envelope) + [artifact(root, root / "confirmation-registration.json", "confirmation_registration")],
              "receipts": receipts, "observations": [], "holdout_status": "Predictions sealed; labels not yet joined by verifier"}
    immutable_json(saved, result)
    return result


def verify(request):
    root, prepared, manifest, contract = _context(request)
    if not (root / "confirmation-prediction.json").exists():
        raise ScienceError("PREDICTION_REQUIRED", "Complete registered confirmation prediction before verification", True)
    registration = _freeze_registration(root, request, prepared, contract)
    stored = read_json(root / "confirmation-prediction.json")
    return _oracle(root, {"contract": contract, "phase": "confirmation", "condition_ids": [registration["condition_id"]],
                          "prediction_manifest": stored["prediction_manifest"], "reproduction_accepted": request.get("reproduction_accepted") is True})


def reverify(request):
    root, prepared, manifest, contract = _context(request)
    if not (root / "confirmation-verification.json").exists():
        raise ScienceError("VERIFICATION_REQUIRED", "Offline re-verification requires a completed verified evidence package")
    result = verify(request)
    result["replay"] = {"kind": "no-inference re-verification", "numerical_agreement": True}
    return result


def rerun(request):
    root, prepared, manifest, contract = _context(request)
    if not (root / "confirmation-verification.json").exists():
        raise ScienceError("VERIFICATION_REQUIRED", "Offline rerun requires completed evidence; it cannot open a new hypothesis")
    originals = [("discovery", read_json(root / "reproduction-result.json")["prediction_manifest"], "original")]
    active = request.get("active_conditions", contract["active_conditions"])
    schedule = {"condition_ids": active, "contract_signature": contract_signature(contract)}
    discovery = root / "discovery" / f"{digest(schedule)}.json"
    if discovery.exists():
        originals.append(("discovery", read_json(discovery)["prediction_manifest"], "discovery"))
    originals.append(("confirmation", read_json(root / "confirmation-prediction.json")["prediction_manifest"], "confirmation"))
    comparisons, artifacts, receipts = [], [], []
    for split, original, label in originals:
        envelope, timing = _prediction(root, prepared, manifest, contract, split, original["condition_ids"], f"offline-{label}-replay")
        if envelope["predictions"]["sha256"] != original["predictions"]["sha256"]:
            raise ScienceError("RERUN_DISAGREEMENT", f"Fixed-plan {label} rerun predictions differ from retained evidence")
        comparisons.append({"phase": label, "identical_predictions": True,
                            "original_sha256": original["predictions"]["sha256"], "rerun_sha256": envelope["predictions"]["sha256"]})
        artifacts += _public_prediction_artifacts(envelope)
        receipts += timing
    return {"replay": {"kind": "no-inference fixed-plan retraining", "identical_predictions": True, "comparisons": comparisons},
            "receipts": receipts, "artifacts": artifacts}
