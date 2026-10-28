"""New adapters must not replace retained numerical source."""
import asyncio
import hashlib
import pytest
from api.config import Settings
from api.orchestrator import Orchestrator, ScienceError
from api.store import Store


def test_frozen_dispatch_rejects_source_drift(tmp_path):
    store = Store(tmp_path / "runtime")
    cfg = Settings(store.root, "fireworks", "model", "https://api.fireworks.ai/inference/v1", "", "", False, None)
    runner = Orchestrator(cfg, store)
    root = store.root / "cases/retained"
    package = root / "frozen_source/science"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    code = "import argparse,json\nfrom pathlib import Path\np=argparse.ArgumentParser();p.add_argument('stage');p.add_argument('--input');p.add_argument('--output');a=p.parse_args();Path(a.output).write_text(json.dumps({'executed':'retained-package-fixture'}))\n"
    (package / "cli.py").write_text(code)
    expected = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in package.glob("*.py")}
    doc = {"id": "retained", "adapter_id": "synthetic", "revision": 1, "artifacts": [], "run": None,
           "contract": {"active_conditions": []}, "registration": None, "reproduction_accepted": False,
           "source_snapshot_dir": "frozen_source", "trusted_code": expected}
    store.create(doc)
    with store.transaction():
        job = runner._queue(doc, "reproduce")
        store._save(doc)
    assert asyncio.run(runner._science(job, "reproduce")) == {"executed": "retained-package-fixture"}
    assert runner._science_working_directory(job, "reproduce") == root / "frozen_source"
    (package / "cli.py").write_text(code + "\n# changed\n")
    with pytest.raises(ScienceError) as changed:
        runner._science_working_directory(job, "reproduce")
    assert changed.value.code == "frozen_source_changed"
    (package / "cli.py").write_text(code)
    (package / "unexpected.py").write_text("raise RuntimeError('must not execute')\n")
    with pytest.raises(ScienceError) as extra:
        runner._science_working_directory(job, "reproduce")
    assert extra.value.code == "frozen_source_changed"
    (package / "unexpected.py").unlink()
    (package / "cli.py").unlink()
    with pytest.raises(ScienceError):
        runner._science_working_directory(job, "reproduce")
    store.close()
