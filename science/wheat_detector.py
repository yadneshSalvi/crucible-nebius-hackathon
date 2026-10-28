"""Only authored TorchVision/SAHI training and inference, with no eval labels.

Runs in a credential-free process. Checkpoint loading uses weights_only=True;
neither supplied model classes nor arbitrary code is executed.
"""

import argparse
import hashlib
import io
import math
import os
import platform
import resource
import time
from pathlib import Path

from .common import ScienceError, atomic_result, canonical_bytes, digest, file_hash, immutable_bytes, immutable_json, read_json, utc_now
from .wheat import RECIPES, SPEC, TRAINING, training_order


def _libraries():
    try:
        import numpy as np
        import PIL
        import sahi
        import torch
        import torchvision
    except ImportError as exc:
        raise ScienceError("WHEAT_DEPENDENCY", "Install the pinned wheat dependencies before numerical execution", True) from exc
    torch.set_num_threads(1)
    return torch, torchvision, np, {"python": platform.python_version(), "torch": torch.__version__, "torchvision": torchvision.__version__,
        "numpy": np.__version__, "pillow": PIL.__version__, "sahi": sahi.__version__, "platform": platform.platform(), "machine": platform.machine()}


def _model(torchvision, initialized=False):
    from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
    if TRAINING["model"] == "fasterrcnn_resnet50_fpn":
        from torchvision.models.detection.backbone_utils import resnet_fpn_backbone
        from torchvision.ops.misc import FrozenBatchNorm2d
        backbone = resnet_fpn_backbone(backbone_name="resnet50", weights=None, norm_layer=FrozenBatchNorm2d, trainable_layers=TRAINING["trainable_backbone_layers"])
        model = torchvision.models.detection.FasterRCNN(backbone, num_classes=91, min_size=TRAINING["min_size"], max_size=TRAINING["max_size"],
            box_detections_per_img=TRAINING["box_detections_per_img"], box_nms_thresh=TRAINING["box_nms_thresh"], box_score_thresh=TRAINING["box_score_thresh"])
    else:
        raise ScienceError("UNSUPPORTED_DETECTOR", "Only the frozen authored ResNet50-FPN detector executes")
    if not initialized:
        features = model.roi_heads.box_predictor.cls_score.in_features
        model.roi_heads.box_predictor = FastRCNNPredictor(features, 2)
    return model


def _device(torch, name):
    if name not in ("cpu", "mps") or (name == "mps" and not torch.backends.mps.is_available()):
        raise ScienceError("WHEAT_HARDWARE", "Frozen requested CPU/MPS device is unavailable; no silent device replacement", True)
    return torch.device(name)


def _sync(torch, device):
    if device.type == "mps":
        torch.mps.synchronize()


def _tensor(image, torch, np, device):
    return torch.from_numpy(np.array(image, dtype=np.float32).transpose(2, 0, 1).copy() / 255.0).to(device)


def _receipt(started_at, started, cpu_start, device, environment):
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {"started_at": started_at, "completed_at": utc_now(), "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu_start,
            "peak_rss_bytes": int(usage.ru_maxrss if platform.system() == "Darwin" else usage.ru_maxrss * 1024),
            "device": str(device), "environment": environment, "threads": 1,
            "mps_fallback_enabled": os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "1",
            "mps_fallback_caveat": "Fallback is enabled for unsupported operators; requested device is recorded, not a claim that every operator ran on GPU",
            "provider_credentials_present": any("API_KEY" in key or "TOKEN" in key for key in os.environ), "pid": os.getpid()}


