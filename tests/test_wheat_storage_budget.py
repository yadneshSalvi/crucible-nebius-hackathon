"""Allocation fixtures, never detector evidence."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from science import wheat
from science.common import canonical_bytes, digest, file_hash


class StorageBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.manifest = {"splits": {r: [{"image": {"bytes": 1000}}] for r in ("train", "discovery", "confirmation")}}
        self.plan = {"training": wheat.TRAINING, "initialization": {}}
        self.save("training-plan.json", canonical_bytes(self.plan))
        self.baseline = self.budget()

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, name, content=b"x" * 4096):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def budget(self):
        return wheat.full_storage_plan(self.root, self.manifest)

    def bind(self, kind, seed=11, path=None):
        names = {"initialization": "model/initialization.pt", "resume": f"model/seed-{seed}/epochs/latest-resume.pt", "final": f"model/seed-{seed}/epochs/epoch-10.pt"}
        path = path or self.save(names[kind])
        sha = file_hash(path)
        if kind == "initialization":
            self.plan["initialization"] = {"sha256": sha}
            self.save("training-plan.json", canonical_bytes(self.plan))
        elif kind == "resume":
            self.save(f"model/seed-{seed}/epochs/epoch-03.json", canonical_bytes({"epoch": 3, "resumable_checkpoint_sha256_at_epoch": sha}))
        else:
            self.save(f"model/seed-{seed}/training-receipt.json", canonical_bytes({"plan_sha256": digest({**self.plan, "seed": seed}), "epochs_completed": 10, "checkpoint_sha256": sha}))
        return path

    def assert_no_credit(self):
        self.assertEqual(self.budget()["canonical_model_slots_credit_bytes"], 0)
        self.assertEqual(self.budget()["remaining_full_pipeline_bytes"], self.baseline["remaining_full_pipeline_bytes"])

    def test_attempt_hardlinks_copies_failed_outputs_and_zip_leave_reserve_intact(self):
        source = self.save("images/train/photo.png")
        alias = self.root / "attempts/failed/input/photo.png"
        alias.parent.mkdir(parents=True)
        os.link(source, alias)
        self.save("attempts/failed/input/copied.png", source.read_bytes())
        for name in ("attempts/failed/output/boxes.npz", "export/stale.zip", "unrelated.bin", "model/seed-11/epochs/.latest.tmp", "model/seed-99/epochs/epoch-10.pt"):
            self.save(name)
        self.assert_no_credit()

    def test_bound_slots_credit_only_allocated_bytes_and_protect_future_budgets(self):
        paths = [self.bind("initialization")]
        for seed in wheat.TRAINING["seeds"]:
            paths += [self.bind("resume", seed), self.bind("final", seed)]
        expected = sum(min(p.stat().st_size, p.stat().st_blocks * 512) for p in paths)
        actual = self.budget()
        self.assertEqual(actual["canonical_model_slots_credit_bytes"], expected)
        self.assertEqual(actual["remaining_full_pipeline_bytes"], self.baseline["remaining_full_pipeline_bytes"] - expected)
        keys = ("atomic_checkpoint_temp_bytes", "prediction_arrays_upper_bound_bytes", "ancillary_outputs_budget_bytes", "portable_zip_upper_bound_bytes")
        for key in keys:
            self.assertEqual(actual[key], self.baseline[key])
        self.assertGreaterEqual(actual["remaining_full_pipeline_bytes"], sum(actual[k] for k in keys))

    def test_shared_canonical_inode_credited_once(self):
        first = self.bind("resume", 11)
        second = self.root / "model/seed-29/epochs/latest-resume.pt"
        second.parent.mkdir(parents=True)
        os.link(first, second)
        self.bind("resume", 29, second)
        self.assertEqual(self.budget()["canonical_model_slots_credit_bytes"], min(first.stat().st_size, first.stat().st_blocks * 512))

    def test_every_source_tree_inode_excluded_even_with_hash_binding(self):
        for directory in ("images", "source", "sealed", "frozen_source"):
            with self.subTest(directory=directory):
                source = self.save(f"{directory}/source.bin")
                slot = self.root / "model/initialization.pt"
                slot.parent.mkdir(parents=True, exist_ok=True)
                slot.unlink(missing_ok=True)
                os.link(source, slot)
                self.bind("initialization", path=slot)
                self.assert_no_credit()

    def test_symlink_file_or_parent_not_credited(self):
        source = self.save("outside-model/initialization.pt")
        self.plan["initialization"] = {"sha256": file_hash(source)}
        self.save("training-plan.json", canonical_bytes(self.plan))
        model = self.root / "model"
        model.symlink_to(source.parent, target_is_directory=True)
        self.assert_no_credit()
        model.unlink()
        model.mkdir()
        (model / "initialization.pt").symlink_to(source)
        self.assert_no_credit()

    def test_sparse_slot_cannot_credit_unallocated_length(self):
        slot = self.save("model/initialization.pt", b"")
        with slot.open("wb") as handle:
            handle.truncate(1024 * 1024)
        self.bind("initialization", path=slot)
        self.assertEqual(self.budget()["canonical_model_slots_credit_bytes"], min(slot.stat().st_size, slot.stat().st_blocks * 512))

    def test_slots_have_individual_caps(self):
        for kind, mib in (("initialization", 128), ("resume", 576), ("final", 192)):
            with self.subTest(kind=kind):
                slot = self.bind(kind)
                original_stat = Path.stat

                def oversized(path, *args, **kwargs):
                    value = original_stat(path, *args, **kwargs)
                    if path == slot:
                        fields = {n: getattr(value, n) for n in dir(value) if n.startswith("st_")}
                        fields.update(st_size=2 * 1024**3, st_blocks=4 * 1024**2)
                        return SimpleNamespace(**fields)
                    return value

                before = self.budget()["canonical_model_slots_credit_bytes"]
                old_credit = min(slot.stat().st_size, slot.stat().st_blocks * 512)
                with patch.object(Path, "stat", oversized):
                    self.assertEqual(self.budget()["canonical_model_slots_credit_bytes"], before - old_credit + mib * 1024**2)

    def test_missing_malformed_stale_and_tampered_bindings_not_credited(self):
        slot = self.save("model/initialization.pt")
        self.assert_no_credit()
        self.save("training-plan.json", b"{malformed")
        self.assert_no_credit()
        self.bind("initialization", path=slot)
        slot.write_bytes(b"tampered")
        self.assert_no_credit()
        self.bind("resume")
        self.save("model/seed-11/epochs/epoch-04.json", canonical_bytes({"epoch": 4, "resumable_checkpoint_sha256_at_epoch": "0" * 64}))
        self.assert_no_credit()
