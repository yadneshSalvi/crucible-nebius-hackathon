"""Analytic/adversarial fixtures, never real wheat scientific evidence."""
import copy
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from science import wheat
from science.common import ScienceError, artifact, canonical_bytes, digest, file_hash, immutable_bytes, immutable_json, read_json
from science.wheat_metrics import image_metrics, iou, summarize


def error(test, code, function, *args):
    with test.assertRaises(ScienceError) as caught:
        function(*args)
    test.assertEqual(caught.exception.code, code)


def assets(base):
    records = []
    for i, role in enumerate(("train", "discovery", "final")):
        path = base / (role + ".png")
        Image.new("RGB", (1024, 1024), (i * 30, i * 40, i * 50)).save(path)
        records.append({"image_id": role, "role": role, "path": path.name, "sha256": file_hash(path),
            "session_id": role, "group_id": role, "boxes": [[100, 100, 20, 30]], "bbox_format": "xywh"})
    path = base / "assets.json"
    path.write_bytes(canonical_bytes({"records": records, "license": "Authored test fixtures"}))
    return path


def fake_training(root):
    checkpoints, receipts = [], []
    for seed in wheat.TRAINING["seeds"]:
        path = immutable_bytes(root / "model" / ("seed-" + str(seed)) / "epochs" / "epoch-10.pt", ("TEST-FIXTURE-NOT-A-MODEL-" + str(seed)).encode())
        receipt = immutable_json(path.parent.parent / "training-receipt.json", {"seed": seed, "environment": {}, "training": wheat.TRAINING,
            "epochs_completed": 10, "evaluation_images_used": 0, "checkpoint_sha256": file_hash(path)})
        checkpoints.append({"seed": seed, **artifact(root, path)})
        receipts.append({"seed": seed, **artifact(root, receipt)})
    immutable_json(root / "training-result.json", {"checkpoints": checkpoints, "checkpoint_set_sha256": digest(checkpoints), "training_receipts": receipts})


def oracle_fixture(root, prepared, contract, recipes=None, split="discovery", registration=None, numeric=False):
    from science.wheat_detector import transformed
    recipes = recipes or ["native_full", "native_noop"]
    rows = read_json(root / "split-manifest.json")["splits"][split]
    capsule = root / "attempts" / ("fixture-" + split + "-" + digest(recipes)[:8]) / "input"
    output = capsule.parent / "output"
    capsule.mkdir(parents=True)
    features, predictions = [], []
    training = read_json(root / "training-result.json")
    checkpoints = []
    for checkpoint in training["checkpoints"]:
        name = "model-seed-" + str(checkpoint["seed"]) + ".pt"
        immutable_bytes(capsule / name, (root / checkpoint["path"]).read_bytes())
        checkpoints.append({"seed": checkpoint["seed"], "path": name, "sha256": checkpoint["sha256"]})
    for row in rows:
        name = row["image_id"] + ".png"
        immutable_bytes(capsule / name, (root / row["image"]["path"]).read_bytes())
        features.append({"image_id": row["image_id"], "image": name, "sha256": row["sha256"], "pixel_sha256": row["pixel_sha256"], "session_id": row["session_id"], "width": 1024, "height": 1024})
    task = {"split": split, "recipe_ids": recipes, "images": features, "checkpoints": checkpoints, "contract_signature": wheat.signature(contract), "trusted_code": prepared["trusted_code"], "numerical_spec_sha256": digest(wheat.SPEC)}
    immutable_json(capsule / "task.json", task)
    for seed in wheat.TRAINING["seeds"]:
        for row in rows:
            for recipe_id in recipes:
                recipe = next(r for r in wheat.RECIPES if r["id"] == recipe_id)
                _, upload, transform = transformed(root / row["image"]["path"], recipe)
                calls = 9 if recipe["mode"] != "full" else 1
                sizes = wheat.SPEC["multiscale"]["min_sizes"] if recipe["mode"] == "multiscale" else [800] * calls
                shapes = [[1, 3, math.ceil(s / 32) * 32, math.ceil(s / 32) * 32] for s in sizes]
                grid = [[x, y, x + 512, y + 512] for y in (0, 409, 512) for x in (0, 409, 512)] if recipe["mode"] == "tiles" else None
                box = {"box": [100., 100., 120., 130.], "score": .9}
                predictions.append({"image_id": row["image_id"], "recipe_id": recipe_id, "seed": seed, "source_sha256": row["sha256"], "source_pixel_sha256": row["pixel_sha256"],
                    "transform": transform, "boxes": [box], "raw_predictions": [{**box, "call": 0}], "tile_bboxes": grid, "upload_bytes": len(upload), "inference_seconds": .1,
                    "forward_calls": calls, "processed_tensor_shapes": shapes, "processed_tensor_pixels": sum(s[0] * s[2] * s[3] for s in shapes)})
    if numeric:
        from science.wheat_storage import PredictionWriter
        writer = PredictionWriter()
        for prediction in predictions:
            writer.add(prediction)
        path = writer.publish(output)
    else:
        path = immutable_json(output / "predictions.json", predictions)
    training = read_json(root / "training-result.json")
    receipt = {"contract_signature": wheat.signature(contract), "split": split, "recipe_ids": recipes, "checkpoint_set_sha256": training["checkpoint_set_sha256"],
        "provider_credentials_present": False, "evaluation_labels_present": False, "predictions_sha256": file_hash(path), "input_manifest_sha256": file_hash(capsule / "task.json"), "prediction_records": len(predictions)}
    immutable_json(output / "receipt.json", receipt)
    immutable_json(capsule.parent / "execution.json", {"test_fixture": True})
    envelope = {"split": split, "recipe_ids": recipes, "contract_signature": wheat.signature(contract), "checkpoint_set_sha256": training["checkpoint_set_sha256"],
        "predictions": artifact(root, path), "receipt": artifact(root, output / "receipt.json"), "input_manifest": artifact(root, capsule / "task.json"), "execution": artifact(root, capsule.parent / "execution.json")}
    if registration:
        envelope["registration_sha256"] = registration["sha256"]
    return {"root": str(root), "contract": contract, "phase": "confirmation" if split == "confirmation" else "discovery", "prediction_manifest": envelope}


