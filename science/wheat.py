"""Trusted source-informed wheat experiment and immutable evidence interface.

No model code is accepted from a manifest. Torch is imported only in the separate
authored detector process. Final labels and photographs stay private until the
complete preregistered family has produced predictions and the oracle opens it.
"""

import copy
import io
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

from .common import ScienceError, artifact, atomic_result, canonical_bytes, digest, file_hash, immutable_bytes, immutable_json, inside, read_json, utc_now, verify_file

SCHEMA = "crucible.wheat.v1"
RECIPES = [
    {"id": "native_full", "label": "Native full image", "width": 1024, "mode": "full"},
    {"id": "native_noop", "label": "Pixel-identical no-op", "width": 1024, "mode": "full"},
    {"id": "retain_768", "label": "768 pixels retained before upload", "width": 768, "mode": "full"},
    {"id": "retain_512", "label": "512 pixels retained before upload", "width": 512, "mode": "full"},
    {"id": "retain_256", "label": "256 pixels retained before upload", "width": 256, "mode": "full"},
    {"id": "native_tiles", "label": "Native SAHI tiles", "width": 1024, "mode": "tiles"},
    {"id": "degraded_tiles256", "label": "256-pixel upload then SAHI tiles", "width": 256, "mode": "tiles"},
    {"id": "native_multiscale", "label": "Native multiscale (matched forward count)", "width": 1024, "mode": "multiscale"},
]
TRAINING = {"seeds": [11, 29, 47], "epochs": 10, "batch_size": 4, "effective_batch_size": 4, "optimizer": "Adam", "learning_rate": 0.0001,
            "betas": [0.9, 0.999], "epsilon": 1e-8, "weight_decay": 0.0001,
            "order": "Sorted image_id inventory; full per-seed/per-epoch shuffle using a separate CPU Python random.Random generator",
            "order_seed_mapping": "seed*100000+epoch; collision-free for the three declared seeds and epochs1..10; Python version retained",
            "selection": "final epoch 10 only; no validation, tuning, early stopping or checkpoint selection",
            "model": "fasterrcnn_resnet50_fpn", "initialization": "ResNet50_Weights.IMAGENET1K_V1",
            "classes": ["background", "wheat_head"], "min_size": 800, "max_size": 1333,
            "trainable_backbone_layers": 3, "box_detections_per_img": 1000, "box_nms_thresh": 0.5,
            "box_score_thresh": 0.05, "inference_score_threshold": 0.5}
SPEC = {"schema_version": SCHEMA, "experiment_type": "new_source_informed_experiment", "training": TRAINING,
        "recipes": RECIPES, "transform": {"resampler": "Pillow LANCZOS", "upload_encoding": "Lossless PNG compress_level6 optimizeFalse at every width",
        "canvas": "Decode original RGB; resize retained width proportionally, encode/decode lossless PNG at every width, restore original canvas with LANCZOS. Native and no-op have identical encoded upload bytes and source-identical decoded pixels; originals retained separately.",
        "physical_interpretation": "Digital pixels retained before upload; no altitude, sensor, biology or physical blur interpretation"},
        "tiling": {"library": "SAHI", "slice_height": 512, "slice_width": 512, "overlap_height_ratio": 0.2, "overlap_width_ratio": 0.2,
        "postprocess": "SAHI NMSPostprocess", "match_metric": "IOU", "match_threshold": 0.5, "standard_full_image_prediction": False},
        "multiscale": {"min_sizes": [640, 680, 720, 760, 800, 840, 880, 920, 960], "max_size": 1333,
        "postprocess": "SAHI NMSPostprocess IOU0.5", "resource_claim": "Same nine forward calls for audited 1024-square images; tensor pixels, runtime and memory may differ. No equal-cost claim."},
        "metric": "equal-session image count MAE, signed bias, precision, recall, TP/(TP+FP+FN) at IoU>=0.5 and duplicates; authored score-ordered one-to-one matching",
        "analysis": "Fixed finite corpus. No confidence interval, p-value, deployment acceptance or independence claim. Sessions may share locations/plots. Empty/empty detection accuracy1, undefined precision/recall remain null.",
        "final": "One selected policy plus fixed native_full/native_tiles/native_multiscale controls; all registered predictions before any final labels joined; no adaptive final expansion",
        "worker": {"train_wall_seconds": 604800, "prediction_wall_seconds": 172800, "threads": 1, "max_file_bytes": 8589934592},
        "replay": {"coordinate_atol": 0.001, "score_atol": 0.00001, "prediction_count": "exact", "scope": "fresh inference from the retained fixed trained checkpoint; no retraining implied"}}
LIMITATIONS = ["New source-informed wheat experiment; not a reproduction of original WILDS settings or its metric.",
               "Public benchmark data, not fresh prospective field evidence. Historic public exposure cannot be excluded.",
               "Session/location independence, independent CV review and practitioner acceptance requirements are not established.",
               "Finite-corpus measurements cannot establish a deployment policy, yield benefit, adoption or algorithmic novelty.",
               "SAHI is established prior work. Multiscale matches forward count, not measured compute or cost.",
               "Separate trusted processes share one OS identity; this is neither hostile-code isolation nor independent human review."]
DISK_RESERVE = 2 * 1024**3


def ensure_free_space(root, incremental_bytes, stage):
    root = Path(root)
    while not root.exists():
        root = root.parent
    free = shutil.disk_usage(root).free
    if free < incremental_bytes + DISK_RESERVE:
        raise ScienceError("INSUFFICIENT_STORAGE", f"{stage} needs {incremental_bytes} additional bytes plus {DISK_RESERVE} reserve; {free} bytes free. Corpus/model/epochs remain unchanged.", True)
    return {"stage": stage, "free_bytes": free, "additional_bytes": incremental_bytes, "reserve_bytes": DISK_RESERVE}


def full_storage_plan(root, manifest):
    images = sum(row["image"]["bytes"] for rows in manifest["splits"].values() for row in rows)
    discovery, final = len(manifest["splits"]["discovery"]), len(manifest["splits"]["confirmation"])
    model, resumes, atomic = 192 * 1024**2, 3 * 576 * 1024**2, 576 * 1024**2
    predictions = 92 * TRAINING["box_detections_per_img"] * len(TRAINING["seeds"]) * (32 * discovery + 28 * final)
    ancillary = 768 * 1024**2
    portable = math.ceil((images + 3 * model + 128 * 1024**2 + predictions + ancillary) * 1.05) + 16 * 1024**2
    total = resumes + atomic + 3 * model + 128 * 1024**2 + predictions + ancillary + portable
    root = Path(root).resolve()
    # Source bytes passed a separate ingestion gate. Worker-input aliases and
    # failed/unreferenced outputs cannot offset required future allocations.
    seen = set()
    for directory in ("images", "source", "sealed", "frozen_source"):
        for path in (root / directory).rglob("*"):
            if path.is_file():
                stat = path.stat()
                seen.add((stat.st_dev, stat.st_ino))

    def regular(path):
        # Exclude both symlinked files and symlinked parent directories.
        return path.resolve() == path and path.is_file()

    def retained_json(path):
        if regular(path):
            try:
                value = read_json(path)
                return value if isinstance(value, dict) else {}
            except ScienceError:
                pass
        return {}

    def credit(path, expected_hash, cap):
        if not isinstance(expected_hash, str) or len(expected_hash) != 64 or not regular(path):
            return 0
        stat = path.stat()
        identity = (stat.st_dev, stat.st_ino)
        if identity in seen or file_hash(path) != expected_hash:
            return 0
        seen.add(identity)
        # Sparse logical length is not already-allocated capacity. No credit on
        # platforms where allocated-byte accounting is unavailable.
        return min(cap, stat.st_size, getattr(stat, "st_blocks", 0) * 512)

    existing = 0
    plan = retained_json(root / "training-plan.json")
    if plan.get("training") == TRAINING:
        initialization = plan.get("initialization") or {}
        if isinstance(initialization, dict):
            existing += credit(root / "model" / "initialization.pt", initialization.get("sha256"), 128 * 1024**2)
        for seed in TRAINING["seeds"]:
            seed_root = root / "model" / ("seed-" + str(seed))
            epochs = seed_root / "epochs"
            diagnostics = [retained_json(epochs / ("epoch-%02d.json" % epoch)) for epoch in range(1, TRAINING["epochs"] + 1)]
            completed = [row for epoch, row in enumerate(diagnostics, 1) if row.get("epoch") == epoch]
            if completed:
                existing += credit(epochs / "latest-resume.pt", completed[-1].get("resumable_checkpoint_sha256_at_epoch"), 576 * 1024**2)
            fit = retained_json(seed_root / "training-receipt.json")
            if fit.get("plan_sha256") == digest({**plan, "seed": seed}) and fit.get("epochs_completed") == TRAINING["epochs"]:
                existing += credit(epochs / "epoch-10.pt", fit.get("checkpoint_sha256"), model)
    return {"source_image_bytes_already_ingested": images, "latest_adam_states_bytes": resumes, "atomic_checkpoint_temp_bytes": atomic,
            "three_final_models_bytes": 3 * model, "prediction_arrays_upper_bound_bytes": predictions, "ancillary_outputs_budget_bytes": ancillary,
            "portable_zip_upper_bound_bytes": portable, "canonical_model_slots_credit_bytes": existing,
            "remaining_full_pipeline_bytes": total - existing, "reserve_bytes": DISK_RESERVE,
            "scope": "Separate ingestion gate; complete corpus/3seeds/10epochs and one ZIP. Only hash-bound canonical model slots offset their capped allocated bytes; atomic, prediction, ancillary and ZIP reserves remain protected for retries. Lossless float64 NPZ bound assumes full cap, not favorable outcomes."}


