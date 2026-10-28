"""Numerical/provenance tests. The first class audits data before any training."""

import copy
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from science.api import contract_signature, get_case, prepare_case, validate_contract
from science.common import ScienceError, artifact, canonical_bytes, file_hash, read_json
from science.prepare import load_prepared
from science.spec import FEATURES, NUMERICAL_SPEC, SEEDS

PROJECT = Path(__file__).resolve().parents[1]
OFFICIAL_ARCHIVE = PROJECT.parent / "artifacts" / "crucible-data-audit" / "occupancy.zip"


def locked(prepared):
    contract = copy.deepcopy(prepared["contract"])
    contract.update(locked=True, approval={"reviewer_name": "Authored local numerical test"})
    return contract


def assert_code(test, code, callable_, *args, **kwargs):
    with test.assertRaises(ScienceError) as error:
        callable_(*args, **kwargs)
    test.assertEqual(error.exception.code, code)


class Test01PreparationBeforeTraining(unittest.TestCase):
    def test_01_metadata_is_pure(self):
        with patch("builtins.open", side_effect=AssertionError("metadata IO")):
            case = get_case("occupancy")
        self.assertEqual(case["contract"]["seeds"], [11, 29, 47])
        self.assertEqual(case["contract"]["candidate"]["parameters"]["n_estimators"], 96)
        self.assertFalse(case["independence_established"])

    @unittest.skipUnless(OFFICIAL_ARCHIVE.is_file(), "Pinned official archive not supplied; use explicit source preparation")
    def test_02_official_timestamps_and_sealed_split_before_fits(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("sklearn.ensemble.RandomForestClassifier.fit", side_effect=AssertionError("fit during source audit")):
                prepared = prepare_case("occupancy", directory, source_zip=OFFICIAL_ARCHIVE)
            self.assertTrue(prepared["source"]["audit"]["performed_before_training"])
            audit = {item["split"]: item for item in prepared["source"]["audit"]["files"]}
            self.assertEqual(audit["train"]["rows"], 8143)
            self.assertEqual(audit["discovery"]["timestamp_min"], "2015-02-02 14:19:00")
            self.assertEqual(audit["discovery"]["timestamp_max"], "2015-02-04 10:43:00")
            self.assertEqual(audit["confirmation"]["rows"], 9752)
            self.assertEqual(audit["confirmation"]["calendar_days"], 8)
            self.assertEqual(audit["confirmation"]["timestamp_max"], "2015-02-18 09:19:00")
            self.assertTrue(all(item["overlap"] == 0 for item in prepared["source"]["audit"]["cross_file_timestamp_overlap"]))
            root = Path(directory)
            for split in ["discovery", "confirmation"]:
                with (root / "data" / f"{split}.csv").open() as handle:
                    self.assertEqual(next(csv.reader(handle)), ["row_id", "block_id", *FEATURES])
            self.assertFalse(any(item["kind"] in ["sealed_labels", "original_source"] for item in prepared["artifacts"]))
            self.assertTrue(all(item.get("private") for item in prepared["data_artifacts"] if item["kind"] in ["sealed_labels", "original_source"]))
            self.assertTrue((root / "frozen_source" / "science" / "verifier.py").is_file())
            self.assertEqual(file_hash(root / "source" / "occupancy.zip"), prepared["source"]["sha256"])
            self.assertEqual(prepare_case("occupancy", root, source_zip=OFFICIAL_ARCHIVE), prepared)

    def test_03_crash_window_resumes_identical_preparation(self):
        import science.prepare as module
        original = module.immutable_json
        with tempfile.TemporaryDirectory() as directory:
            def crash_at_publication(path, value):
                if Path(path).name == "prepared.json":
                    raise OSError("injected crash after source manifest")
                return original(path, value)
            with patch.object(module, "immutable_json", side_effect=crash_at_publication):
                with self.assertRaises(OSError):
                    prepare_case("synthetic", directory)
            root = Path(directory)
            before = (root / "source-manifest.json").read_bytes()
            prepared = prepare_case("synthetic", root)
            self.assertEqual(before, (root / "source-manifest.json").read_bytes())
            self.assertEqual(prepared["created_at"], prepared["source"]["retrieved_at"])
            load_prepared(root)

    def test_04_data_tamper_and_oracle_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared = prepare_case("synthetic", directory)
            contract = locked(prepared)
            changed = copy.deepcopy(contract)
            changed["candidate"]["parameters"]["n_estimators"] = 1
            assert_code(self, "ORACLE_PROTECTED", validate_contract, changed, prepared)
            changed = copy.deepcopy(contract)
            changed["practical_delta"] = 0.04
            validate_contract(changed, prepared)
            self.assertNotEqual(contract_signature(contract), contract_signature(changed))
            path = Path(directory) / "sealed" / "confirmation-labels.csv"
            path.write_bytes(path.read_bytes() + b"tampered\n")
            assert_code(self, "ARTIFACT_TAMPERED", load_prepared, directory)

    def test_05_independent_analytic_metric_and_inference(self):
        from science.verifier import balanced_accuracy, holm_adjust, mechanical_decision, summarize_effects
        self.assertEqual(balanced_accuracy([0, 0, 1, 1], [0, 1, 1, 1]), 0.75)
        self.assertEqual(balanced_accuracy([0, 0, 1, 1], [1, 1, 0, 0]), 0.0)
        self.assertIsNone(balanced_accuracy([0, 0], [0, 1]))
        adjusted = holm_adjust([0.01, 0.04, 0.03])
        for observed, expected in zip(adjusted, [0.03, 0.06, 0.06]):
            self.assertAlmostEqual(observed, expected)
        summary = summarize_effects([0.20, 0.21, 0.19, 0.22, 0.18, 0.205, 0.195, 0.215])
        self.assertLess(summary["greater_holm_p"], 0.05)
        self.assertEqual(mechanical_decision(summary, 8, True, "in_scope", True)["outcome"], "supported_in_tested_scope")
        self.assertEqual(mechanical_decision(summary, 5, True, "in_scope", True)["outcome"], "inconclusive")
        self.assertEqual(mechanical_decision(summary, 8, False, "in_scope", True)["outcome"], "inconclusive")
        negative = summarize_effects([-0.1, -0.12, -0.08, -0.11, -0.09, -0.105])
        self.assertEqual(mechanical_decision(negative, 6, True, "applicability", True)["outcome"], "boundary_identified")
        uncertain = summarize_effects([-0.3, 0.3, -0.2, 0.2, -0.1, 0.1])
        self.assertEqual(mechanical_decision(uncertain, 6, True, "in_scope", True)["outcome"], "inconclusive")

    def test_06_interrupted_immutable_write_never_publishes_partial_bytes(self):
        from science.common import immutable_bytes
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.json"
            with patch("science.common.os.fsync", side_effect=OSError("injected interruption during durable write")):
                with self.assertRaises(OSError):
                    immutable_bytes(path, b"complete immutable source")
            self.assertFalse(path.exists())
            # A hard-killed process could leave this ignored sibling temp.
            (Path(directory) / ".source.json.stranded.tmp").write_bytes(b"partial")
            immutable_bytes(path, b"complete immutable source")
            self.assertEqual(path.read_bytes(), b"complete immutable source")
            assert_code(self, "IMMUTABLE_CONFLICT", immutable_bytes, path, b"changed")


class Test02TrustedWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from science.orchestrate import explore, predict, reproduce, verify
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name) / "base"
        cls.prepared = prepare_case("synthetic", cls.root)
        # This assertion is an explicit pre-fit audit gate, separate from scores.
        assert cls.prepared["source"]["audit"]["performed_before_training"]
        cls.contract = locked(cls.prepared)
        cls.request = {"root": str(cls.root), "contract": cls.contract, "reproduction_accepted": True,
                       "registration": {"condition_id": "original", "registered_at": "2026-10-28T00:00:00Z", "reviewer_name": "Authored local test"},
                       "active_conditions": ["original", "co2_25", "co2_50", "co2_100", "light_50"]}
        cls.reproduction = reproduce(cls.request)
        cls.discovery = explore(cls.request)
        cls.prediction = predict(cls.request)
        cls.verification = verify(cls.request)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def clone(self):
        root = Path(self.temporary.name) / ("clone-" + str(self._testMethodName))
        shutil.copytree(self.root, root)
        request = copy.deepcopy(self.request)
        request["root"] = str(root)
        return root, request

    def oracle_request(self, root, request):
        result = read_json(root / "confirmation-prediction.json")
        return {**request, "root": str(root), "phase": "confirmation", "condition_ids": ["original"],
                "prediction_manifest": result["prediction_manifest"]}

    def rebind(self, root, request, receipt=None, predictions=None):
        envelope = request["prediction_manifest"]
        prediction_path = root / envelope["predictions"]["path"]
        receipt_path = root / envelope["receipt"]["path"]
        if predictions is not None:
            prediction_path.write_text(predictions)
            envelope["predictions"] = artifact(root, prediction_path, "unlabeled_predictions", "text/csv")
        receipt = receipt or read_json(receipt_path)
        receipt["predictions"]["sha256"] = envelope["predictions"]["sha256"]
        receipt_path.write_bytes(canonical_bytes(receipt) + b"\n")
        envelope["receipt"] = artifact(root, receipt_path, "training_receipt")

    def test_01_real_training_and_exact_replay(self):
        replay = self.reproduction["replay"]
        self.assertTrue(replay["identical_predictions"])
        self.assertTrue(replay["identical_fitted_states"])
        self.assertEqual(len(self.discovery["observations"]), 5)
        self.assertEqual(self.prediction["observations"], [])
        envelope = self.prediction["prediction_manifest"]
        receipt = read_json(self.root / envelope["receipt"]["path"])
        self.assertEqual(len(receipt["fit_receipts"]), 6)
        self.assertGreater(receipt["cpu_seconds"], 0)
        self.assertGreater(receipt["wall_seconds"], 0)
        self.assertFalse(receipt["environment"]["provider_credentials_present"])
        for fit in receipt["fit_receipts"]:
            self.assertGreater(fit["fit_wall_seconds"], 0)
        self.assertEqual(self.verification["verification"]["status"], "verified")
        self.assertEqual(self.verification["observations"][0]["blocks"], 24)
        self.assertIn(self.verification["conclusion"]["outcome"], ["supported_in_tested_scope", "inconclusive", "evidence_against_registered_claim"])

    def test_02_predictor_capsule_has_no_evaluation_labels(self):
        from science.predictor import _rows
        for task in self.root.glob("attempts/*/input/task.json"):
            self.assertEqual({p.name for p in task.parent.iterdir()}, {"task.json", "train.csv", "evaluation.csv"})
            with (task.parent / "evaluation.csv").open() as handle:
                self.assertNotIn("target", next(csv.reader(handle)))
            assert_code(self, "PREDICTOR_INPUT_SCHEMA", _rows, task.parent / "train.csv", False)

    def test_03_duplicate_prediction_rejected_even_after_rehash(self):
        from science.verifier import verify_predictions
        root, request = self.clone()
        oracle = self.oracle_request(root, request)
        path = root / oracle["prediction_manifest"]["predictions"]["path"]
        lines = path.read_text().splitlines()
        lines[2] = lines[1]
        self.rebind(root, oracle, predictions="\n".join(lines) + "\n")
        assert_code(self, "DUPLICATE_PREDICTION", verify_predictions, oracle)

    def test_04_false_count_rejected_even_after_rehash(self):
        from science.verifier import verify_predictions
        root, request = self.clone()
        oracle = self.oracle_request(root, request)
        receipt = read_json(root / oracle["prediction_manifest"]["receipt"]["path"])
        receipt["evaluation_rows"] += 1
        self.rebind(root, oracle, receipt=receipt)
        assert_code(self, "PREDICTION_COUNT", verify_predictions, oracle)

    def test_05_wrong_labels_and_count_rejected(self):
        from science.verifier import verify_predictions
        root, request = self.clone()
        labels = root / "sealed" / "confirmation-labels.csv"
        lines = labels.read_text().splitlines()
        row_id, target = lines[1].split(",")
        lines[1] = row_id + "," + str(1 - int(target))
        labels.write_text("\n".join(lines[:-1]) + "\n")
        assert_code(self, "ARTIFACT_TAMPERED", verify_predictions, self.oracle_request(root, request))

    def test_06_preprocessing_leakage_rejected_even_after_rehash(self):
        from science.verifier import verify_predictions
        root, request = self.clone()
        oracle = self.oracle_request(root, request)
        receipt = read_json(root / oracle["prediction_manifest"]["receipt"]["path"])
        receipt["fit_receipts"][0]["preprocessing"]["evaluation_fit_rows"] = 1
        self.rebind(root, oracle, receipt=receipt)
        assert_code(self, "PREPROCESSING_LEAKAGE", verify_predictions, oracle)

    def test_07_holdout_cannot_change_registered_condition(self):
        from science.orchestrate import predict
        root, request = self.clone()
        request["registration"]["condition_id"] = "co2_100"
        assert_code(self, "HOLDOUT_ALREADY_REGISTERED", predict, request)

    def test_08_portable_offline_actual_rerun_and_reverification(self):
        from science.bundle import export_case
        root, request = self.clone()
        exported = export_case(request)
        destination = Path(self.temporary.name) / "unpacked"
        with zipfile.ZipFile(root / exported["artifacts"][0]["path"]) as archive:
            self.assertFalse(any(".env" in name or "plans/" in name or "node_modules" in name for name in archive.namelist()))
            for name in archive.namelist():
                if name.endswith(".json"):
                    content = archive.read(name).decode()
                    self.assertNotIn(str(Path.home()), content, name)
                    self.assertNotIn(str(PROJECT), content, name)
            archive.extractall(destination)
        result = subprocess.run([sys.executable, "reproduce.py"], cwd=destination, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(read_json(destination / "rerun-result.json")["replay"]["identical_predictions"])
        self.assertTrue(read_json(destination / "reverify-result.json")["replay"]["numerical_agreement"])


if __name__ == "__main__":
    unittest.main()