class TestWheatMetrics(unittest.TestCase):
    def test_complete_reproducible_epoch_shuffle_uses_separate_rng(self):
        import random
        inventory = ["image-%04d" % i for i in range(100)]
        hashes = set()
        for seed in (11, 29, 47):
            for epoch in range(1, 11):
                order = wheat.training_order(inventory, seed, epoch)
                self.assertEqual(sorted(order), inventory)
                self.assertEqual(order, wheat.training_order(inventory, seed, epoch))
                hashes.add(digest(order))
        self.assertEqual(len(hashes), 30)
        random.seed(123)
        expected = random.random()
        random.seed(123)
        wheat.training_order(inventory, 11, 1)
        self.assertEqual(random.random(), expected)
    def test_one_to_one_and_cancelling_count_error(self):
        metrics = image_metrics([[0, 0, 10, 10], [20, 20, 30, 30]], [{"box": [0, 0, 10, 10], "score": .9}, {"box": [0, 0, 10, 10], "score": .8}], 100, 100)
        self.assertEqual((metrics["tp"], metrics["fp"], metrics["fn"], metrics["duplicate_count"]), (1, 1, 1, 1))
        self.assertEqual(metrics["absolute_count_error"], 0)
        self.assertEqual(metrics["recall"], .5)
        self.assertEqual(metrics["detection_accuracy_iou50"], 1 / 3)

    def test_boundaries_empty_and_invalid_boxes(self):
        self.assertEqual(iou([0, 0, 3, 2], [1, 0, 4, 2]), .5)
        self.assertEqual(image_metrics([[0, 0, 3, 2]], [{"box": [1, 0, 4, 2], "score": .5}], 10, 10)["tp"], 1)
        empty = image_metrics([], [], 10, 10)
        self.assertEqual(empty["detection_accuracy_iou50"], 1)
        self.assertIsNone(empty["recall"])
        error(self, "BOX_BOUNDS", image_metrics, [[-1, 0, 3, 2]], [], 10, 10)
        error(self, "BOX_SCHEMA", image_metrics, [[0, 0, float("nan"), 2]], [], 10, 10)

    def test_seed_repeats_do_not_inflate_session_count(self):
        rows = []
        for session, images in (("a", ["a1", "a2"]), ("b", ["b1"])):
            for image in images:
                for seed in (11, 29, 47):
                    m = image_metrics([[0, 0, 1, 1]], [] if session == "a" else [{"box": [0, 0, 1, 1], "score": .9}], 10, 10)
                    rows.append({"recipe_id": "native_full", "image_id": image, "session_id": session, "seed": seed, **m, "upload_bytes": 100, "inference_seconds": .1, "forward_calls": 1, "processed_tensor_pixels": 640000})
        result, _ = summarize(rows)
        self.assertEqual((result[0]["sessions"], result[0]["images"], result[0]["count_mae"]), (2, 3, .5))
        self.assertIsNone(result[0]["ci_low"])

    def test_nullable_metrics_average_seeds_then_images(self):
        rows = []
        for image in ("a", "b"):
            for seed in (11, 29, 47):
                m = image_metrics([], [], 10, 10)
                m["precision"] = (0.0 if seed == 11 else None) if image == "a" else 1.0
                m["mean_matched_iou"] = m["precision"]
                rows.append({"recipe_id": "native_full", "image_id": image, "session_id": "one", "seed": seed, **m,
                    "upload_bytes": 100, "inference_seconds": .1, "forward_calls": 1, "processed_tensor_pixels": 640000})
        result, _ = summarize(rows)
        self.assertEqual(result[0]["precision"], .5)
        self.assertEqual(result[0]["mean_matched_iou"], .5)
        self.assertAlmostEqual(result[0]["total_inference_seconds"], .6)
        self.assertEqual(result[0]["total_upload_bytes"], 200)

    def test_lossless_numeric_roundtrip_preserves_shifted_subpixel_bits(self):
        import numpy as np
        from science.wheat_storage import PredictionWriter, prediction_rows
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory, patch("science.wheat.shutil.disk_usage", return_value=SimpleNamespace(free=100 * 1024**3)):
            root = Path(directory)
            x = float(np.float32(.001234567)) + 409
            self.assertNotEqual(float(np.float32(x)), x)
            raw = {"box": [x, 412.0, x + 10, 430.0], "score": float(np.float32(.9123456)), "call": 1}
            actual_sahi_box = [float(np.float32(v)) for v in raw["box"]]
            row = {"image_id": "test", "seed": 11, "recipe_id": "native_tiles", "raw_predictions": [raw], "boxes": [{"box": actual_sahi_box, "score": raw["score"]}]}
            writer = PredictionWriter()
            writer.add(row)
            path = writer.publish(root)
            decoded = list(prediction_rows(root, path))
            self.assertEqual(decoded, [row])
            index = read_json(path)
            np.savez(root / "boxes.npz", raw=np.asarray([object()], dtype=object), selected=np.empty(0, dtype=np.uint32), final=np.empty((0, 5), dtype=np.float64))
            index["arrays"]["sha256"] = file_hash(root / "boxes.npz")
            path.write_bytes(canonical_bytes(index))
            error(self, "PREDICTION_SCHEMA", lambda: list(prediction_rows(root, path)))