def code_digests():
    folder = Path(__file__).parent
    return {p.name: file_hash(p) for p in sorted([folder / "__init__.py", folder / "common.py", *folder.glob("wheat*.py")])}


def metadata():
    contract = {"schema_version": SCHEMA, "adapter_id": "wheat", "experiment_type": "new_source_informed_experiment",
                "claim": "Measure count and localization changes caused by fixed pixels-retained-before-upload and inference recipes on this finite public wheat corpus.",
                "population": "The pinned public wheat photographs and acquisition-session labels only", "metric": SPEC["metric"],
                "analysis": SPEC["analysis"], "allowed_recipes": copy.deepcopy(RECIPES), "training": copy.deepcopy(TRAINING),
                "numerical_spec_sha256": digest(SPEC), "confirmation_split_sha256": None, "corpus_sha256": None,
                "source_manifest_sha256": None,
                "dependency_lock_sha256": None,
                "acceptance_requirement": None, "locked": False}
    return {"adapter_id": "wheat", "title": "Wheat heads: pixels retained before upload", "case_kind": "new_source_informed_experiment",
            "independence_established": False, "contract": contract, "recipes": copy.deepcopy(RECIPES), "limitations": LIMITATIONS[:]}


def training_order(image_ids, seed, epoch):
    """Full inventory permutation, independent of global/model RNG and outcomes."""
    import random
    if seed not in TRAINING["seeds"] or not 1 <= epoch <= TRAINING["epochs"] or not image_ids or len(set(image_ids)) != len(image_ids):
        raise ScienceError("TRAINING_PLAN_CHANGED", "Invalid fixed shuffle seed/epoch/inventory")
    order = sorted(image_ids)
    random.Random(seed * 100000 + epoch).shuffle(order)
    return order


def signature(contract):
    return digest({k: v for k, v in contract.items() if k not in ("locked", "approval", "reviewer_name", "reviewed_at")})


def validate_contract(contract, prepared):
    if not isinstance(contract, dict) or contract.get("locked") is not True:
        raise ScienceError("CONTRACT_NOT_LOCKED", "Lock the authored wheat contract before execution", True)
    expected = prepared["contract"]
    for key in expected:
        if key not in ("locked", "approval", "reviewer_name", "reviewed_at") and contract.get(key) != expected[key]:
            raise ScienceError("ORACLE_PROTECTED", "Trusted wheat contract field changed: " + key)
    return contract


def _source_path(base, value):
    # An explicit trusted asset manifest can refer to its own relative files.
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return inside(base, value)


def _normalize_records(source, base):
    from PIL import Image
    from .wheat_metrics import checked_box
    rows = source.get("records", source.get("images"))
    if not isinstance(rows, list) or not rows:
        raise ScienceError("SOURCE_SCHEMA", "Asset manifest needs a nonempty records/images list")
    result, identities, hashes, session_roles, group_roles = [], set(), set(), {}, {}
    for row in rows:
        image_id = str(row.get("image_id", row.get("id", "")))
        role = row.get("split", row.get("role"))
        role = "confirmation" if role == "final" else role
        if not image_id or not image_id.replace("-", "").replace("_", "").isalnum() or role not in ("train", "discovery", "confirmation"):
            raise ScienceError("SOURCE_SCHEMA", "Invalid image identity or role")
        path = _source_path(base, row.get("path", row.get("image_path", "")))
        sha = file_hash(path)
        if row.get("sha256") != sha:
            raise ScienceError("SOURCE_HASH_MISMATCH", "Image differs from asset manifest: " + image_id)
        with Image.open(path) as image:
            width, height = image.size
            encoded_format = image.format
            media_type = Image.MIME.get(encoded_format, "application/octet-stream")
            pixel_sha = __import__("hashlib").sha256(image.convert("RGB").tobytes()).hexdigest()
        if row.get("encoded_format", encoded_format) != encoded_format:
            raise ScienceError("SOURCE_HASH_MISMATCH", "Declared image codec differs from source bytes: " + image_id)
        if row.get("pixel_sha256") is not None and row["pixel_sha256"] != pixel_sha:
            raise ScienceError("SOURCE_HASH_MISMATCH", "Declared decoded pixel hash changed: " + image_id)
        if (width, height) != (row.get("width", width), row.get("height", height)) or width != 1024 or height != 1024:
            raise ScienceError("SOURCE_SHAPE", "This fixed adapter requires audited 1024x1024 source photographs")
        if image_id in identities or pixel_sha in hashes:
            raise ScienceError("SPLIT_LEAKAGE", "Duplicate identity or pixel-identical photograph in corpus")
        identities.add(image_id)
        hashes.add(pixel_sha)
        session = str(row.get("session_id", row.get("domain", row.get("domain_id", ""))))
        group = str(row.get("group_id", session))
        if not session:
            raise ScienceError("SOURCE_SCHEMA", "Every image needs an original acquisition session identity")
        if session in session_roles and session_roles[session] != role:
            raise ScienceError("SPLIT_LEAKAGE", "An acquisition session occurs in multiple roles")
        session_roles[session] = role
        if group in group_roles and group_roles[group] != role:
            raise ScienceError("SPLIT_LEAKAGE", "A related plot/location group occurs in multiple roles")
        group_roles[group] = role
        boxes = row.get("boxes", row.get("bboxes"))
        annotation_provenance = None
        if boxes is None:
            annotation_path = _source_path(base, row.get("annotation_path", ""))
            expected = row.get("annotation_sha256")
            if not expected or file_hash(annotation_path) != expected:
                raise ScienceError("SOURCE_HASH_MISMATCH", "Annotations differ from asset manifest")
            annotations = read_json(annotation_path)
            boxes = annotations if isinstance(annotations, list) else annotations.get("boxes", annotations.get("annotations"))
            annotation_provenance = {"sha256": expected, "name": annotation_path.name}
        if not isinstance(boxes, list):
            raise ScienceError("SOURCE_SCHEMA", "Each image needs an explicit annotation list, including empty lists")
        fmt = row.get("bbox_format", source.get("bbox_format", "xywh"))
        converted = []
        for box in boxes:
            box = box.get("bbox", box.get("box")) if isinstance(box, dict) else box
            if fmt == "xywh" and isinstance(box, (list, tuple)) and len(box) == 4:
                x, y, w, h = box
                box = [x, y, x + w, y + h]
            elif fmt != "xyxy":
                raise ScienceError("SOURCE_SCHEMA", "Only explicit xywh/xyxy annotations are supported")
            converted.append(checked_box(box, width, height))
        result.append({"image_id": image_id, "split": role, "session_id": session, "group_id": group,
                       "width": width, "height": height, "sha256": sha, "pixel_sha256": pixel_sha,
                       "encoded_format": encoded_format, "media_type": media_type,
                       "source_path": path, "boxes": converted, "original_bbox_format": fmt,
                       "annotation_provenance": annotation_provenance})
    if {row["split"] for row in result} != {"train", "discovery", "confirmation"}:
        raise ScienceError("SOURCE_SCHEMA", "Fixed train, discovery and final roles must all be supplied")
    return sorted(result, key=lambda row: row["image_id"])