def _save_torch(torch, path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    from .wheat import ensure_free_space
    ensure_free_space(path.parent, 576 * 1024**2, "atomic model/resume checkpoint publication")
    temporary = path.with_name("." + path.name + ".tmp")
    torch.save(value, temporary)
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def train_model(task_path, output):
    from PIL import Image
    torch, torchvision, np, environment = _libraries()
    task = read_json(task_path)
    plan = task["plan"]
    if plan["training"] != TRAINING or plan["numerical_spec_sha256"] != digest(SPEC):
        raise ScienceError("TRAINING_PLAN_CHANGED", "Training task differs from trusted finite recipe")
    initial = Path(task["initialization"])
    if file_hash(initial) != plan["initialization"]["sha256"]:
        raise ScienceError("INITIALIZATION_MISMATCH", "Initialization bytes changed")
    torch.manual_seed(plan["seed"])
    if torch.backends.mps.is_available():
        torch.mps.manual_seed(plan["seed"])
    # Deterministic algorithms can be unavailable on MPS. Their availability is
    # not fabricated: fixed seeds and actual inference agreement are separate.
    device = _device(torch, plan["device"])
    started_at, started, cpu_start = utc_now(), time.perf_counter(), time.process_time()
    model = _model(torchvision, initialized=True)
    initial_state = torch.load(initial, map_location="cpu", weights_only=True)
    if "ResNet50_Weights" in TRAINING["initialization"]:
        backbone = {key: value for key, value in initial_state.items() if not key.startswith("fc.")}
        result = model.backbone.body.load_state_dict(backbone, strict=True)
    else:
        model.load_state_dict(initial_state, strict=True)
    from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
    model.roi_heads.box_predictor = FastRCNNPredictor(model.roi_heads.box_predictor.cls_score.in_features, 2)
    # Explicit freezing is needed because TorchVision uses all layers trainable
    # when weights=None even if a trainable_backbone_layers argument is passed.
    if TRAINING["model"] == "fasterrcnn_resnet50_fpn":
        trainable = ["layer4", "layer3", "layer2", "layer1", "conv1"][:TRAINING["trainable_backbone_layers"]]
        for name, parameter in model.backbone.body.named_parameters():
            parameter.requires_grad_(any(name.startswith(prefix) for prefix in trainable))
    model.to(device)
    optimizer = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=TRAINING["learning_rate"],
                                betas=tuple(TRAINING["betas"]), eps=TRAINING["epsilon"], weight_decay=TRAINING["weight_decay"])
    epoch_dir = Path(task["resume_dir"]).resolve()
    epoch_dir.mkdir(parents=True, exist_ok=True)
    latest = epoch_dir / "latest-resume.pt"
    start_epoch, history = 0, []
    if latest.exists():
        resume = torch.load(latest, map_location="cpu", weights_only=True)
        if resume["plan_sha256"] != digest(plan):
            raise ScienceError("TRAINING_PLAN_CHANGED", "Resumable checkpoint belongs to another frozen training plan")
        model.load_state_dict(resume["model"])
        optimizer.load_state_dict(resume["optimizer"])
        for state in optimizer.state.values():
            for key, value in state.items():
                if torch.is_tensor(value):
                    state[key] = value.to(device)
        torch.set_rng_state(resume["cpu_rng"])
        if device.type == "mps" and resume.get("mps_rng") is not None:
            torch.mps.set_rng_state(resume["mps_rng"])
        start_epoch, history = resume["epoch"], resume["history"]
    rows = task["training"]
    if not rows or [row["image_id"] for row in rows] != sorted(row["image_id"] for row in rows):
        raise ScienceError("TRAINING_PLAN_CHANGED", "Training rows must be nonempty and fixed image_id order")
    for row in rows:
        if set(row) != {"image_id", "image", "sha256", "boxes"} or Path(row["image"]).name != row["image"] or file_hash(row["image"]) != row["sha256"]:
            raise ScienceError("TRAINING_INPUT_SCHEMA", "Invalid training capsule or image hash")
    for epoch in range(start_epoch + 1, TRAINING["epochs"] + 1):
        epoch_started = time.perf_counter()
        model.train()
        losses, component_sums, optimizer_steps = [], {}, 0
        optimizer.zero_grad(set_to_none=True)
        by_id = {row["image_id"]: row for row in rows}
        order = training_order(list(by_id), plan["seed"], epoch)
        epoch_rows = [by_id[image_id] for image_id in order]
        for index in range(0, len(epoch_rows), TRAINING["batch_size"]):
            batch = epoch_rows[index:index + TRAINING["batch_size"]]
            images, targets = [], []
            for row in batch:
                with Image.open(row["image"]) as source:
                    image = source.convert("RGB")
                boxes = torch.tensor(row["boxes"], dtype=torch.float32, device=device).reshape(-1, 4)
                targets.append({"boxes": boxes, "labels": torch.ones(len(boxes), dtype=torch.int64, device=device)})
                images.append(_tensor(image, torch, np, device))
            optimizer.zero_grad(set_to_none=True)
            loss_dict = model(images, targets)
            loss = sum(loss_dict.values())
            if not bool(torch.isfinite(loss).detach().cpu()):
                raise ScienceError("NONFINITE_TRAINING", "Frozen training produced nonfinite loss; no checkpoint selected")
            loss.backward()
            optimizer.step()
            optimizer_steps += 1
            losses.append(float(loss.detach().cpu()))
            for key, value in loss_dict.items():
                component_sums[key] = component_sums.get(key, 0.0) + float(value.detach().cpu())
        _sync(torch, device)
        record = {"epoch": epoch, "images": len(rows), "optimizer_steps": optimizer_steps, "mean_training_loss": sum(losses) / len(losses),
                  "order_sha256": digest(order), "order_seed": plan["seed"] * 100000 + epoch,
                  "component_means": {key: value / len(losses) for key, value in component_sums.items()}, "wall_seconds": time.perf_counter() - epoch_started,
                  "selection": "Epoch10 is fixed before outcomes; training loss is diagnostic only"}
        history.append(record)
        cpu_state = {key: value.detach().cpu() for key, value in model.state_dict().items()}
        _save_torch(torch, latest, {"model": cpu_state, "optimizer": optimizer.state_dict(), "epoch": epoch, "history": history,
                                  "plan_sha256": digest(plan), "cpu_rng": torch.get_rng_state(), "mps_rng": torch.mps.get_rng_state() if device.type == "mps" else None})
        immutable_json(epoch_dir / ("epoch-%02d.json" % epoch), {**record, "resumable_checkpoint_sha256_at_epoch": file_hash(latest),
                      "checkpoint_retention": "Latest resumable checkpoint replaced each completed epoch; final epoch model retained immutably. Past epoch diagnostics/hashes retained; past checkpoint bytes not retained."})
        print(canonical_bytes({"stage": "epoch_complete", **record}).decode(), flush=True)
    final = epoch_dir / "epoch-10.pt"
    if not final.exists():
        _save_torch(torch, final, {key: value.detach().cpu() for key, value in model.state_dict().items()})
    else:
        retained = torch.load(final, map_location="cpu", weights_only=True)
        if set(retained) != set(model.state_dict()) or any(not torch.equal(retained[key], value.detach().cpu()) for key, value in model.state_dict().items()):
            raise ScienceError("CHECKPOINT_MISMATCH", "Existing final model differs from resumed fixed epoch10 state")
    receipt = {**_receipt(started_at, started, cpu_start, device, environment), "schema_version": "crucible.wheat.training.v1",
               "training": TRAINING, "plan_sha256": digest(plan), "contract_signature": plan["contract_signature"],
               "initialization_sha256": plan["initialization"]["sha256"], "training_split_sha256": plan["training_split_sha256"],
               "training_images": len(rows), "evaluation_images_used": 0, "epochs_completed": TRAINING["epochs"], "resumed_after_epoch": start_epoch,
               "training_image_ids_sha256": digest([row["image_id"] for row in rows]), "epoch_history": history,
               "checkpoint_sha256": file_hash(final), "seed": plan["seed"], "tuning_trials": 0,
               "selection": TRAINING["selection"], "total_epoch_wall_seconds": sum(row["wall_seconds"] for row in history),
               "mps_allocated_bytes_at_completion": torch.mps.current_allocated_memory() if device.type == "mps" else None,
               "determinism": "Fixed seeds and recipe; no promise of bitwise-identical MPS retraining. Replay checks actual checkpoint inference within frozen tolerances."}
    output.mkdir(parents=True, exist_ok=True)
    atomic_result(output / "result.json", {"checkpoint": {"sha256": file_hash(final), "bytes": final.stat().st_size}, "receipt": receipt})