class TestWheatIntegrity(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        self.disk = patch("science.wheat.shutil.disk_usage", return_value=SimpleNamespace(free=100 * 1024**3))
        self.disk.start()
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = assets(self.base)
        self.root = self.base / "case"
        self.prepared = wheat.prepare({"root": str(self.root), "source_manifest": str(self.source)})
        self.contract = copy.deepcopy(self.prepared["contract"])
        self.contract["locked"] = True

    def tearDown(self):
        self.temp.cleanup()
        self.disk.stop()

    def test_pure_metadata_and_final_privacy_before_fit(self):
        with patch("builtins.open", side_effect=AssertionError("metadata IO")):
            self.assertEqual(wheat.metadata()["contract"]["training"]["seeds"], [11, 29, 47])
        self.assertTrue(self.prepared["source"]["audit"]["performed_before_training"])
        self.assertFalse(any("confirmation" in a["path"] or a["kind"] == "sealed_boxes" for a in self.prepared["artifacts"]))
        self.assertEqual(read_json(self.root / "sealed" / "final.json")["boxes"], [[100., 100., 120., 130.]])
        self.assertEqual(len(self.prepared["final_pixel_hashes"]), 1)
        self.assertEqual(wheat.prepare({"root": str(self.root), "source_manifest": str(self.source)}), self.prepared)
        retained = read_json(self.root / "split-manifest.json")["splits"]["train"][0]["image"]["path"]
        self.assertEqual((self.root / retained).stat().st_ino, (self.base / "train.png").stat().st_ino)

    def test_storage_failure_precedes_retention_or_training(self):
        from types import SimpleNamespace
        new_root = self.base / "blocked"
        with patch("science.wheat.shutil.disk_usage", return_value=SimpleNamespace(free=0)):
            error(self, "INSUFFICIENT_STORAGE", wheat.prepare, {"root": str(new_root), "source_manifest": str(self.source)})
            self.assertFalse((new_root / "preparation-identity.json").exists())
            error(self, "INSUFFICIENT_STORAGE", wheat.train, {"root": str(self.root), "contract": self.contract})

    def test_dependency_lock_is_frozen_hashed_and_tamper_checked(self):
        record = self.prepared["dependencies"]["files"]["requirements-wheat.lock"]
        path = self.root / record["path"]
        original = Path(wheat.__file__).parent.parent / "requirements-wheat.lock"
        self.assertEqual(path.read_bytes(), original.read_bytes())
        self.assertEqual(self.contract["dependency_lock_sha256"], file_hash(path))
        self.assertIn(b"requests==", path.read_bytes())
        self.assertGreater(path.read_bytes().count(b"--hash=sha256:"), 10)
        path.write_bytes(path.read_bytes() + b"\n# changed after preparation\n")
        error(self, "ARTIFACT_TAMPERED", wheat.load, self.root)

    def test_fixed_png_codec_and_pixel_identical_noop(self):
        import io
        from science.wheat_detector import transformed
        from science.wheat_metrics import audit_pixels
        path = self.base / "discovery.png"
        source, full, full_transform = transformed(path, wheat.RECIPES[0])
        noop, noop_upload, noop_transform = transformed(path, wheat.RECIPES[1])
        self.assertEqual(full, noop_upload)
        self.assertEqual(source.tobytes(), noop.tobytes())
        self.assertEqual(full_transform["processed_pixel_sha256"], noop_transform["processed_pixel_sha256"])
        small_recipe = next(r for r in wheat.RECIPES if r["id"] == "retain_256")
        canvas, upload, transform = transformed(path, small_recipe)
        with Image.open(io.BytesIO(upload)) as image:
            self.assertEqual((image.format, image.size), ("PNG", (256, 256)))
        self.assertEqual(canvas.size, (1024, 1024))
        audit_pixels(path, small_recipe, {"transform": transform, "upload_bytes": len(upload)})

    def test_cross_role_group_and_pixels_rejected(self):
        source = read_json(self.source)
        source["records"][1]["group_id"] = source["records"][0]["group_id"]
        error(self, "SPLIT_LEAKAGE", wheat._normalize_records, source, self.base)
        source = read_json(self.source)
        source["records"][1].update(path=source["records"][0]["path"], sha256=source["records"][0]["sha256"])
        error(self, "SPLIT_LEAKAGE", wheat._normalize_records, source, self.base)

    def test_recomputed_oracle_and_rehashed_duplicate_rejection(self):
        fake_training(self.root)
        request = oracle_fixture(self.root, self.prepared, self.contract)
        result = wheat.oracle(request)
        self.assertEqual(result["metrics"][0]["count_mae"], 0)
        self.assertEqual(len(result["image_records"]), 6)
        envelope = request["prediction_manifest"]
        path = self.root / envelope["predictions"]["path"]
        changed = read_json(path)
        changed[1] = changed[0]
        path.write_bytes(canonical_bytes(changed) + b"\n")
        envelope["predictions"] = artifact(self.root, path)
        receipt_path = self.root / envelope["receipt"]["path"]
        receipt = read_json(receipt_path)
        receipt["predictions_sha256"] = file_hash(path)
        receipt_path.write_bytes(canonical_bytes(receipt) + b"\n")
        envelope["receipt"] = artifact(self.root, receipt_path)
        error(self, "DUPLICATE_PREDICTION", wheat.oracle, request)

    def test_final_registration_and_portable_separate_process_metrics(self):
        fake_training(self.root)
        selected = None
        for recipe in ("native_full", "native_noop", "retain_256"):
            request = oracle_fixture(self.root, self.prepared, self.contract, [recipe])
            result = wheat.oracle(request)
            result["prediction_manifest"] = request["prediction_manifest"]
            immutable_json(self.root / "discovery" / (recipe + ".json"), result)
            if recipe == "retain_256":
                selected = result
        manifest = read_json(self.root / "split-manifest.json")
        self.assertTrue(wheat.noop_equivalence(self.root, manifest)["passed"])
        request = {"root": str(self.root), "contract": self.contract, "registration": {"policy_id": "retain_256", "registered_at": "2026-10-28T00:00:00Z",
            "reviewer_name": "Authored test fixture", "parent_discovery_sha256": digest(selected)}}
        registration = wheat.freeze_registration(request)
        family = ["retain_256", "native_full", "native_tiles", "native_multiscale"]
        self.assertEqual(registration["comparison_recipe_ids"], family)
        changed = copy.deepcopy(request)
        changed["registration"]["policy_id"] = "retain_512"
        error(self, "REGISTRATION_LINEAGE", wheat.freeze_registration, changed)
        error(self, "CONFIRMATION_FROZEN", wheat.explore, {**request, "recipe_ids": ["retain_768"]})
        oracle = oracle_fixture(self.root, self.prepared, self.contract, family, "confirmation", registration, numeric=True)
        immutable_json(self.root / "final-prediction.json", {"prediction_manifest": oracle["prediction_manifest"], "private_artifacts": []})
        wheat.oracle(oracle)
        exported = wheat.export_case(request)
        import zipfile
        destination = self.base / "unpacked"
        with zipfile.ZipFile(self.root / exported["artifacts"][0]["path"]) as bundle:
            self.assertFalse(any(".env" in name or "plans/" in name for name in bundle.namelist()))
            self.assertEqual(bundle.read("requirements-wheat.lock"), (self.root / "environment" / "requirements-wheat.lock").read_bytes())
            self.assertEqual(bundle.read("case/environment/requirements-wheat.lock"), bundle.read("requirements-wheat.lock"))
            readme = bundle.read("README-REPRODUCE.md").decode()
            self.assertIn("case/model/seed-11/training-receipt.json", readme)
            self.assertIn("--require-hashes", readme)
            self.assertIn("Extraction and replay require separate space", readme)
            bundle.extractall(destination)
        replay_request = {**request, "root": str(destination / "case")}
        plan = wheat.replay_workspace_plan(replay_request, metrics_only=True)
        self.assertEqual(plan["alias_full_copy_fallback_bytes"], sum(row["bytes"] for row in plan["missing_final_capsule_aliases"]))
        self.assertGreater(plan["alias_full_copy_fallback_bytes"], 0)
        fresh = wheat.replay_workspace_plan(replay_request)
        self.assertGreater(fresh["actual_retained_prediction_bytes"], 0)
        self.assertGreater(fresh["new_capsule_full_copy_fallback_bytes"], 0)
        self.assertGreater(fresh["additional_bytes"], plan["additional_bytes"])
        from types import SimpleNamespace
        with patch("science.wheat.shutil.disk_usage", return_value=SimpleNamespace(free=0)):
            error(self, "INSUFFICIENT_STORAGE", wheat.admit_replay_workspace, replay_request)
            with patch("science.wheat._prediction", side_effect=AssertionError("inference before admission")):
                error(self, "INSUFFICIENT_STORAGE", wheat.rerun, replay_request)
        self.assertFalse((destination / "local-replay-request.json").exists())
        self.assertTrue(all(not (destination / "case" / row["path"]).exists() for row in plan["missing_final_capsule_aliases"]))
        verified = subprocess.run([sys.executable, "reproduce.py", "--verify-only"], cwd=destination, capture_output=True, text=True, timeout=30)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertTrue(all(not (destination / "case" / row["path"]).exists() for row in plan["missing_final_capsule_aliases"]))
        wrapper = """import os,runpy,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
real_link=os.link
def cross_filesystem(source,destination,*args,**kwargs):
 if Path(source).parent!=Path(destination).parent:raise OSError('simulated cross-filesystem source')
 return real_link(source,destination,*args,**kwargs)
sys.argv=['reproduce.py','--metrics-only']
with patch('shutil.disk_usage',return_value=SimpleNamespace(free=100*1024**3)), patch('os.link',side_effect=cross_filesystem):
 runpy.run_path('reproduce.py',run_name='__main__')
"""
        completed = subprocess.run([sys.executable, "-c", wrapper], cwd=destination, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(read_json(destination / "reverify-result.json")["replay"]["numerical_agreement"])
        for row in plan["missing_final_capsule_aliases"]:
            copied, original = destination / "case" / row["path"], destination / "case" / row["source"]
            self.assertEqual(file_hash(copied), file_hash(original))
            self.assertNotEqual(copied.stat().st_ino, original.stat().st_ino)

    def test_final_registration_requires_cross_envelope_noop(self):
        fake_training(self.root)
        oracle = oracle_fixture(self.root, self.prepared, self.contract, ["retain_256"])
        result = wheat.oracle(oracle)
        result["prediction_manifest"] = oracle["prediction_manifest"]
        immutable_json(self.root / "discovery" / "selected.json", result)
        request = {"root": str(self.root), "contract": self.contract, "registration": {"policy_id": "retain_256", "registered_at": "2026-10-28T00:00:00Z",
            "reviewer_name": "Authored test fixture", "parent_discovery_sha256": digest(result)}}
        error(self, "NOOP_REQUIRED", wheat.freeze_registration, request)


if __name__ == "__main__":
    unittest.main()