def prepare(request):
    root = Path(request["root"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / "prepared.json").exists():
        prepared = load(root)[0]
        if request.get("source_manifest") and file_hash(request["source_manifest"]) != prepared["source"]["sha256"]:
            raise ScienceError("SOURCE_IDENTITY_CHANGED", "Prepared wheat root already binds different source-manifest bytes")
        return prepared
    source_path = Path(request["source_manifest"]).resolve()
    source = read_json(source_path)
    dependency_bytes = {}
    for name in ("requirements-wheat.txt", "requirements-wheat.lock", "requirements-wheat-linux-cuda.lock"):
        dependency_path = Path(__file__).parent.parent / name
        if not dependency_path.is_file():
            raise ScienceError("DEPENDENCY_LOCK_REQUIRED", "Preparation needs the checked-in full wheat requirements and hash lock")
        dependency_bytes[name] = dependency_path.read_bytes()
    dependency_hashes = {name: __import__("hashlib").sha256(content).hexdigest() for name, content in dependency_bytes.items()}
    records = _normalize_records(source, source_path.parent)
    cross_filesystem = sum(row["source_path"].stat().st_size for row in records if row["source_path"].stat().st_dev != root.stat().st_dev)
    ingestion = ensure_free_space(root, cross_filesystem + 128 * 1024**2, "preparation/ingestion")
    identity_path = root / "preparation-identity.json"
    if identity_path.exists():
        identity = read_json(identity_path)
        if identity["source_manifest_sha256"] != file_hash(source_path) or identity["trusted_code"] != code_digests() or identity.get("dependency_files") != dependency_hashes:
            raise ScienceError("PREPARATION_IDENTITY_CHANGED", "Interrupted wheat preparation changed source/code")
    else:
        identity = {"created_at": utc_now(), "source_manifest_sha256": file_hash(source_path), "trusted_code": code_digests(), "dependency_files": dependency_hashes}
        immutable_json(identity_path, identity)
    immutable_bytes(root / "source" / "asset-manifest.json", source_path.read_bytes())
    manifest = {"schema_version": SCHEMA, "splits": {role: [] for role in ("train", "discovery", "confirmation")}}
    all_artifacts = [{**artifact(root, root / "source" / "asset-manifest.json", "original_source"), "private": True}]
    dependencies = {name: artifact(root, immutable_bytes(root / "environment" / name, content), "dependency_lock" if name.endswith(".lock") else "dependency_requirements", "text/plain") for name, content in dependency_bytes.items()}
    all_artifacts += list(dependencies.values())
    for row in records:
        role, image_id = row["split"], row["image_id"]
        suffix = row["source_path"].suffix.lower()
        image = root / "images" / role / (image_id + suffix)
        _link(row["source_path"], image)
        if file_hash(image) != row["sha256"]:
            raise ScienceError("SOURCE_HASH_MISMATCH", "Image changed during materialization")
        labels = immutable_json(root / "sealed" / (image_id + ".json"), {"image_id": image_id, "boxes": row["boxes"]})
        labels.chmod(0o600)
        public = {key: value for key, value in row.items() if key not in ("source_path", "boxes")}
        public["image"] = {**artifact(root, image, "wheat_image", row["media_type"]), "private": role == "confirmation"}
        public["labels"] = {**artifact(root, labels, "sealed_boxes"), "private": True}
        manifest["splits"][role].append(public)
        all_artifacts += [public["image"], public["labels"]]
    (root / "sealed").chmod(0o700)
    manifest["confirmation_split_sha256"] = digest(manifest["splits"]["confirmation"])
    immutable_json(root / "split-manifest.json", manifest)
    immutable_json(root / "numerical-spec.json", SPEC)
    frozen = []
    for name in code_digests():
        path = immutable_bytes(root / "frozen_source" / "science" / name, (Path(__file__).parent / name).read_bytes())
        frozen.append(artifact(root, path, "trusted_source", "text/x-python"))
    case = metadata()
    case["contract"].update(confirmation_split_sha256=manifest["confirmation_split_sha256"], corpus_sha256=digest(manifest), source_manifest_sha256=identity["source_manifest_sha256"], dependency_lock_sha256=dependency_hashes["requirements-wheat.lock"])
    designated = source.get("illustration_image_id")
    choices = [row for row in manifest["splits"]["discovery"] if row["image_id"] == designated] if designated else manifest["splits"]["discovery"][:1]
    if not choices:
        raise ScienceError("ILLUSTRATION_ROLE", "Pre-outcome designated illustration must belong to discovery")
    illustration = choices[0]
    source_public = {key: value for key, value in source.items() if key not in ("records", "images")}
    source_public.update({"kind": "new_source_informed_experiment", "audit": {"performed_before_training": True,
        "images": len(records), "roles": {role: len(rows) for role, rows in manifest["splits"].items()},
        "sessions": {role: len({row["session_id"] for row in rows}) for role, rows in manifest["splits"].items()},
        "duplicate_identity_or_pixel_hashes": 0, "cross_role_sessions": 0, "annotation_conversion": "xywh to continuous xyxy; no silent clipping/exclusion",
        "final_labels_not_released": True, "collection_independence": "unestablished"}, "sha256": identity["source_manifest_sha256"]})
    for name in ("preparation-identity.json", "split-manifest.json", "numerical-spec.json"):
        # The internal split manifest contains final image IDs/hashes but no box values.
        all_artifacts.append({**artifact(root, root / name, "manifest"), "private": name == "split-manifest.json"})
    all_artifacts += frozen
    prepared = {"schema_version": SCHEMA, "adapter_id": "wheat", "created_at": identity["created_at"], "source": source_public,
                "contract": case["contract"], "manifest_sha256": digest(manifest), "corpus_sha256": digest(manifest),
                "confirmation_split_sha256": manifest["confirmation_split_sha256"], "numerical_spec_sha256": digest(SPEC),
                "trusted_code": code_digests(), "trusted_code_sha256": digest(code_digests()), "source_files": frozen,
                "source_snapshot_dir": "frozen_source", "data_artifacts": all_artifacts,
                "dependencies": {"files": dependencies, "provenance": "Exact checked-in requirements-wheat.txt, full transitive requirements-wheat.lock and supplemental requirements-wheat-linux-cuda.lock bytes, frozen at preparation. Installation recipes only; Linux/CUDA installation and execution remain unqualified until actual host checks and receipts. Actual executed environments are reported separately in per-seed training receipts."},
                "artifacts": [a for a in all_artifacts if not a.get("private") and (a["kind"] != "wheat_image" or a["sha256"] == illustration["sha256"])], "limitations": LIMITATIONS[:],
                "storage": {"ingestion": ingestion, "full_pipeline": full_storage_plan(root, manifest), "materialization": "Verified same-filesystem hardlinks. Every-stage hash checks detect source mutation; no separate storage identity. Cross-filesystem fallback budgeted before copying."},
                "illustration": {key: value for key, value in illustration.items() if key != "labels"},
                "final_image_hashes": [row["sha256"] for row in manifest["splits"]["confirmation"]],
                "final_pixel_hashes": [row["pixel_sha256"] for row in manifest["splits"]["confirmation"]],
                "illustration_selection": "Explicit source-manifest designation, otherwise lexicographically first discovery identity; chosen before fitting/outcomes"}
    immutable_json(root / "prepared.json", prepared)
    return prepared


def load(root, check_code=True):
    root = Path(root).resolve()
    prepared = read_json(root / "prepared.json")
    for record in prepared["data_artifacts"]:
        verify_file(root, record)
    manifest = read_json(root / "split-manifest.json")
    if digest(manifest) != prepared["manifest_sha256"] or digest(SPEC) != prepared["numerical_spec_sha256"]:
        raise ScienceError("MANIFEST_TAMPERED", "Wheat manifest or numerical specification changed")
    if check_code and prepared["trusted_code"] != code_digests():
        raise ScienceError("TRUSTED_CODE_CHANGED", "Wheat source changed after preparation; use a fresh case root")
    return prepared, manifest


def _context(request):
    root = Path(request["root"]).resolve()
    prepared, manifest = load(root)
    validate_contract(request.get("contract"), prepared)
    return root, prepared, manifest


def _minimal_environment():
    environment = {"PATH": os.defpath, "PYTHONPATH": str(Path(__file__).parent.parent), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
            "PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1",
            "MKL_NUM_THREADS": "1", "TZ": "UTC", "LANG": "en_US.UTF-8", "PYTORCH_ENABLE_MPS_FALLBACK": "1"}
    # Preserve the scheduler's logical GPU namespace, including an empty mask.
    environment.update({key: os.environ[key] for key in ("CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER") if key in os.environ})
    return environment


def _worker(task, attempt, training=False):
    capsule = attempt / "input"
    immutable_json(capsule / "task.json", task)
    started = time.perf_counter()
    output = attempt / "output"
    command = [sys.executable, "-m", "science.wheat_detector", "--manifest", str(capsule / "task.json"), "--output-dir", str(output)]
    def limits():
        import resource
        resource.setrlimit(resource.RLIMIT_FSIZE, (SPEC["worker"]["max_file_bytes"],) * 2)
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    try:
        completed = subprocess.run(command, cwd=capsule, env=_minimal_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=SPEC["worker"]["train_wall_seconds" if training else "prediction_wall_seconds"], preexec_fn=limits)
    except subprocess.TimeoutExpired as exc:
        immutable_json(attempt / "execution.json", {"status": "timeout", "elapsed_seconds": time.perf_counter() - started})
        raise ScienceError("WORKER_TIMEOUT", "Wheat worker exceeded the frozen wall-time bound; no scientific verdict", True) from exc
    def safe(value):
        value = value.decode(errors="replace")[-12000:]
        return value.replace(str(Path.home()), "<home>").replace(str(Path(__file__).parent.parent), "<source>")
    immutable_json(attempt / "execution.json", {"status": "succeeded" if completed.returncode == 0 else "failed", "exit_code": completed.returncode,
        "command": ["python", "-m", "science.wheat_detector", "--manifest", "task.json", "--output-dir", "../output"], "cwd": "input",
        "elapsed_seconds": time.perf_counter() - started, "stdout": safe(completed.stdout), "stderr": safe(completed.stderr),
        "environment_keys": sorted(_minimal_environment()), "isolation": "Trusted separate subprocess, same OS identity"})
    if completed.returncode:
        result_path = output / "result.json"
        error = read_json(result_path).get("error", {}) if result_path.exists() else {}
        raise ScienceError(error.get("code", "WORKER_FAILED"), error.get("message", "Wheat detector worker failed; inspect execution receipt"), True)
    return read_json(output / "result.json")


def _link(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if file_hash(destination) != file_hash(source):
            raise ScienceError("IMMUTABLE_CONFLICT", "Materialized source bytes changed")
        return
    try:
        os.link(source, destination)
    except OSError:
        ensure_free_space(destination.parent, Path(source).stat().st_size, "cross-filesystem materialization")
        immutable_bytes(destination, Path(source).read_bytes())


def _attempt(root, label):
    attempt = root / "attempts" / (label + "-" + uuid.uuid4().hex)
    (attempt / "input").mkdir(parents=True)
    return attempt


def train(request):
    root, prepared, manifest = _context(request)
    if (root / "training-result.json").exists():
        result = read_json(root / "training-result.json")
        for record in result["artifacts"]:
            verify_file(root, record)
        return {**result, "replay": "retained completed training; no new fit"}
    if (root / "final-registration.json").exists():
        raise ScienceError("CONFIRMATION_FROZEN", "Training cannot change after final registration")
    storage = full_storage_plan(root, manifest)
    ensure_free_space(root, storage["remaining_full_pipeline_bytes"], "full computation/export pipeline")
    initialization = request.get("initialization") or {}
    path = Path(initialization.get("path", "")).resolve()
    if not initialization.get("sha256") or not path.is_file() or file_hash(path) != initialization["sha256"]:
        raise ScienceError("INITIALIZATION_REQUIRED", "Supply the audited official ImageNet backbone initialization path and exact SHA256", True)
    if initialization.get("name") != TRAINING["initialization"] or not initialization.get("source_url") or not initialization.get("license"):
        raise ScienceError("INITIALIZATION_REQUIRED", "Initialization must bind ImageNet backbone name, official source URL and rights statement")
    plan = {"schema_version": SCHEMA, "training": TRAINING, "initialization": {k: v for k, v in initialization.items() if k != "path"},
            "training_split_sha256": digest(manifest["splits"]["train"]), "corpus_sha256": prepared["corpus_sha256"],
            "contract_signature": signature(request["contract"]), "numerical_spec_sha256": digest(SPEC), "trusted_code": prepared["trusted_code"],
            "device": request.get("device", "mps"), "created_at": utc_now()}
    plan_path = root / "training-plan.json"
    if plan_path.exists():
        existing = read_json(plan_path)
        if {k: v for k, v in existing.items() if k != "created_at"} != {k: v for k, v in plan.items() if k != "created_at"}:
            raise ScienceError("TRAINING_PLAN_CHANGED", "Training is already frozen to a different plan")
        plan = existing
    else:
        immutable_json(plan_path, plan)
    initial = root / "model" / "initialization.pt"
    _link(path, initial)
    if file_hash(initial) != initialization["sha256"]:
        raise ScienceError("INITIALIZATION_MISMATCH", "Materialized initialization changed")
    artifacts = [artifact(root, initial, "initialization"), artifact(root, plan_path, "training_plan")]
    checkpoints, training_receipts, receipts = [], [], []
    for seed in TRAINING["seeds"]:
        seed_root = root / "model" / ("seed-" + str(seed))
        receipt_path = seed_root / "training-receipt.json"
        final = seed_root / "epochs" / "epoch-10.pt"
        if receipt_path.exists() and final.exists():
            fit_receipt = read_json(receipt_path)
            if file_hash(final) != fit_receipt["checkpoint_sha256"] or fit_receipt["plan_sha256"] != digest({**plan, "seed": seed}):
                raise ScienceError("CHECKPOINT_MISMATCH", "Completed seed checkpoint differs from frozen plan")
        else:
            attempt = _attempt(root, "train-seed-" + str(seed))
            _link(initial, attempt / "input" / "initialization.pt")
            rows = []
            for row in manifest["splits"]["train"]:
                name = row["image_id"] + Path(row["image"]["path"]).suffix
                _link(verify_file(root, row["image"]), attempt / "input" / name)
                rows.append({"image_id": row["image_id"], "image": name, "sha256": row["sha256"], "boxes": read_json(verify_file(root, row["labels"]))["boxes"]})
            result = _worker({"stage": "train", "plan": {**plan, "seed": seed}, "initialization": "initialization.pt", "training": rows,
                              "resume_dir": os.path.relpath(seed_root / "epochs", attempt / "input")}, attempt, training=True)
            if not final.is_file() or file_hash(final) != result["checkpoint"]["sha256"]:
                raise ScienceError("CHECKPOINT_MISMATCH", "Trained checkpoint does not match worker receipt")
            fit_receipt = result["receipt"]
            immutable_json(receipt_path, fit_receipt)
            artifacts.append(artifact(root, attempt / "execution.json", "execution_receipt"))
        checkpoints.append({"seed": seed, **artifact(root, final, "trained_detector")})
        training_receipts.append({"seed": seed, **artifact(root, receipt_path, "training_receipt")})
        artifacts += [checkpoints[-1], training_receipts[-1]]
        receipts.append(_receipt(fit_receipt, "training"))
    returned = {"checkpoints": checkpoints, "checkpoint_set_sha256": digest(checkpoints), "training_receipts": training_receipts,
                "artifacts": artifacts, "receipts": receipts, "observations": []}
    immutable_json(root / "training-result.json", returned)
    return returned


def _receipt(receipt, kind):
    return {"id": kind + "-" + digest(receipt)[:18], "kind": kind, "provider": "local " + receipt.get("device", "CPU"),
            "model": TRAINING["model"], "status": "succeeded", "started_at": receipt.get("started_at"),
            "elapsed_ms": round(receipt.get("wall_seconds", 0) * 1000), "cpu_seconds": receipt.get("cpu_seconds"),
            "peak_rss_bytes": receipt.get("peak_rss_bytes"), "fit_count": 1 if kind == "training" else 0}


def _recipe_ids(values):
    if not isinstance(values, list) or not values or len(values) != len(set(values)) or not set(values) <= {r["id"] for r in RECIPES}:
        raise ScienceError("INVALID_RECIPE", "Select unique recipe IDs from the fixed finite family")
    return values


def _prediction_rows(root, envelope):
    from .wheat_storage import prediction_rows
    return list(prediction_rows(root, verify_file(root, envelope["predictions"])))


def _prediction(root, prepared, manifest, request, split, recipes, label, replay=False):
    if not replay:
        storage = full_storage_plan(root, manifest)
        ensure_free_space(root, storage["remaining_full_pipeline_bytes"], "remaining fixed computation/export pipeline")
    if not (root / "training-result.json").exists():
        raise ScienceError("TRAINING_REQUIRED", "Complete the frozen actual training before prediction", True)
    training = read_json(root / "training-result.json")
    attempt = _attempt(root, label)
    checkpoints = []
    for checkpoint in training["checkpoints"]:
        name = "model-seed-" + str(checkpoint["seed"]) + ".pt"
        _link(verify_file(root, checkpoint), attempt / "input" / name)
        checkpoints.append({"seed": checkpoint["seed"], "path": name, "sha256": checkpoint["sha256"]})
    rows = []
    for row in manifest["splits"][split]:
        name = row["image_id"] + Path(row["image"]["path"]).suffix
        _link(verify_file(root, row["image"]), attempt / "input" / name)
        rows.append({"image_id": row["image_id"], "image": name, "sha256": row["sha256"], "pixel_sha256": row["pixel_sha256"],
                     "session_id": row["session_id"], "width": row["width"], "height": row["height"]})
    task = {"stage": "predict", "split": split, "recipe_ids": recipes, "images": rows, "checkpoints": checkpoints, "checkpoint_set_sha256": training["checkpoint_set_sha256"],
            "contract_signature": signature(request["contract"]), "numerical_spec_sha256": digest(SPEC), "trusted_code": prepared["trusted_code"],
            "corpus_sha256": prepared["corpus_sha256"], "device": request.get("inference_device", "cpu"),
            "illustration_image_id": prepared["illustration"]["image_id"] if split == "discovery" else None}
    result = _worker(task, attempt)
    envelope = {"schema_version": SCHEMA, "split": split, "recipe_ids": recipes, "contract_signature": signature(request["contract"]),
                "checkpoint_set_sha256": training["checkpoint_set_sha256"], "predictions": artifact(root, attempt / "output" / "predictions.json", "unlabeled_box_predictions"),
                "receipt": artifact(root, attempt / "output" / "receipt.json", "prediction_receipt"),
                "input_manifest": artifact(root, attempt / "input" / "task.json", "prediction_input_manifest"),
                "execution": artifact(root, attempt / "execution.json", "execution_receipt")}
    generated = []
    for path in sorted((attempt / "output").glob("seed-*/*")):
        if path.suffix == ".npz" or path.name == "predictions.json":
            generated.append(artifact(root, path, "unlabeled_numeric_predictions", "application/octet-stream" if path.suffix == ".npz" else "application/json"))
    for path in sorted((attempt / "output").glob("seed-*/pixels/*")):
        generated.append({**artifact(root, path, "processed_pixels", "image/png" if path.suffix == ".png" else "image/jpeg"), "private": split == "confirmation"})
    return envelope, [_receipt(result["receipt"], "prediction")], generated


def _oracle(root, request):
    attempt = _attempt(root, "verify-" + request["phase"])
    oracle_request = {**request, "root": os.path.relpath(root, attempt)}
    immutable_json(attempt / "request.json", oracle_request)
    command = [sys.executable, "-m", "science.wheat_cli", "oracle", "--input", str(attempt / "request.json"), "--output", str(attempt / "result.json")]
    result = subprocess.run(command, cwd=attempt, env=_minimal_environment(), capture_output=True, timeout=120)
    output = read_json(attempt / "result.json")
    if result.returncode or output.get("error"):
        error = output.get("error", {})
        raise ScienceError(error.get("code", "VERIFIER_FAILED"), error.get("message", "Separate wheat oracle failed"))
    return output


def explore(request):
    root, prepared, manifest = _context(request)
    if (root / "final-registration.json").exists():
        raise ScienceError("CONFIRMATION_FROZEN", "No discovery experiments after final registration")
    recipes = _recipe_ids(request.get("recipe_ids"))
    schedule = {"recipe_ids": recipes, "contract_signature": signature(request["contract"])}
    saved = root / "discovery" / (digest(schedule) + ".json")
    if saved.exists():
        result = read_json(saved)
        for record in result["artifacts"]:
            verify_file(root, record)
        # Keep the exact immutable parent digest stable across a resumed API
        # commit. Retained receipts identify the original execution time.
        return result
    envelope, receipts, pixels = _prediction(root, prepared, manifest, request, "discovery", recipes, "discovery")
    result = _oracle(root, {"contract": request["contract"], "phase": "discovery", "prediction_manifest": envelope})
    result.update(prediction_manifest=envelope, schedule=schedule)
    result["receipts"] = receipts + result.get("receipts", [])
    result["artifacts"] += [envelope[k] for k in ("predictions", "receipt", "input_manifest", "execution")] + pixels
    result["noop_equivalence"] = noop_equivalence(root, manifest, result)
    immutable_json(saved, result)
    return result


def noop_equivalence(root, manifest, incoming=None):
    """Compare separately executed discovery cells without opening final data."""
    retained = [read_json(path) for path in sorted((root / "discovery").glob("*.json"))]
    if incoming is not None:
        retained.append(incoming)
    collected = {"native_full": {}, "native_noop": {}}
    prediction_hashes, checkpoint_sets = set(), set()
    for result in retained:
        envelope = result.get("prediction_manifest") or {}
        if not set(envelope.get("recipe_ids", [])) & set(collected):
            continue
        rows = _prediction_rows(root, envelope)
        checkpoint_sets.add(envelope["checkpoint_set_sha256"])
        prediction_hashes.add(envelope["predictions"]["sha256"])
        for row in rows:
            if row["recipe_id"] in collected:
                key = (row["image_id"], row["seed"])
                value = {"boxes": row["boxes"], "source_sha256": row["source_sha256"], "pixel_sha256": row["transform"]["processed_pixel_sha256"]}
                previous = collected[row["recipe_id"]].get(key)
                if previous is not None and previous != value:
                    raise ScienceError("NOOP_PREDICTION_DISAGREEMENT", "Repeated no-op/native predictions changed")
                collected[row["recipe_id"]][key] = value
    required = {(row["image_id"], seed) for row in manifest["splits"]["discovery"] for seed in TRAINING["seeds"]}
    complete = all(set(values) == required for values in collected.values())
    if len(checkpoint_sets) > 1 or (complete and collected["native_full"] != collected["native_noop"]):
        raise ScienceError("NOOP_PREDICTION_DISAGREEMENT", "Pixel-identical discovery no-op and native outputs differ")
    return {"status": "passed" if complete else "not_established", "passed": complete, "image_seed_pairs": len(required),
            "prediction_hashes": sorted(prediction_hashes), "scope": "Independent comparison across retained discovery envelopes; same frozen checkpoint family and original pixels"}


def freeze_registration(request):
    root, prepared, manifest = _context(request)
    incoming = request.get("registration") or {}
    policy = incoming.get("policy_id")
    _recipe_ids([policy])
    required = list(dict.fromkeys([policy, "native_full", "native_tiles", "native_multiscale"]))
    comparisons = incoming.get("comparison_recipe_ids", required)
    if comparisons != required:
        raise ScienceError("REGISTRATION_REQUIRED", "Final family must be selected policy followed by native_full/native_tiles/native_multiscale controls, deduplicated")
    if not incoming.get("registered_at") or not incoming.get("reviewer_name") or not incoming.get("parent_discovery_sha256"):
        raise ScienceError("REGISTRATION_REQUIRED", "Final registration needs reviewer, timestamp and retained discovery parent digest")
    parents = [read_json(path) for path in sorted((root / "discovery").glob("*.json"))]
    selected_parents = [parent for parent in parents if digest(parent) == incoming["parent_discovery_sha256"]]
    if not selected_parents:
        raise ScienceError("REGISTRATION_LINEAGE", "Final parent must be an exact retained discovery result digest")
    if policy not in selected_parents[0].get("prediction_manifest", {}).get("recipe_ids", []):
        raise ScienceError("REGISTRATION_LINEAGE", "Selected policy was not executed in the retained discovery parent")
    noop = noop_equivalence(root, manifest)
    if not noop["passed"]:
        raise ScienceError("NOOP_REQUIRED", "Complete and verify native_full and native_noop on every discovery image/seed before final registration", True)
    if not (root / "training-result.json").exists():
        raise ScienceError("TRAINING_REQUIRED", "Final registration requires trained fixed detector")
    training = read_json(root / "training-result.json")
    body = {"schema_version": SCHEMA, "policy_id": policy, "comparison_recipe_ids": required,
            "registered_at": incoming["registered_at"], "reviewer_name": incoming["reviewer_name"],
            "parent_discovery_sha256": incoming["parent_discovery_sha256"], "contract_signature": signature(request["contract"]),
            "checkpoint_set_sha256": training["checkpoint_set_sha256"], "training_receipts_sha256": digest(training["training_receipts"]),
            "numerical_spec_sha256": digest(SPEC), "trusted_code_sha256": prepared["trusted_code_sha256"],
            "confirmation_split_sha256": prepared["confirmation_split_sha256"], "corpus_sha256": prepared["corpus_sha256"],
            "source_manifest_sha256": prepared["source"]["sha256"],
            "analysis": SPEC["analysis"], "stopping_rule": SPEC["final"], "acceptance_requirement": None}
    body["noop_equivalence"] = noop
    registration = {**body, "sha256": digest(body)}
    saved = root / "final-registration.json"
    if saved.exists():
        existing = read_json(saved)
        stable = [key for key in body if key not in ("registered_at", "reviewer_name")]
        if any(existing.get(key) != body[key] for key in stable):
            raise ScienceError("HOLDOUT_ALREADY_REGISTERED", "Final corpus is already frozen to another policy/family/lineage")
        return existing
    immutable_json(saved, registration)
    return registration


def predict(request):
    root, prepared, manifest = _context(request)
    registration = freeze_registration(request)
    saved = root / "final-prediction.json"
    if saved.exists():
        result = read_json(saved)
        for record in result["artifacts"]:
            verify_file(root, record)
        return {**result, "replay": "retained registered prediction; no final reopening"}
    envelope, receipts, pixels = _prediction(root, prepared, manifest, request, "confirmation", registration["comparison_recipe_ids"], "final")
    envelope["registration_sha256"] = registration["sha256"]
    result = {"prediction_manifest": envelope, "receipts": receipts, "observations": [], "private_artifacts": pixels,
              "artifacts": [envelope[k] for k in ("predictions", "receipt", "input_manifest", "execution")] + [artifact(root, root / "final-registration.json", "final_registration")],
              "holdout_status": "All registered final predictions complete; labels not yet joined"}
    immutable_json(saved, result)
    return result


def verify(request):
    root, prepared, manifest = _context(request)
    registration = freeze_registration(request)
    saved = root / "final-prediction.json"
    if not saved.exists():
        raise ScienceError("PREDICTION_REQUIRED", "Complete all registered final predictions before opening labels")
    predictions = read_json(saved)
    result = _oracle(root, {"contract": request["contract"], "phase": "confirmation", "prediction_manifest": predictions["prediction_manifest"]})
    result["artifacts"] += [{**manifest["splits"]["confirmation"][0]["image"], "private": False}] + [{**a, "private": False} for a in predictions.get("private_artifacts", [])]
    result["registration"] = registration
    return result


def oracle(request):
    from .wheat_metrics import audit_inference_lineage, audit_pixels, image_metrics, summarize
    root, prepared, manifest = _context(request)
    envelope = request["prediction_manifest"]
    split = "confirmation" if request["phase"] == "confirmation" else "discovery"
    recipes = _recipe_ids(envelope["recipe_ids"])
    receipt = read_json(verify_file(root, envelope["receipt"]))
    predictions = _prediction_rows(root, envelope)
    task = read_json(verify_file(root, envelope["input_manifest"]))
    training = read_json(root / "training-result.json")
    if [row["seed"] for row in training["checkpoints"]] != TRAINING["seeds"] or training["checkpoint_set_sha256"] != digest(training["checkpoints"]):
        raise ScienceError("CHECKPOINT_MISMATCH", "Trained checkpoint family changed")
    for checkpoint, fit in zip(training["checkpoints"], training["training_receipts"]):
        verify_file(root, checkpoint)
        fit_receipt = read_json(verify_file(root, fit))
        if fit_receipt.get("seed") != checkpoint["seed"] or fit_receipt.get("training") != TRAINING or fit_receipt.get("epochs_completed") != TRAINING["epochs"] or fit_receipt.get("evaluation_images_used") != 0 or fit_receipt.get("checkpoint_sha256") != checkpoint["sha256"]:
            raise ScienceError("FIT_ACCOUNTING", "A seed fit differs from fixed training, epoch selection or training-only provenance")
    for value in (envelope, receipt, task):
        if value.get("contract_signature") != signature(request["contract"]):
            raise ScienceError("CONTRACT_MISMATCH", "Prediction lineage does not match locked contract")
    if task.get("trusted_code") != prepared["trusted_code"] or task.get("numerical_spec_sha256") != digest(SPEC):
        raise ScienceError("TRUSTED_CODE_CHANGED", "Prediction code/spec lineage changed")
    expected_checkpoints = [{"seed": row["seed"], "path": "model-seed-" + str(row["seed"]) + ".pt", "sha256": row["sha256"]} for row in training["checkpoints"]]
    if task.get("checkpoints") != expected_checkpoints:
        raise ScienceError("CHECKPOINT_MISMATCH", "Predictor capsule does not bind every exact trained seed")
    for checkpoint in expected_checkpoints:
        capsule_model = verify_file(root, envelope["input_manifest"]).parent / checkpoint["path"]
        if not capsule_model.is_file() or file_hash(capsule_model) != checkpoint["sha256"]:
            raise ScienceError("CHECKPOINT_MISMATCH", "Predictor capsule model bytes changed")
    if envelope.get("checkpoint_set_sha256") != training["checkpoint_set_sha256"] or receipt.get("checkpoint_set_sha256") != training["checkpoint_set_sha256"]:
        raise ScienceError("CHECKPOINT_MISMATCH", "Predictions do not bind trained checkpoint")
    if receipt.get("provider_credentials_present") is not False or receipt.get("evaluation_labels_present") is not False:
        raise ScienceError("PREDICTOR_INPUT_SCHEMA", "Predictor receipt reports credentials or evaluation labels")
    if any(value.get("split") != split or value.get("recipe_ids") != recipes for value in (envelope, receipt, task)):
        raise ScienceError("UNREGISTERED_PREDICTION", "Prediction split/recipe family mismatch")
    if receipt.get("predictions_sha256") != envelope["predictions"]["sha256"] or receipt.get("input_manifest_sha256") != envelope["input_manifest"]["sha256"]:
        raise ScienceError("ARTIFACT_TAMPERED", "Prediction/capsule bytes differ from receipt")
    expected = {row["image_id"]: row for row in manifest["splits"][split]}
    if len(task.get("images", [])) != len(expected) or {row["image_id"] for row in task["images"]} != set(expected):
        raise ScienceError("PREDICTION_COVERAGE", "Predictor capsule does not cover exact split")
    for row in task["images"]:
        if set(row) - {"image_id", "image", "sha256", "pixel_sha256", "session_id", "width", "height"}:
            raise ScienceError("PREDICTOR_INPUT_SCHEMA", "Evaluation capsule has undeclared/label fields")
        if Path(row["image"]).name != row["image"] or any(row[key] != expected[row["image_id"]][key] for key in ("sha256", "pixel_sha256", "session_id", "width", "height")):
            raise ScienceError("PREDICTOR_INPUT_SCHEMA", "Evaluation image identity changed")
        image_path = verify_file(root, envelope["input_manifest"]).parent / row["image"]
        if file_hash(image_path) != row["sha256"]:
            raise ScienceError("ARTIFACT_TAMPERED", "Evaluation capsule image bytes changed")
    if split == "confirmation":
        registration = read_json(root / "final-registration.json")
        if registration.get("sha256") != digest({k: v for k, v in registration.items() if k != "sha256"}):
            raise ScienceError("REGISTRATION_TAMPERED", "Final registration digest changed")
        if recipes != registration["comparison_recipe_ids"] or envelope.get("registration_sha256") != registration["sha256"] or registration["confirmation_split_sha256"] != prepared["confirmation_split_sha256"]:
            raise ScienceError("UNREGISTERED_PREDICTION", "Final predictions differ from complete frozen family")
    required = {(image_id, recipe, seed) for image_id in expected for recipe in recipes for seed in TRAINING["seeds"]}
    seen, rows, image_records = set(), [], []
    if not isinstance(predictions, list) or len(predictions) != len(required) or receipt.get("prediction_records") != len(required):
        raise ScienceError("PREDICTION_COVERAGE", "Wrong prediction record count")
    keys = [(row.get("image_id"), row.get("recipe_id"), row.get("seed")) for row in predictions]
    if len(set(keys)) != len(keys) or set(keys) != required:
        raise ScienceError("DUPLICATE_PREDICTION", "Predictions do not cover exact unique image/recipe/seed family")
    # Labels are deliberately read only after full family accounting above.
    for row in predictions:
        key = (row.get("image_id"), row.get("recipe_id"), row.get("seed"))
        if key not in required or key in seen:
            raise ScienceError("DUPLICATE_PREDICTION", "Unexpected/duplicate image-recipe prediction")
        seen.add(key)
        source = expected[row["image_id"]]
        if row.get("source_sha256") != source["sha256"] or row.get("source_pixel_sha256") != source["pixel_sha256"]:
            raise ScienceError("COORDINATE_LINEAGE", "Prediction is not bound to the original photograph")
        transform = row.get("transform", {})
        recipe = next(r for r in RECIPES if r["id"] == row["recipe_id"])
        if transform.get("retained_width") != recipe["width"] or transform.get("canvas_width") != source["width"] or transform.get("canvas_height") != source["height"]:
            raise ScienceError("COORDINATE_LINEAGE", "Wrong retained pixels or coordinate canvas")
        if recipe["id"] in ("native_full", "native_noop") and transform.get("processed_pixel_sha256") != source["pixel_sha256"]:
            raise ScienceError("NOOP_CHANGED_PIXELS", "Native/no-op transform changed image pixels")
        calls = 9 if recipe["mode"] in ("tiles", "multiscale") else 1
        if row.get("forward_calls") != calls or not isinstance(row.get("processed_tensor_pixels"), int) or row["processed_tensor_pixels"] <= 0:
            raise ScienceError("RESOURCE_RECEIPT", "Incorrect forward-call/tensor pixel accounting")
        audit_pixels(verify_file(root, source["image"]), recipe, row)
        audit_inference_lineage(recipe, row, source["width"], source["height"], TRAINING["min_size"], SPEC["multiscale"]["min_sizes"])
        if not isinstance(row.get("inference_seconds"), (int, float)) or not math.isfinite(row["inference_seconds"]) or row["inference_seconds"] < 0:
            raise ScienceError("RESOURCE_RECEIPT", "Missing measured finite inference time")
        labels = read_json(verify_file(root, source["labels"]))
        metrics = image_metrics(labels["boxes"], row.get("boxes", []), source["width"], source["height"])
        joined = {"image_id": row["image_id"], "recipe_id": row["recipe_id"], "seed": row["seed"], "session_id": source["session_id"],
                  **metrics, **{key: row[key] for key in ("upload_bytes", "inference_seconds", "forward_calls", "processed_tensor_pixels")}}
        rows.append(joined)
        processed_artifacts = []
        for retained in row.get("processed_artifacts", []):
            name = retained["name"]
            if Path(name).name != name:
                raise ScienceError("UNSAFE_PATH", "Processed pixel artifact needs a simple retained filename")
            relative = (Path(envelope["predictions"]["path"]).parent / ("seed-" + str(row["seed"])) / "pixels" / name).as_posix()
            path = verify_file(root, {"path": relative, "sha256": retained["sha256"]})
            record = artifact(root, path, "processed_pixels", "image/png" if path.suffix == ".png" else "image/jpeg")
            record["pixel_role"] = "detector_canvas" if "-canvas.png" in name else "uploaded_image"
            processed_artifacts.append(record)
        canvas = next((a for a in processed_artifacts if a["pixel_role"] == "detector_canvas"), None)
        if canvas:
            transform = {**transform, "processed": {**canvas, "width": source["width"], "height": source["height"]}}
        illustration_id = prepared["illustration"]["image_id"] if split == "discovery" else manifest["splits"]["confirmation"][0]["image_id"]
        if row["image_id"] == illustration_id:
            image_records.append({**joined, "image": {**source["image"], "private": False}, "targets": labels["boxes"], "predictions": row["boxes"],
                                  "transform": transform, "processed_artifacts": processed_artifacts})
    # Independently verify no-op output equality when both controls were executed.
    lookup = {(row["image_id"], row["recipe_id"], row["seed"]): row for row in predictions}
    for image_id in expected:
        for seed in TRAINING["seeds"]:
            if (image_id, "native_full", seed) in lookup and (image_id, "native_noop", seed) in lookup and lookup[(image_id, "native_full", seed)]["boxes"] != lookup[(image_id, "native_noop", seed)]["boxes"]:
                raise ScienceError("NOOP_PREDICTION_DISAGREEMENT", "Pixel-identical no-op changed detector predictions")
    summaries, sessions = summarize(rows)
    phase = request["phase"]
    metrics_path = root / "metrics" / (phase + "-" + envelope["predictions"]["sha256"][:16] + ".json")
    metrics_artifact = artifact(root, immutable_json(metrics_path, {"image_metrics": rows, "session_metrics": sessions, "summaries": summaries}), "independent_box_metrics")
    observations = [{"phase": phase, "condition_id": summary["recipe_id"], "condition_label": next(r["label"] for r in RECIPES if r["id"] == summary["recipe_id"]),
                     "metric": "count_mae", "value": summary["count_mae"], "rows": summary["images"], "blocks": summary["sessions"],
                     "unit": summary["unit"], "ci_low": None, "ci_high": None, "effect": None, "candidate": None, "baseline": None,
                     "warning": "Finite public corpus; session independence and an operational acceptance threshold are not established", "artifact_sha256": metrics_artifact["sha256"]} for summary in summaries]
    result = {"verification": {"status": "verified", "oracle": "independent authored box matcher in a separate credential-free process", "prediction_records": len(seen),
                "metric_audit": {"coordinate_lineage": True, "exact_identity_coverage": True, "one_to_one_matching": True, "final_family_frozen": split == "confirmation"}},
              "observations": observations, "metrics": summaries, "session_metrics": sessions, "image_records": image_records,
              "conclusion": {"outcome": "descriptive_finite_corpus", "direction": None, "reasons": ["Operational acceptance requirement not established", "Independent collection units not established", "No paper-protocol equivalence or deployment recommendation"]},
              "artifacts": [metrics_artifact], "receipts": [], "limitations": LIMITATIONS[:]}
    if split == "confirmation":
        immutable_json(root / "final-verification.json", result)
    return result


def reverify(request):
    root, _, _ = _context(request)
    original = read_json(root / "final-verification.json")
    result = verify(request)
    if result["metrics"] != original["metrics"] or result["session_metrics"] != original["session_metrics"]:
        raise ScienceError("REVERIFICATION_DISAGREEMENT", "Independent metric replay changed")
    result["replay"] = {"kind": "no-inference independent metric re-verification", "numerical_agreement": True}
    return result


def _retained_replay_plans(root):
    if not (root / "final-verification.json").exists():
        raise ScienceError("VERIFICATION_REQUIRED", "Replay needs completed final evidence; it is not a new final test")
    originals = [("discovery", read_json(path)["prediction_manifest"]) for path in sorted((root / "discovery").glob("*.json"))]
    originals.append(("confirmation", read_json(root / "final-prediction.json")["prediction_manifest"]))
    return originals


def _retained_prediction_storage(root, path, depth=0):
    if depth > 2 or not path.resolve().is_relative_to(root):
        raise ScienceError("PREDICTION_SCHEMA", "Replay index escaped the finite evidence structure")
    value = read_json(path)
    if isinstance(value, list):
        return path.stat().st_size, path.stat().st_size
    if value.get("schema_version") == "crucible.wheat.seed-index.v1":
        actual, expanded = path.stat().st_size, path.stat().st_size
        for record in value["seed_predictions"]:
            child = inside(root, (path.parent / record["path"]).relative_to(root).as_posix())
            if file_hash(child) != record["sha256"]:
                raise ScienceError("ARTIFACT_TAMPERED", "Retained seed index changed before admission")
            size, bound = _retained_prediction_storage(root, child, depth + 1)
            actual, expanded = actual + size, expanded + bound
        return actual, expanded
    if value.get("schema_version") != "crucible.wheat.box-arrays.v1":
        raise ScienceError("PREDICTION_SCHEMA", "Unknown retained numeric storage schema")
    arrays = verify_file(path.parent, value["arrays"])
    if any(not isinstance(value.get(key), int) or value[key] < 0 for key in ("raw_count", "selected_count")):
        raise ScienceError("PREDICTION_SCHEMA", "Numeric storage counts must be nonnegative integers")
    pixels = sum(a["bytes"] for row in value["records"] for a in row.get("processed_artifacts", []))
    return path.stat().st_size + arrays.stat().st_size + pixels, path.stat().st_size + 48 * value["raw_count"] + 44 * value["selected_count"] + pixels


def replay_workspace_plan(request, metrics_only=False, assume_capsules_missing=False):
    """Read-only estimate, separate from training, extraction and the one ZIP."""
    root, prepared, manifest = _context(request)
    originals = _retained_replay_plans(root)
    training = read_json(root / "training-result.json")
    models = [verify_file(root, item) for item in training["checkpoints"]]
    sources = {row["sha256"]: row["image"] for rows in manifest["splits"].values() for row in rows}
    sources.update({item["sha256"]: item for item in training["checkpoints"]})
    task_path = verify_file(root, originals[-1][1]["input_manifest"])
    task = read_json(task_path)
    aliases = []
    entries = [(row["image"], row["sha256"]) for row in task["images"]] + [(row["path"], row["sha256"]) for row in task["checkpoints"]]
    for name, sha in entries:
        if Path(name).name != name or sha not in sources:
            raise ScienceError("PREDICTOR_INPUT_SCHEMA", "Replay capsule is not bound to canonical images/models")
        source, destination = verify_file(root, sources[sha]), task_path.parent / name
        if destination.exists() and file_hash(destination) != sha:
            raise ScienceError("ARTIFACT_TAMPERED", "Retained final capsule changed")
        if assume_capsules_missing or not destination.exists():
            aliases.append({"path": destination.relative_to(root).as_posix(), "source": source.relative_to(root).as_posix(), "bytes": source.stat().st_size, "sha256": sha})
    capsule_bytes, retained_bytes, predictions = 0, 0, 0
    if not metrics_only:
        for split, envelope in originals:
            recipes = _recipe_ids(envelope["recipe_ids"])
            capsule_bytes += sum(verify_file(root, row["image"]).stat().st_size for row in manifest["splits"][split]) + sum(path.stat().st_size for path in models)
            actual, expanded = _retained_prediction_storage(root, verify_file(root, envelope["predictions"]))
            retained_bytes += actual
            calls = sum(1 if next(r for r in RECIPES if r["id"] == recipe)["mode"] == "full" else 9 for recipe in recipes)
            cap_bound = 92 * TRAINING["box_detections_per_img"] * len(TRAINING["seeds"]) * len(manifest["splits"][split]) * calls
            predictions += max(expanded, cap_bound) + 16 * 1024**2
    metrics_bytes = 3 * (root / "final-verification.json").stat().st_size + 16 * 1024**2
    alias_bytes = sum(row["bytes"] for row in aliases)
    return {"schema_version": "crucible.wheat.replay-workspace.v1", "mode": "metrics_only" if metrics_only else "fresh_inference",
            "missing_final_capsule_aliases": aliases, "alias_full_copy_fallback_bytes": alias_bytes,
            "new_capsule_full_copy_fallback_bytes": capsule_bytes, "actual_retained_prediction_bytes": retained_bytes,
            "new_prediction_bound_bytes": predictions, "metrics_and_control_files_bytes": metrics_bytes,
            "additional_bytes": alias_bytes + capsule_bytes + predictions + metrics_bytes, "reserve_bytes": DISK_RESERVE,
            "scope": "Additional to extracted canonical evidence and retained ZIP. Full-copy fallback reserved for missing final aliases and every new capsule; hardlinks may use less. No retraining/new ZIP included."}


def admit_replay_workspace(request, metrics_only=False):
    plan = replay_workspace_plan(request, metrics_only=metrics_only)
    root = Path(request["root"]).resolve()
    ensure_free_space(root, plan["additional_bytes"], "separate offline replay workspace")
    for row in plan["missing_final_capsule_aliases"]:
        _link(verify_file(root, {"path": row["source"], "sha256": row["sha256"]}), inside(root, row["path"]))
    return plan


def rerun(request):
    root, prepared, manifest = _context(request)
    workspace = admit_replay_workspace(request)
    originals = _retained_replay_plans(root)
    comparisons, artifacts, receipts = [], [], []
    for split, retained in originals:
        replay, timing, pixels = _prediction(root, prepared, manifest, request, split, retained["recipe_ids"], "offline-replay", replay=True)
        left = _prediction_rows(root, retained)
        right = _prediction_rows(root, replay)
        if len(left) != len(right):
            raise ScienceError("RERUN_DISAGREEMENT", "Replay prediction record count changed")
        for a, b in zip(left, right):
            if (a["image_id"], a["recipe_id"], a["seed"]) != (b["image_id"], b["recipe_id"], b["seed"]) or len(a["boxes"]) != len(b["boxes"]):
                raise ScienceError("RERUN_DISAGREEMENT", "Replay identity or box count changed")
            for x, y in zip(a["boxes"], b["boxes"]):
                if abs(x["score"] - y["score"]) > SPEC["replay"]["score_atol"] or any(abs(v - w) > SPEC["replay"]["coordinate_atol"] for v, w in zip(x["box"], y["box"])):
                    raise ScienceError("RERUN_DISAGREEMENT", "Fresh inference differs beyond registered coordinate/score tolerances")
        comparisons.append({"split": split, "recipe_ids": retained["recipe_ids"], "prediction_agreement_within_tolerance": True,
                            "retained_sha256": retained["predictions"]["sha256"], "rerun_sha256": replay["predictions"]["sha256"]})
        artifacts += [replay[k] for k in ("predictions", "receipt", "input_manifest", "execution")]
        receipts += timing
    return {"replay": {"kind": "fresh actual detector inference from retained checkpoint; no retraining", "comparisons": comparisons,
                       "prediction_agreement_within_tolerance": True, "tolerances": SPEC["replay"], "workspace_admission": workspace}, "artifacts": artifacts, "receipts": receipts, "observations": []}


def export_case(request):
    root, prepared, manifest = _context(request)
    if not (root / "final-verification.json").exists():
        raise ScienceError("VERIFICATION_REQUIRED", "Portable export releases final labels only after completed registered verification")
    files = {}
    for path in sorted((root / "frozen_source" / "science").glob("*.py")):
        files["science/" + path.name] = path
    for record in prepared["dependencies"]["files"].values():
        files["case/" + record["path"]] = verify_file(root, record)
    # Explicit tree allowlist; epoch checkpoints other than selected epoch10 are
    # not required for replay, and capsules use duplicate hardlinks of images.
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root)
        if rel.parts[0] in ("export",) or any(p.startswith(".") for p in rel.parts):
            continue
        if path.name == "latest-resume.pt":
            continue
        if "input" in rel.parts and path.suffix not in (".json",):
            # The capsule references these exact bytes. Retain via ZIP aliases
            # for offline oracle checking; ZIP compression handles duplication.
            pass
        if path.suffix.lower() not in (".json", ".jsonl", ".jpg", ".jpeg", ".png", ".pt", ".py", ".npz"):
            continue
        files["case/" + rel.as_posix()] = path
    # Capsule images/models are hardlinks locally. Store each byte sequence once
    # and reconstruct only these duplicate input paths during offline replay.
    canonical = {file_hash(path): name for name, path in files.items() if "/attempts/" not in name and path.suffix != ".py"}
    aliases = {}
    for name, path in list(files.items()):
        if "/input/" in name and path.suffix != ".json" and file_hash(path) in canonical:
            aliases[name] = canonical[file_hash(path)]
            del files[name]
    replay = {"root": "case", "contract": request["contract"], "registration": request["registration"], "inference_device": request.get("inference_device", "cpu")}
    script = '''#!/usr/bin/env python3
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--verify-only',action='store_true');p.add_argument('--metrics-only',action='store_true');a=p.parse_args()
m=json.loads((root/'manifest.json').read_text())
for name,sha in m['files'].items():
 f=(root/name).resolve()
 if not f.is_relative_to(root):raise SystemExit('Unsafe path: '+name)
 if not f.is_file() and name in m.get('aliases',{}):f=(root/m['aliases'][name]).resolve()
 if not f.is_relative_to(root) or not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest()!=sha:raise SystemExit('Integrity failure: '+name)
print('All retained logical bytes verified; missing aliases checked against canonical bytes without copying.')
if a.verify_only:raise SystemExit(0)
r=json.loads((root/'replay-request.json').read_text());r['root']=str(root/'case')
sys.dont_write_bytecode=True
from science.wheat import admit_replay_workspace
from science.common import ScienceError
try:space=admit_replay_workspace(r,metrics_only=a.metrics_only)
except ScienceError as e:
 print(e.code+': '+e.message,file=sys.stderr);raise SystemExit(2)
print('Replay workspace admitted:',space['additional_bytes'],'additional bytes plus',space['reserve_bytes'],'reserve.')
q=root/'local-replay-request.json';q.write_text(json.dumps(r))
for stage in (['reverify'] if a.metrics_only else ['rerun','reverify']):
 subprocess.run([sys.executable,'-m','science.wheat_cli',stage,'--input',str(q),'--output',str(root/(stage+'-result.json'))],cwd=root,check=True)
print('Fixed evidence replay complete; this is not fresh confirmation or retraining.')
'''
    receipt_locations = ", ".join("case/" + row["path"] for row in read_json(root / "training-result.json")["training_receipts"])
    extras = {"replay-request.json": canonical_bytes(replay) + b"\n", "reproduce.py": script.encode()}
    for name, record in prepared["dependencies"]["files"].items():
        extras[name] = verify_file(root, record).read_bytes()
    extras["README-REPRODUCE.md"] = ("# Wheat finite-corpus evidence\n\nNew source-informed experiment, not WILDS reproduction. The exact checked-in Python3.13 requirements and full transitive hash lock were frozen at preparation: install with `python3.13 -m pip install --require-hashes -r requirements-wheat.lock` (or use a prepared wheelhouse). The supplemental requirements-wheat-linux-cuda.lock provides a separately resolved CPython3.13/Linux x86_64 CUDA installation recipe. Linux/CUDA installation and hardware execution remain unqualified until actual host checks and receipts; including this lock is not execution evidence. Locks are installation recipes; executed environments are recorded separately in " + receipt_locations + ".\n\nRun `python reproduce.py --verify-only` for read-only hash checking; missing capsule aliases are verified against canonical bytes without materializing the historical training copies. `--metrics-only` recomputes independent metrics without importing Torch. The default performs fresh fixed-checkpoint inference and re-verifies metrics; it is neither retraining nor fresh confirmation. After dependency installation no network, model service or provider key is required.\n\nThe training/export space budget covers one ZIP only. Extraction and replay require separate space: see manifest.json workspace.canonical_extraction_bytes_upper_bound plus workspace.fresh_inference.additional_bytes (or metrics_only.additional_bytes), plus its reserve. These are additional to the ZIP and installed dependencies. Admission checks actual canonical image/model sizes, retained predictions and schedules before creating any capsule alias, request or replay attempt. Full-copy fallback is reserved for every missing required final alias and new capsule, even if hardlinks succeed. Only the final capsule required by the oracle is reconstructed; other historical aliases remain logical references.\n\nOriginal attribution/rights and unresolved source differences remain in case/prepared.json and case/source/asset-manifest.json.\n").encode()
    hashes = {name: file_hash(path) for name, path in files.items()}
    hashes.update({name: hashes[target] for name, target in aliases.items()})
    hashes.update({name: __import__("hashlib").sha256(content).hexdigest() for name, content in extras.items()})
    extraction_bound = math.ceil((sum(path.stat().st_size for path in files.values()) + sum(len(content) for content in extras.values())) * 1.05) + 16 * 1024**2
    workspace = {"canonical_extraction_bytes_upper_bound": extraction_bound,
                 "fresh_inference": replay_workspace_plan(request, assume_capsules_missing=True),
                 "metrics_only": replay_workspace_plan(request, metrics_only=True, assume_capsules_missing=True),
                 "scope": "Separate from the one-ZIP budget. Before extraction allow canonical expansion plus chosen replay additional bytes/reserve, beyond the ZIP and installed dependencies."}
    export_manifest = {"schema_version": SCHEMA, "files": hashes, "aliases": aliases, "workspace": workspace, "contract_signature": signature(request["contract"]), "corpus_sha256": prepared["corpus_sha256"],
                       "holdout_release": "After the complete once-registered family was predicted and independently verified; replay only"}
    output = root / "export" / ("wheat-" + digest(export_manifest)[:16] + ".zip")
    output.parent.mkdir(exist_ok=True)
    receipt_path = output.with_suffix(".receipt.json")
    if output.exists() and receipt_path.exists():
        receipt = read_json(receipt_path)
        if receipt["sha256"] != file_hash(output) or receipt["manifest_sha256"] != digest(export_manifest):
            raise ScienceError("ARTIFACT_TAMPERED", "Retained portable ZIP changed")
        return {"artifacts": [artifact(root, output, "portable_evidence", "application/zip")], "manifest": export_manifest, "export_sha256": receipt["sha256"], "sealed_labels_released": True}
    upper_bound = math.ceil((sum(path.stat().st_size for path in files.values()) + sum(len(content) for content in extras.values())) * 1.05) + 16 * 1024**2
    ensure_free_space(root, upper_bound, "portable ZIP publication (single streamed copy)")
    temporary = output.with_suffix(".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as bundle:
        for name, path in sorted(files.items()):
            bundle.write(path, name, compress_type=zipfile.ZIP_STORED if path.suffix in (".png", ".npz") else zipfile.ZIP_DEFLATED)
        for name, content in sorted(extras.items()):
            bundle.writestr(name, content)
        bundle.writestr("manifest.json", canonical_bytes(export_manifest) + b"\n")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    if output.exists():
        temporary.unlink()
    else:
        os.replace(temporary, output)
    immutable_json(receipt_path, {"sha256": file_hash(output), "manifest_sha256": digest(export_manifest), "bytes": output.stat().st_size})
    return {"artifacts": [artifact(root, output, "portable_evidence", "application/zip")], "manifest": export_manifest,
            "export_sha256": file_hash(output), "sealed_labels_released": True}