def transformed(image_path, recipe):
    """Returns exact pixels, transmitted bytes, and reconstructable transform."""
    from PIL import Image
    source_bytes = Path(image_path).read_bytes()
    with Image.open(io.BytesIO(source_bytes)) as source:
        image = source.convert("RGB")
    width, height = image.size
    retained = image.copy() if recipe["width"] == width else image.resize((recipe["width"], round(height * recipe["width"] / width)), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    retained.save(buffer, format="PNG", compress_level=6, optimize=False)
    uploaded = buffer.getvalue()
    with Image.open(io.BytesIO(uploaded)) as decoded:
        canvas = decoded.convert("RGB")
        if canvas.size != (width, height):
            canvas = canvas.resize((width, height), Image.Resampling.LANCZOS)
    encoding = "Lossless PNG compress_level6 optimizeFalse"
    return canvas, uploaded, {"retained_width": recipe["width"], "retained_height": round(height * recipe["width"] / width),
        "canvas_width": width, "canvas_height": height, "resampler": "Pillow LANCZOS", "encoding": encoding,
        "upload_sha256": hashlib.sha256(uploaded).hexdigest(), "processed_pixel_sha256": hashlib.sha256(canvas.tobytes()).hexdigest(),
        "coordinates": "continuous xyxy on original canvas; SAHI offsets shifted to original canvas", "restore_common_canvas": True}


def _predict_one(task_path, output, task=None):
    torch, torchvision, np, environment = _libraries()
    task = task or read_json(task_path)
    if task["numerical_spec_sha256"] != digest(SPEC):
        raise ScienceError("NUMERICAL_SPEC_CHANGED", "Prediction task differs from frozen specification")
    if file_hash(task["checkpoint"]["path"]) != task["checkpoint"]["sha256"]:
        raise ScienceError("CHECKPOINT_MISMATCH", "Prediction checkpoint bytes changed")
    for row in task["images"]:
        if set(row) != {"image_id", "image", "sha256", "pixel_sha256", "session_id", "width", "height"} or Path(row["image"]).name != row["image"]:
            raise ScienceError("PREDICTOR_INPUT_SCHEMA", "Evaluation capsule must contain only image features and identities")
        if file_hash(row["image"]) != row["sha256"]:
            raise ScienceError("ARTIFACT_TAMPERED", "Evaluation image changed")
    device = _device(torch, task["device"])
    started_at, started, cpu_start = utc_now(), time.perf_counter(), time.process_time()
    torch.manual_seed(task["seed"])
    model = _model(torchvision)
    model.load_state_dict(torch.load(task["checkpoint"]["path"], map_location="cpu", weights_only=True), strict=True)
    model.to(device).eval()
    from sahi.models.torchvision import TorchVisionDetectionModel
    from sahi.predict import get_sliced_prediction
    from sahi.postprocess.combine import NMSPostprocess
    from sahi.prediction import ObjectPrediction
    from sahi.slicing import get_slice_bboxes
    wrapper = TorchVisionDetectionModel(model=model, device=str(device), confidence_threshold=TRAINING["inference_score_threshold"], category_mapping={"1": "wheat_head"}, load_at_init=False)
    wrapper.set_model(model)
    # All forward calls pass through these hooks, including library tiling.
    observed = {"calls": 0, "pixels": 0, "shapes": [], "outputs": []}
    def transformed_hook(module, inputs, outputs):
        tensor = outputs[0].tensors
        observed["pixels"] += int(tensor.shape[0] * tensor.shape[2] * tensor.shape[3])
        observed["shapes"].append(list(tensor.shape))
    def model_hook(module, inputs, outputs):
        observed["calls"] += 1
        observed["outputs"].append([{ "box": [float(v) for v in box], "score": float(score)} for box, score, label in
            zip(outputs[0]["boxes"].detach().cpu().tolist(), outputs[0]["scores"].detach().cpu().tolist(), outputs[0]["labels"].detach().cpu().tolist())
            if label == 1 and score > TRAINING["inference_score_threshold"]])
    model.transform.register_forward_hook(transformed_hook)
    model.register_forward_hook(model_hook)
    output.mkdir(parents=True, exist_ok=True)
    (output / "pixels").mkdir(exist_ok=True)
    from .wheat_storage import PredictionWriter
    writer = PredictionWriter()
    total_calls, total_pixels, record_count = 0, 0, 0
    with torch.inference_mode():
        for row in task["images"]:
            for recipe_id in task["recipe_ids"]:
                recipe = next(r for r in RECIPES if r["id"] == recipe_id)
                canvas, uploaded, transform = transformed(row["image"], recipe)
                for key in ("calls", "pixels"):
                    observed[key] = 0
                observed["shapes"], observed["outputs"] = [], []
                model.transform.min_size, model.transform.max_size = (TRAINING["min_size"],), TRAINING["max_size"]
                _sync(torch, device)
                before = time.perf_counter()
                tile_bboxes = None
                if recipe["mode"] == "tiles":
                    result = get_sliced_prediction(np.asarray(canvas), wrapper, slice_height=512, slice_width=512,
                        overlap_height_ratio=0.2, overlap_width_ratio=0.2, perform_standard_pred=False,
                        postprocess_type="NMS", postprocess_match_metric="IOU", postprocess_match_threshold=0.5,
                        postprocess_class_agnostic=False, verbose=0, auto_slice_resolution=False, progress_bar=False, batch_size=1,
                        force_postprocess_type=True)
                    boxes = [{"box": list(map(float, p.bbox.to_xyxy())), "score": float(p.score.value)} for p in result.object_prediction_list]
                    tile_bboxes = get_slice_bboxes(canvas.height, canvas.width, slice_height=512, slice_width=512, overlap_height_ratio=0.2, overlap_width_ratio=0.2, auto_slice_resolution=False)
                elif recipe["mode"] == "multiscale":
                    objects = []
                    for scale in SPEC["multiscale"]["min_sizes"]:
                        model.transform.min_size, model.transform.max_size = (scale,), SPEC["multiscale"]["max_size"]
                        result = model([_tensor(canvas, torch, np, device)])[0]
                        for box, score, label in zip(result["boxes"].cpu().tolist(), result["scores"].cpu().tolist(), result["labels"].cpu().tolist()):
                            if label == 1 and score > TRAINING["inference_score_threshold"]:
                                objects.append(ObjectPrediction(bbox=box, score=score, category_id=1, category_name="wheat_head", full_shape=[canvas.height, canvas.width]))
                    merged = NMSPostprocess(match_threshold=0.5, match_metric="IOU", class_agnostic=False)(objects) if objects else []
                    boxes = [{"box": list(map(float, p.bbox.to_xyxy())), "score": float(p.score.value)} for p in merged]
                else:
                    result = model([_tensor(canvas, torch, np, device)])[0]
                    boxes = [{"box": list(map(float, box)), "score": float(score)} for box, score, label in
                        zip(result["boxes"].cpu().tolist(), result["scores"].cpu().tolist(), result["labels"].cpu().tolist()) if label == 1 and score > TRAINING["inference_score_threshold"]]
                _sync(torch, device)
                elapsed = time.perf_counter() - before
                boxes.sort(key=lambda p: (-p["score"], *p["box"]))
                raw = []
                for call, members in enumerate(observed["outputs"]):
                    offset = tile_bboxes[call][:2] if tile_bboxes is not None else [0, 0]
                    for item in members:
                        box = item["box"]
                        raw.append({"box": [box[0] + offset[0], box[1] + offset[1], box[2] + offset[0], box[3] + offset[1]], "score": item["score"], "call": call})
                pixel_artifacts = []
                if row["image_id"] == task.get("illustration_image_id"):
                    suffix = ".png"
                    upload_path = immutable_bytes(output / "pixels" / (row["image_id"] + "-" + recipe_id + "-upload" + suffix), uploaded)
                    buffer = io.BytesIO()
                    canvas.save(buffer, format="PNG", compress_level=3)
                    canvas_path = immutable_bytes(output / "pixels" / (row["image_id"] + "-" + recipe_id + "-canvas.png"), buffer.getvalue())
                    pixel_artifacts = [{"name": p.name, "sha256": file_hash(p), "bytes": p.stat().st_size} for p in (canvas_path, upload_path)]
                writer.add({"image_id": row["image_id"], "session_id": row["session_id"], "recipe_id": recipe_id, "seed": task["seed"],
                    "source_sha256": row["sha256"], "source_pixel_sha256": row["pixel_sha256"], "transform": transform,
                    "boxes": boxes, "raw_predictions": raw, "tile_bboxes": tile_bboxes, "upload_bytes": len(uploaded),
                    "inference_seconds": elapsed, "forward_calls": observed["calls"], "processed_tensor_pixels": observed["pixels"],
                    "processed_tensor_shapes": observed["shapes"], "processed_artifacts": pixel_artifacts,
                    "merging": "SAHI NMS IOU0.5" if recipe["mode"] != "full" else "TorchVision detector NMS0.5", "device": str(device)})
                total_calls += observed["calls"]
                total_pixels += observed["pixels"]
                record_count += 1
                print(canonical_bytes({"stage": "prediction_complete", "image_id": row["image_id"], "recipe_id": recipe_id,
                                      "forward_calls": observed["calls"], "wall_seconds": elapsed}).decode(), flush=True)
    prediction_path = writer.publish(output)
    receipt = {**_receipt(started_at, started, cpu_start, device, environment), "schema_version": "crucible.wheat.prediction.v1",
               "evaluation_labels_present": False, "seed": task["seed"], "contract_signature": task["contract_signature"], "split": task["split"], "recipe_ids": task["recipe_ids"],
               "numerical_spec_sha256": digest(SPEC), "checkpoint_sha256": task["checkpoint"]["sha256"], "corpus_sha256": task["corpus_sha256"],
               "input_manifest_sha256": file_hash(task_path), "predictions_sha256": file_hash(prediction_path), "prediction_records": record_count,
               "evaluation_images": len(task["images"]), "forward_calls": total_calls, "processed_tensor_pixels": total_pixels, "fit_count": 0}
    immutable_json(output / "receipt.json", receipt)
    atomic_result(output / "result.json", {"receipt": receipt})


def predict_images(task_path, output):
    task = read_json(task_path)
    if [item["seed"] for item in task["checkpoints"]] != TRAINING["seeds"]:
        raise ScienceError("CHECKPOINT_MISMATCH", "Every fixed seed checkpoint must be predicted")
    started_at, started, cpu_start = utc_now(), time.perf_counter(), time.process_time()
    seed_predictions, receipts = [], []
    for checkpoint in task["checkpoints"]:
        seed = checkpoint["seed"]
        seed_output = output / ("seed-" + str(seed))
        seed_task = {**task, "checkpoint": checkpoint, "seed": seed,
                     "illustration_image_id": task.get("illustration_image_id") if seed == TRAINING["seeds"][0] else None}
        _predict_one(task_path, seed_output, seed_task)
        seed_predictions.append({"seed": seed, "path": "seed-" + str(seed) + "/predictions.json", "sha256": file_hash(seed_output / "predictions.json")})
        receipts.append(read_json(seed_output / "receipt.json"))
    predictions = immutable_json(output / "predictions.json", {"schema_version": "crucible.wheat.seed-index.v1", "seed_predictions": seed_predictions})
    receipt = {**receipts[0], "started_at": started_at, "completed_at": utc_now(), "wall_seconds": time.perf_counter() - started,
               "cpu_seconds": time.process_time() - cpu_start, "seed_receipts": receipts, "seeds": TRAINING["seeds"],
               "checkpoint_set_sha256": task["checkpoint_set_sha256"], "prediction_records": sum(r["prediction_records"] for r in receipts), "predictions_sha256": file_hash(predictions),
               "forward_calls": sum(r["forward_calls"] for r in receipts), "processed_tensor_pixels": sum(r["processed_tensor_pixels"] for r in receipts)}
    immutable_json(output / "receipt.json", receipt)
    atomic_result(output / "result.json", {"receipt": receipt})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    try:
        task = read_json(args.manifest)
        if task["stage"] == "train":
            train_model(args.manifest, output)
        elif task["stage"] == "predict":
            predict_images(args.manifest, output)
        else:
            raise ScienceError("INVALID_STAGE", "Only authored train/predict tasks execute")
    except ScienceError as exc:
        atomic_result(output / "result.json", exc.as_dict())
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
