"""Offline acquisition fixtures; synthetic bytes are never wheat evidence."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
from types import SimpleNamespace
import zipfile

import httpx
import pytest


ARCHIVE_SIZE = 10215190132
ARCHIVE_URL = "https://example.test/gwhd_2021.zip"
HTTPX_CLIENT = httpx.Client


@pytest.fixture
def download(monkeypatch):
    scripts = Path(__file__).parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("wheat_download_transport_fixture", scripts / "download_wheat_catalog.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


class SparseArchive:
    """Serve a real tiny ZIP at the end of the pinned logical archive size.

    ZipFile supports a prepended archive, so this exercises real ZIP offsets
    without allocating or downloading the audited ten-gigabyte source.
    """

    def __init__(self, *, corrupt_member=None, workers=1, synchronize=False, member_count=8):
        self.members = {f"gwhd_2021/images/image-{i:02d}.png": bytes([65 + i]) * (1024 + i) for i in range(member_count)}
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as zf:
            for name, payload in self.members.items():
                zf.writestr(name, payload)
            zf.writestr("gwhd_2021/images/unselected.png", b"not in the fixed cohort")
            zf.writestr("gwhd_2021/competition_test.csv", b"unreleased labels")
        self.data = output.getvalue()
        with zipfile.ZipFile(io.BytesIO(self.data)) as zf:
            self.infos = {entry.filename: entry for entry in zf.infolist()}
            if corrupt_member is not None:
                entry = self.infos[corrupt_member]
                offset = entry.header_offset + 30 + len(entry.filename.encode()) + len(entry.extra)
                changed = bytearray(self.data)
                changed[offset] ^= 1
                self.data = bytes(changed)
        self.calls = []
        self.clients = []
        self.guard = threading.Lock()
        self.first_worker_requests = set()
        self.barrier = threading.Barrier(workers) if synchronize and workers > 1 else None
        self.range_error = None

    def setup_root(self, root):
        root.mkdir(parents=True, exist_ok=True)
        # Reverse the role plan to ensure transport order comes from ZIP offsets.
        images = [{"image_id": Path(name).stem, "source_filename": Path(name).name, "role": "train"} for name in reversed(self.members)]
        plan = {"format": "crucible.wheat-role-plan/v1", "images": images}
        (root / "role-plan.json").write_text(json.dumps(plan))

    def factory(self, *args, **kwargs):
        assert kwargs.get("verify", True) is not False, "TLS verification must stay enabled"
        client_id = object()
        with self.guard:
            self.clients.append(client_id)

        def respond(request):
            current = threading.current_thread().ident
            if str(request.url) != ARCHIVE_URL:
                assert str(request.url) == "https://zenodo.org/api/records/5092309"
                return httpx.Response(200, json={"files": [{"key": "gwhd_2021.zip", "size": ARCHIVE_SIZE,
                    "checksum": "md5:22b4b542c9ae7e056d7fcdeae9ecaed5", "links": {"self": ARCHIVE_URL}}]})
            assert request.url.scheme == "https"
            assert request.headers["accept-encoding"] == "identity"
            match = re.fullmatch(r"bytes=(\d+)-(\d+)", request.headers["range"])
            assert match is not None
            start, end = map(int, match.groups())
            assert 0 <= start <= end < ARCHIVE_SIZE
            assert end - start + 1 <= 32 * 1024 * 1024
            with self.guard:
                self.calls.append((current, client_id, start, end))
                first_worker = current != threading.main_thread().ident and current not in self.first_worker_requests
                self.first_worker_requests.add(current)
            if first_worker and self.barrier is not None:
                self.barrier.wait(timeout=10)
            prefix = max(0, min(end - start + 1, ARCHIVE_SIZE - len(self.data) - start))
            tail_start = max(0, start - (ARCHIVE_SIZE - len(self.data)))
            tail_end = max(0, end + 1 - (ARCHIVE_SIZE - len(self.data)))
            content = b"\0" * prefix + self.data[tail_start:tail_end]
            headers = {"content-range": f"bytes {start}-{end}/{ARCHIVE_SIZE}"}
            if self.range_error == "wrong-range":
                headers["content-range"] = f"bytes {start}-{end + 1}/{ARCHIVE_SIZE}"
            elif self.range_error == "truncated":
                content = content[:-1]
            elif self.range_error == "overlong":
                content += b"x"
            return httpx.Response(200 if self.range_error == "full-response" else 206, content=content, headers=headers)

        return HTTPX_CLIENT(transport=httpx.MockTransport(respond), timeout=5, follow_redirects=True)


def invoke(download, monkeypatch, root, *, workers=1, download_requested=True):
    monkeypatch.setattr(download.shutil, "disk_usage", lambda _: SimpleNamespace(free=100 * 1024 ** 3))
    argv = ["download_wheat_catalog.py", "--assets-root", str(root), "--workers", str(workers)]
    if download_requested:
        argv.append("--download")
    monkeypatch.setattr(sys, "argv", argv)
    download.main()


def trace_member_reads(monkeypatch):
    reads = defaultdict(list)
    original = zipfile.ZipFile.read

    def read(zf, name, *args, **kwargs):
        member = name.filename if isinstance(name, zipfile.ZipInfo) else name
        reads[threading.current_thread().ident].append(member)
        return original(zf, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "read", read)
    return reads


@pytest.mark.parametrize("workers", [1, 2, 4])
def test_workers_preserve_cohort_receipts_and_use_isolated_contiguous_readers(download, tmp_path, monkeypatch, workers):
    archive = SparseArchive(workers=workers, synchronize=True)
    archive.setup_root(tmp_path)
    reads = trace_member_reads(monkeypatch)
    monkeypatch.setattr(download.httpx, "Client", archive.factory)
    write_threads = []
    original_replace = Path.replace

    def replace(path, target):
        if path.suffix in {".part", ".tmp"}:
            write_threads.append(threading.current_thread().ident)
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    invoke(download, monkeypatch, tmp_path, workers=workers)
    receipt = json.loads((tmp_path / "download-progress.json").read_text())
    assert set(receipt["images"]) == set(archive.members)
    assert receipt["attempts"][-1]["status"] == "COMPLETED"
    for member, payload in archive.members.items():
        assert (tmp_path / "primary" / member).read_bytes() == payload
        assert receipt["images"][member] == {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
            "crc32": f"{archive.infos[member].CRC:08x}", "crc32_verified": True}
    assert write_threads and set(write_threads) == {threading.main_thread().ident}
    assert sorted(member for members in reads.values() for member in members) == sorted(archive.members)
    archive_order = list(archive.members)
    for members in reads.values():
        offsets = [archive_order.index(member) for member in members]
        assert offsets == list(range(min(offsets), max(offsets) + 1)), "worker shard must be contiguous in archive order"
    thread_clients = defaultdict(set)
    client_threads = defaultdict(set)
    for thread, client_id, _, _ in archive.calls:
        thread_clients[thread].add(client_id)
        client_threads[client_id].add(thread)
    assert all(len(clients) == 1 for clients in thread_clients.values())
    assert all(len(threads) == 1 for threads in client_threads.values())
    final_budget = receipt["attempts"][-1]["range_budget"]
    assert final_budget["requests"] == len(archive.calls)
    assert final_budget["requested_bytes"] == sum(end - start + 1 for _, _, start, end in archive.calls)
    assert final_budget["completed_range_bytes"] == final_budget["requested_bytes"]
    assert final_budget["failed_requests"] == 0
    assert threading.main_thread().ident in thread_clients, "directory reader belongs to the global budget"
    if workers > 1:
        assert len(archive.first_worker_requests - {threading.main_thread().ident}) == workers
    assert not list(tmp_path.rglob("*.part"))
    assert not list(tmp_path.rglob("*.tmp"))


def test_corrupt_member_never_reaches_image_or_receipt(download, tmp_path, monkeypatch):
    corrupt = "gwhd_2021/images/image-03.png"
    archive = SparseArchive(corrupt_member=corrupt)
    archive.setup_root(tmp_path)
    monkeypatch.setattr(download.httpx, "Client", archive.factory)
    with pytest.raises(zipfile.BadZipFile, match="CRC"):
        invoke(download, monkeypatch, tmp_path, workers=4)
    receipt = json.loads((tmp_path / "download-progress.json").read_text())
    assert corrupt not in receipt["images"]
    assert not (tmp_path / "primary" / corrupt).exists()
    assert receipt["attempts"][-1]["status"] == "INTERRUPTED_OR_FAILED"


def test_keyboard_interrupt_keeps_verified_prefix_and_resume_skips_it(download, tmp_path, monkeypatch):
    archive = SparseArchive()
    archive.setup_root(tmp_path)
    monkeypatch.setattr(download.httpx, "Client", archive.factory)
    original_write = download.write_json
    interrupted = False

    def interrupt_after_two(path, value):
        nonlocal interrupted
        original_write(path, value)
        if not interrupted and path.name == "download-progress.json" and len(value["images"]) >= 2:
            interrupted = True
            raise KeyboardInterrupt("offline interruption fixture")

    monkeypatch.setattr(download, "write_json", interrupt_after_two)
    with pytest.raises(KeyboardInterrupt):
        invoke(download, monkeypatch, tmp_path, workers=4)
    receipt_path = tmp_path / "download-progress.json"
    first = json.loads(receipt_path.read_text())
    pinned = dict(first["images"])
    assert len(pinned) >= 2
    assert first["attempts"][-1]["status"] == "INTERRUPTED_OR_FAILED"
    assert not [t for t in threading.enumerate() if t.name.startswith("wheat-source")]
    reads = trace_member_reads(monkeypatch)
    monkeypatch.setattr(download, "write_json", original_write)
    invoke(download, monkeypatch, tmp_path, workers=2)
    resumed = json.loads(receipt_path.read_text())
    assert resumed["attempts"][-1]["status"] == "COMPLETED"
    assert all(resumed["images"][name] == value for name, value in pinned.items())
    assert not set(pinned).intersection(member for members in reads.values() for member in members)
    assert set(resumed["images"]) == set(archive.members)


def test_storage_gate_runs_before_any_image_read(download, tmp_path, monkeypatch):
    archive = SparseArchive()
    archive.setup_root(tmp_path)
    reads = trace_member_reads(monkeypatch)
    monkeypatch.setattr(download.httpx, "Client", archive.factory)
    monkeypatch.setattr(download.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    monkeypatch.setattr(sys, "argv", ["download_wheat_catalog.py", "--assets-root", str(tmp_path), "--workers", "4", "--download"])
    with pytest.raises(SystemExit, match="Storage gate"):
        download.main()
    assert not reads
    assert not list((tmp_path / "primary").rglob("*.png"))
    assert not (tmp_path / "download-progress.json").exists()


def test_audit_mode_does_not_read_or_write_images(download, tmp_path, monkeypatch):
    archive = SparseArchive()
    archive.setup_root(tmp_path)
    reads = trace_member_reads(monkeypatch)
    monkeypatch.setattr(download.httpx, "Client", archive.factory)
    invoke(download, monkeypatch, tmp_path, workers=4, download_requested=False)
    assert not reads
    assert not (tmp_path / "primary").exists()
    assert not (tmp_path / "download-progress.json").exists()


def test_working_reserve_is_rechecked_before_each_image_publish(download, tmp_path, monkeypatch):
    archive = SparseArchive()
    archive.setup_root(tmp_path)
    monkeypatch.setattr(download.httpx, "Client", archive.factory)
    available = iter([100 * 1024 ** 3, 100 * 1024 ** 3, 0])
    monkeypatch.setattr(download.shutil, "disk_usage", lambda _: SimpleNamespace(free=next(available, 0)))
    monkeypatch.setattr(sys, "argv", ["download_wheat_catalog.py", "--assets-root", str(tmp_path), "--workers", "4", "--download"])
    with pytest.raises(OSError, match="reserve"):
        download.main()
    receipt = json.loads((tmp_path / "download-progress.json").read_text())
    assert len(receipt["images"]) == len(list((tmp_path / "primary").rglob("*.png"))) == 1
    assert receipt["attempts"][-1]["status"] == "INTERRUPTED_OR_FAILED"
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize("duplicate", ["archive", "role-plan"])
def test_duplicate_member_identities_fail_before_image_reads(download, tmp_path, monkeypatch, duplicate):
    archive = SparseArchive()
    archive.setup_root(tmp_path)
    if duplicate == "archive":
        output = io.BytesIO(archive.data)
        with zipfile.ZipFile(output, "a") as zf:
            with pytest.warns(UserWarning, match="Duplicate name"):
                zf.writestr(next(iter(archive.members)), b"ambiguous identity")
        archive.data = output.getvalue()
    else:
        path = tmp_path / "role-plan.json"
        plan = json.loads(path.read_text())
        plan["images"].append(plan["images"][0])
        path.write_text(json.dumps(plan))
    reads = trace_member_reads(monkeypatch)
    monkeypatch.setattr(download.httpx, "Client", archive.factory)
    with pytest.raises(ValueError, match="Duplicate"):
        invoke(download, monkeypatch, tmp_path, workers=4)
    assert not reads
    assert not (tmp_path / "primary").exists()
    assert not (tmp_path / "download-progress.json").exists()


def test_receipt_cannot_admit_member_outside_fixed_cohort(download, tmp_path, monkeypatch):
    archive = SparseArchive()
    archive.setup_root(tmp_path)
    receipt_path = tmp_path / "download-progress.json"
    initial = json.dumps({"role_plan_sha256": hashlib.sha256((tmp_path / "role-plan.json").read_bytes()).hexdigest(),
        "images": {"gwhd_2021/images/unselected.png": {"sha256": "0" * 64}}, "attempts": []})
    receipt_path.write_text(initial)
    reads = trace_member_reads(monkeypatch)
    monkeypatch.setattr(download.httpx, "Client", archive.factory)
    with pytest.raises(ValueError, match="outside the frozen cohort"):
        invoke(download, monkeypatch, tmp_path, workers=4)
    assert not reads
    assert receipt_path.read_text() == initial


@pytest.mark.parametrize("field,value", [("bytes", 1), ("crc32", "00000000"), ("crc32_verified", False)])
def test_resume_rejects_changed_pinned_member_metadata(download, tmp_path, monkeypatch, field, value):
    archive = SparseArchive()
    archive.setup_root(tmp_path)
    monkeypatch.setattr(download.httpx, "Client", archive.factory)
    invoke(download, monkeypatch, tmp_path)
    receipt_path = tmp_path / "download-progress.json"
    receipt = json.loads(receipt_path.read_text())
    member = next(iter(archive.members))
    receipt["images"][member][field] = value
    receipt_path.write_text(json.dumps(receipt))
    reads = trace_member_reads(monkeypatch)
    with pytest.raises(ValueError, match="metadata changed"):
        invoke(download, monkeypatch, tmp_path, workers=4)
    assert not reads
    assert json.loads(receipt_path.read_text())["images"][member][field] == value
    assert (tmp_path / "primary" / member).read_bytes() == archive.members[member]


def test_missing_pinned_file_cannot_be_replaced_under_changed_sha(download, tmp_path, monkeypatch):
    archive = SparseArchive()
    archive.setup_root(tmp_path)
    monkeypatch.setattr(download.httpx, "Client", archive.factory)
    invoke(download, monkeypatch, tmp_path)
    member = next(iter(archive.members))
    destination = tmp_path / "primary" / member
    destination.unlink()
    receipt_path = tmp_path / "download-progress.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["images"][member]["sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="previously pinned SHA256"):
        invoke(download, monkeypatch, tmp_path, workers=2)
    assert not destination.exists()
    assert json.loads(receipt_path.read_text())["images"][member]["sha256"] == "0" * 64


def test_asset_lock_is_exclusive_and_released_after_failure(download, tmp_path):
    with download.acquisition_lock(tmp_path):
        with pytest.raises((OSError, RuntimeError, SystemExit), match="(?i)(lock|another|progress)"):
            with download.acquisition_lock(tmp_path):
                pytest.fail("overlapping asset import admitted")
    with pytest.raises(ValueError, match="fixture failure"):
        with download.acquisition_lock(tmp_path):
            raise ValueError("fixture failure")
    with download.acquisition_lock(tmp_path):
        pass


def test_asset_lock_excludes_another_process(download, tmp_path):
    child = """import fcntl, pathlib, sys
