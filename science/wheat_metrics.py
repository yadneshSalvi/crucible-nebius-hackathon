"""Independent box oracle. This module never imports the detector or torch.

Continuous xyxy coordinates, no inclusive '+1'. Greedy score-ordered one-to-one
matching at IoU >= .5 is an authored application metric, not WILDS accuracy.
"""

import math
import statistics
import hashlib
import io
from collections import defaultdict

from .common import ScienceError


def checked_box(box, width, height):
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise ScienceError("BOX_SCHEMA", "A box must have four continuous xyxy coordinates")
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in box):
        raise ScienceError("BOX_SCHEMA", "Box coordinates must be finite numbers")
    x1, y1, x2, y2 = map(float, box)
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ScienceError("BOX_BOUNDS", "Box is empty or outside the original image canvas")
    return [x1, y1, x2, y2]


def iou(left, right):
    intersection = max(0.0, min(left[2], right[2]) - max(left[0], right[0])) * max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    union = (left[2] - left[0]) * (left[3] - left[1]) + (right[2] - right[0]) * (right[3] - right[1]) - intersection
    return intersection / union if union else 0.0


def audit_pixels(path, recipe, row):
    """Independently reconstruct pixels without importing the detector."""
    from PIL import Image
    raw = path.read_bytes()
    with Image.open(io.BytesIO(raw)) as opened:
        source = opened.convert("RGB")
    small = source.copy() if recipe["width"] == source.width else source.resize((recipe["width"], round(source.height * recipe["width"] / source.width)), Image.Resampling.LANCZOS)
    stream = io.BytesIO()
    small.save(stream, format="PNG", compress_level=6, optimize=False)
    upload = stream.getvalue()
    with Image.open(io.BytesIO(upload)) as decoded:
        processed = decoded.convert("RGB")
        if processed.size != source.size:
            processed = processed.resize(source.size, Image.Resampling.LANCZOS)
    declared = row["transform"]
    if len(upload) != row.get("upload_bytes") or hashlib.sha256(upload).hexdigest() != declared.get("upload_sha256") or hashlib.sha256(processed.tobytes()).hexdigest() != declared.get("processed_pixel_sha256"):
        raise ScienceError("TRANSFORM_LINEAGE", "Independent pixel reconstruction disagrees with predictor input declaration")


def audit_inference_lineage(recipe, row, width, height, min_size, scales):
    """Check offsets, tensor padding, original coordinates and NMS witnesses."""
    if recipe["mode"] == "tiles":
        starts = [0, 409, 512]
        expected_tiles = [[x, y, x + 512, y + 512] for y in starts for x in starts]
        if row.get("tile_bboxes") != expected_tiles:
            raise ScienceError("COORDINATE_LINEAGE", "SAHI grid differs from fixed 512/0.2 recipe")
        sizes = [min_size] * 9
    elif recipe["mode"] == "multiscale":
        expected_tiles, sizes = None, scales
    else:
        expected_tiles, sizes = None, [min_size]
    shapes = [[1, 3, math.ceil(size / 32) * 32, math.ceil(size / 32) * 32] for size in sizes]
    if row.get("processed_tensor_shapes") != shapes or row.get("processed_tensor_pixels") != sum(s[0] * s[2] * s[3] for s in shapes):
        raise ScienceError("RESOURCE_RECEIPT", "Tensor shapes/pixels disagree with frozen inference sizes")
    raw = row.get("raw_predictions")
    if not isinstance(raw, list):
        raise ScienceError("COORDINATE_LINEAGE", "Raw forward outputs required for coordinate/merge audit")
    for prediction in raw:
        box = checked_box(prediction.get("box"), width, height)
        call, score = prediction.get("call"), prediction.get("score")
        if not isinstance(call, int) or not 0 <= call < len(sizes) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0.5 < score <= 1:
            raise ScienceError("COORDINATE_LINEAGE", "Raw prediction has invalid call identity/score")
        if expected_tiles is not None:
            tile = expected_tiles[call]
            if box[0] < tile[0] or box[1] < tile[1] or box[2] > tile[2] or box[3] > tile[3]:
                raise ScienceError("COORDINATE_LINEAGE", "Shifted raw prediction escapes its source tile")
    final = row.get("boxes", [])
    def same(a, b):
        return abs(a["score"] - b["score"]) <= 1e-6 and all(abs(x - y) <= 1e-4 for x, y in zip(a["box"], b["box"]))
    if any(not any(same(p, q) for q in raw) for p in final):
        raise ScienceError("COORDINATE_LINEAGE", "Merged box is not an actual shifted forward output")
    if recipe["mode"] == "full":
        if len(final) != len(raw):
            raise ScienceError("MERGE_LINEAGE", "Full-image boxes differ from retained forward output")
    else:
        if any(iou(p["box"], q["box"]) > 0.500001 for i, p in enumerate(final) for q in final[i + 1:]):
            raise ScienceError("MERGE_LINEAGE", "NMS retained overlapping predictions beyond threshold")
        if any(not any(same(p, q) or (q["score"] + 1e-6 >= p["score"] and iou(p["box"], q["box"]) > 0.499999) for q in final) for p in raw):
            raise ScienceError("MERGE_LINEAGE", "Lost raw prediction lacks higher-score NMS witness")


