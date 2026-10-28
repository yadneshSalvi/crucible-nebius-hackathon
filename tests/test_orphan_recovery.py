"""Real child-process recovery probes; no detector, dataset or provider calls."""
import asyncio
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from api.config import Settings
from api.orchestrator import Orchestrator
from api.store import Store, digest
from api.wheat_protocol import initial_study


@pytest.mark.parametrize("module,should_stop", [("science.cli", True), ("science.wheat_cli", True), ("science.cli_extra", False)])
def test_restart_stops_only_exact_owned_worker_modules(tmp_path, module, should_stop):
    package = tmp_path / "science"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / (module.rsplit(".", 1)[-1] + ".py")).write_text("import time\ntime.sleep(60)\n")
    cfg = Settings(tmp_path / "runtime", "fireworks", "fixture", "https://fixture.invalid", "", "", False, None)
    store = Store(cfg.root)
    doc = initial_study()
    doc["reproduction_accepted"] = False
    store.create(doc)
    runner = Orchestrator(cfg, store)
    with store.transaction():
        doc = store._folio(doc["id"])
        job = runner._queue(doc, "prepare")
        store._save(doc)
    original = digest(job["input"])
    output = cfg.root / "jobs" / job["id"] / "probe.json"
    process = subprocess.Popen([sys.executable, "-m", module, "--output", str(output)], cwd=tmp_path,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        job.update(pid=process.pid, status="running")
        runner._save_job(job)
        asyncio.run(runner.startup())
        recovered = runner._current_job(job["id"])
        assert recovered["status"] == "interrupted" and recovered["can_resume"]
        assert recovered["fence"] == 2 and digest(recovered["input"]) == original
        if should_stop:
            assert process.wait(timeout=3) in (-signal.SIGTERM, -signal.SIGKILL)
            assert recovered["orphan_cleanup"] in {"terminated_exact_job_group", "killed_exact_job_group", "already_exited"}
        else:
            assert process.poll() is None
            assert recovered["orphan_cleanup"] == "not_running_or_pid_reused"
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
        store.close()


def test_orphan_directory_match_does_not_accept_a_prefix(tmp_path):
    directory = tmp_path / "jobs" / "exact-job"
    prefix_collision = f"python -m science.wheat_cli train --output {directory}-other/result.json"
    assert not Orchestrator._orphan_command_matches(prefix_collision, directory)
    assert not Orchestrator._orphan_command_matches(f"python -m science.cli_other --output {directory}/result.json", directory)
    assert Orchestrator._orphan_command_matches(f'python -m science.wheat_cli train --output "{directory}/result.json"', directory)