with pathlib.Path(sys.argv[1]).open('a+b') as handle:
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(73)
"""
    with download.acquisition_lock(tmp_path):
        result = subprocess.run([sys.executable, "-c", child, str(tmp_path / ".download.lock")], capture_output=True, timeout=10)
    assert result.returncode == 73, result.stderr.decode()


@pytest.mark.parametrize("range_error", ["full-response", "wrong-range", "truncated", "overlong"])
def test_shared_reader_rejects_nonexact_range_responses(download, monkeypatch, range_error):
    archive = SparseArchive()
    archive.range_error = range_error
    transfer = download.TransferBudget(max_bytes=100, max_requests=4)
    with archive.factory() as client:
        reader = download.SharedRemoteZip(client, ARCHIVE_URL, ARCHIVE_SIZE, transfer)
        with pytest.raises(ValueError, match="(?i)(range|truncated)"):
            reader.read(10)
    assert len(archive.calls) == 1


def test_shared_byte_allowance_is_reserved_atomically_before_network(download):
    archive = SparseArchive()
    transfer = download.TransferBudget(max_bytes=10, max_requests=4)
    start = threading.Barrier(4)

    def read_one():
        with archive.factory() as client:
            reader = download.SharedRemoteZip(client, ARCHIVE_URL, ARCHIVE_SIZE, transfer)
            start.wait(timeout=10)
            try:
                return reader.read(6)
            except ValueError as exc:
                return exc

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: read_one(), range(4)))
    assert sum(isinstance(result, bytes) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 3
    assert len(archive.calls) == 1
    snapshot = transfer.snapshot()
    assert snapshot["requests"] == snapshot["completed_requests"] == 1
    assert snapshot["requested_bytes"] == snapshot["completed_range_bytes"] == 6


def test_failed_range_does_not_refund_shared_allowance(download):
    archive = SparseArchive()
    archive.range_error = "truncated"
    transfer = download.TransferBudget(max_bytes=10, max_requests=4)
    with archive.factory() as client:
        reader = download.SharedRemoteZip(client, ARCHIVE_URL, ARCHIVE_SIZE, transfer)
        with pytest.raises(ValueError, match="Truncated"):
            reader.read(6)
        with pytest.raises(ValueError, match="budget"):
            reader.read(6)
    assert len(archive.calls) == 1
    snapshot = transfer.snapshot()
    assert snapshot["requests"] == snapshot["failed_requests"] == 1
    assert snapshot["requested_bytes"] == 6
    assert snapshot["completed_range_bytes"] == snapshot["completed_requests"] == 0


def test_shared_request_allowance_rejects_before_network(download):
    archive = SparseArchive()
    transfer = download.TransferBudget(max_bytes=100, max_requests=1)
    with archive.factory() as client:
        reader = download.SharedRemoteZip(client, ARCHIVE_URL, ARCHIVE_SIZE, transfer)
        assert reader.read(6) == b"\0" * 6
        with pytest.raises(ValueError, match="budget"):
            reader.read(1)
    assert len(archive.calls) == 1


def test_closing_full_queue_stops_readers_without_publishing(download, monkeypatch):
    archive = SparseArchive(member_count=24)
    entries = [archive.infos[name] for name in archive.members]
    for entry in entries:
        entry.header_offset += ARCHIVE_SIZE - len(archive.data)
    full = threading.Event()
    abort = threading.Event()
    queues = []
    queue_type = download.queue.Queue
    full_exception = download.queue.Full

    class ObservedQueue(queue_type):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            queues.append(self)

        def put(self, *args, **kwargs):
            if abort.is_set():
                raise RuntimeError("release offline cancellation fixture")
            try:
                return super().put(*args, **kwargs)
            except full_exception:
                full.set()
                raise

    monkeypatch.setattr(download.queue, "Queue", ObservedQueue)
    reads = trace_member_reads(monkeypatch)
    stream = download.fetch_members({"links": {"self": ARCHIVE_URL}, "size": ARCHIVE_SIZE}, entries, 4,
        download.TransferBudget(ARCHIVE_SIZE * 2), client_factory=archive.factory, buffer_size=256)
    assert next(stream)[0].filename in archive.members
    assert full.wait(timeout=10), "fixture must reach backpressure before cancellation"
    assert len(queues) == 1 and queues[0].maxsize == queues[0].qsize() == 4
    assert sum(map(len, reads.values())) <= 9, "four queued, four held by workers, one consumed"
    close_errors = []

    def close():
        try:
            stream.close()
        except BaseException as exc:
            close_errors.append(exc)

    closer = threading.Thread(target=close, daemon=True)
    closer.start()
    closer.join(timeout=5)
    stalled = closer.is_alive()
    abort.set()  # Release a faulty implementation before failing the assertion.
    closer.join(timeout=5)
    assert not stalled, "generator close deadlocked with queue-full workers"
    assert not close_errors
    assert not [t for t in threading.enumerate() if t.name.startswith("wheat-source")]


def test_resume_adopts_crc_verified_orphan_after_rename_interrupt(download, tmp_path, monkeypatch):
    archive = SparseArchive()
    archive.setup_root(tmp_path)
    monkeypatch.setattr(download.httpx, "Client", archive.factory)
    original_replace = Path.replace
    interrupted = False

    def interrupt_after_rename(path, target):
        nonlocal interrupted
        result = original_replace(path, target)
        if not interrupted and path.suffix == ".part":
            interrupted = True
            raise KeyboardInterrupt("after image publication, before receipt mutation")
        return result

    monkeypatch.setattr(Path, "replace", interrupt_after_rename)
    with pytest.raises(KeyboardInterrupt):
        invoke(download, monkeypatch, tmp_path, workers=4)
    first = json.loads((tmp_path / "download-progress.json").read_text())
    assert first["images"] == {}
    orphans = list((tmp_path / "primary").rglob("*.png"))
    assert len(orphans) == 1
    orphan = orphans[0]
    original_bytes = orphan.read_bytes()
    original_stat = orphan.stat()
    monkeypatch.setattr(Path, "replace", original_replace)
    reads = trace_member_reads(monkeypatch)
    invoke(download, monkeypatch, tmp_path, workers=2)
    resumed = json.loads((tmp_path / "download-progress.json").read_text())
    member = orphan.relative_to(tmp_path / "primary").as_posix()
    assert member in {name for names in reads.values() for name in names}, "orphan must be CRC checked from its member"
    assert resumed["images"][member]["sha256"] == hashlib.sha256(original_bytes).hexdigest()
    assert orphan.read_bytes() == original_bytes
    assert orphan.stat().st_ino == original_stat.st_ino
    assert orphan.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert resumed["attempts"][-1]["status"] == "COMPLETED"


def test_workers_reject_unsupported_values_before_network(download, tmp_path, monkeypatch):
    def forbidden_client(*args, **kwargs):
        pytest.fail("invalid worker count reached network")

    monkeypatch.setattr(download.httpx, "Client", forbidden_client)
    monkeypatch.setattr(sys, "argv", ["download_wheat_catalog.py", "--assets-root", str(tmp_path), "--workers", "3", "--download"])
    with pytest.raises(SystemExit):
        download.main()