def image_metrics(targets, predictions, width, height, threshold=0.5):
    """An unmatched prediction overlapping an already matched target is duplicate.

    Empty/empty has detection accuracy 1, recall/precision undefined. Empty
    targets with any predictions has accuracy 0. All images enter count metrics.
    Ties use original prediction index, then target index, deterministically.
    """
    truth = [checked_box(b, width, height) for b in targets]
    boxes = []
    for index, prediction in enumerate(predictions):
        score = prediction.get("score")
        if isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score) or not 0.5 <= score <= 1:
            raise ScienceError("PREDICTION_SCHEMA", "Retained prediction scores must be finite and >= 0.5")
        boxes.append((index, checked_box(prediction.get("box"), width, height), score))
    matched, matches, false_positive, duplicate = set(), [], [], []
    for index, box, score in sorted(boxes, key=lambda item: (-item[2], item[0])):
        available = [(iou(box, target), target_index) for target_index, target in enumerate(truth) if target_index not in matched]
        best = max(available, default=(0.0, -1), key=lambda item: (item[0], -item[1]))
        if best[0] >= threshold:
            matched.add(best[1])
            matches.append({"prediction_index": index, "target_index": best[1], "iou": best[0]})
        else:
            false_positive.append(index)
            if any(iou(box, truth[target_index]) >= threshold for target_index in matched):
                duplicate.append(index)
    misses = [index for index in range(len(truth)) if index not in matched]
    tp, fp, fn = len(matches), len(false_positive), len(misses)
    bias = len(boxes) - len(truth)
    return {"target_count": len(truth), "prediction_count": len(boxes), "tp": tp, "fp": fp, "fn": fn,
            "absolute_count_error": abs(bias), "signed_count_bias": bias,
            "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None,
            "detection_accuracy_iou50": tp / (tp + fp + fn) if tp + fp + fn else 1.0,
            "mean_matched_iou": statistics.fmean(m["iou"] for m in matches) if matches else None,
            "duplicate_count": len(duplicate), "matches": matches, "missed_target_indices": misses,
            "false_positive_indices": false_positive, "duplicate_prediction_indices": duplicate}


def summarize(rows):
    """Equal-session means of image metrics; no sampling CI or p-value."""
    by_image = defaultdict(list)
    for row in rows:
        by_image[(row["recipe_id"], row["session_id"], row["image_id"])].append(row)
    fields = ["absolute_count_error", "signed_count_bias", "precision", "recall", "detection_accuracy_iou50", "mean_matched_iou", "duplicate_count"]
    def means(members):
        return {field: statistics.fmean(r[field] for r in members if r[field] is not None) if any(r[field] is not None for r in members) else None for field in fields}
    groups = defaultdict(list)
    for (recipe, session, image_id), seeds in by_image.items():
        groups[(recipe, session)].append({"image_id": image_id, **means(seeds)})
    session_rows = []
    for (recipe, session), members in sorted(groups.items()):
        raw = [row for row in rows if row["recipe_id"] == recipe and row["session_id"] == session]
        session_rows.append({"recipe_id": recipe, "session_id": session, "images": len(members), **means(members),
                             "tp": sum(r["tp"] for r in raw), "fp": sum(r["fp"] for r in raw), "fn": sum(r["fn"] for r in raw)})
    summaries = []
    for recipe in sorted({row["recipe_id"] for row in rows}):
        sessions = [row for row in session_rows if row["recipe_id"] == recipe]
        members = [row for row in rows if row["recipe_id"] == recipe]
        average = means(sessions)
        unique_images = {row["image_id"]: row for row in members}
        summaries.append({"recipe_id": recipe, "sessions": len(sessions), "images": len(unique_images), "seeds": sorted({r.get("seed", 11) for r in members}), **average,
                          "count_mae": average["absolute_count_error"], "count_bias": average["signed_count_bias"],
                          "tp": sum(r["tp"] for r in members), "fp": sum(r["fp"] for r in members), "fn": sum(r["fn"] for r in members),
                          "total_duplicates": sum(r["duplicate_count"] for r in members),
                          "mean_upload_bytes": statistics.fmean(r["upload_bytes"] for r in members),
                          "mean_inference_seconds": statistics.fmean(r["inference_seconds"] for r in members),
                          "total_inference_seconds": sum(r["inference_seconds"] for r in members),
                          "total_upload_bytes": sum(r["upload_bytes"] for r in unique_images.values()),
                          "resource_basis": "Inference totals include all three training seeds; encoded upload payload counted once per photograph, no actual network transfer claimed",
                          "forward_calls": sum(r["forward_calls"] for r in members),
                          "processed_tensor_pixels": sum(r["processed_tensor_pixels"] for r in members),
                          "unit": "seeds averaged within image, images within session, equal session means; fixed public corpus, independence unestablished",
                          "ci_low": None, "ci_high": None})
    return summaries, session_rows
