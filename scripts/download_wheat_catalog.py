"""Retrieve the entire predefined source cohort without a second full ZIP copy.

Default mode is an asset/disk audit. --download requires enough space for every
missing image plus the declared working reserve. It never narrows the cohort.
--workers enables bounded concurrent HTTPS readers with one atomic publisher.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager, nullcontext
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import shutil
import threading
import zipfile

import httpx

from qualify_wheat_assets import RECORD_URL, RemoteZip


class TransferBudget:
    """One conservative range/request allowance shared by every reader."""

    def __init__(self, max_bytes, max_requests=4096):
        self.max_bytes, self.max_requests = max_bytes, max_requests
        self.requested_bytes, self.received_bytes = 0, 0
        self.requests, self.completed_requests, self.failed_requests = 0, 0, 0
        self.lock = threading.Lock()

    def reserve(self, count):
        with self.lock:
            if count <= 0 or count > 32 * 1024 * 1024 or self.requested_bytes + count > self.max_bytes or self.requests >= self.max_requests:
                raise ValueError("Shared archive range byte/request budget exceeded")
            # Reserve before the request. Failed/interrupted ranges never refund
            # this allowance, including any unknown partial response body.
            self.requested_bytes += count
            self.requests += 1

    def completed(self, count):
        with self.lock:
            self.received_bytes += count
            self.completed_requests += 1

    def failed(self):
        with self.lock:
            self.failed_requests += 1

    def snapshot(self):
        with self.lock:
            return {"max_bytes": self.max_bytes, "max_requests": self.max_requests,
                    "requested_bytes": self.requested_bytes, "completed_range_bytes": self.received_bytes,
                    "requests": self.requests, "completed_requests": self.completed_requests,
                    "failed_requests": self.failed_requests,
                    "scope": "All readers in this attempt; requested bytes include failed/in-flight ranges. One metadata API request is separate."}


class SharedRemoteZip(RemoteZip):
    def __init__(self, client, url, size, transfer):
        super().__init__(client, url, size, budget=transfer.max_bytes)
        self.transfer = transfer

    def read(self, count=-1):
        count = self.size - self.position if count < 0 else min(count, self.size - self.position)
        if count == 0:
            return b""
        self.transfer.reserve(count)
        try:
            data = super().read(count)
        except BaseException:
            self.transfer.failed()
            raise
        self.transfer.completed(len(data))
        return data


def make_client():
    return httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "Crucible-source-audit/1.0"})


@contextmanager
def acquisition_lock(root):
    """The OS releases this lock even if an importer crashes or is killed."""
    with (root / ".download.lock").open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another corpus importer holds this assets-directory lock") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def fetch_members(archive, entries, workers, transfer, *, client_factory=None, buffer_size=8 * 1024 * 1024):
    """Fetch contiguous shards; only the caller publishes bytes and receipts.

    Each reader owns its HTTPS client, ZipFile and read-ahead buffer. The bounded
    queue prevents readers from retaining the corpus in memory. Closing this
    generator stops new member reads and joins in-flight bounded requests.
    Retained completed payloads are bounded by (2 * workers + 1) members of at
    most 16 MiB, plus reader buffers and HTTP/decompression temporaries.
    """
    if workers not in (1, 2, 4):
        raise ValueError("Use one, two or four bounded source readers")
    if not entries:
        return
    client_factory = client_factory or make_client
    stop = threading.Event()
    completed = queue.Queue(maxsize=workers)

    def fetch(shard):
        with client_factory() as client:
            remote = SharedRemoteZip(client, archive["links"]["self"], archive["size"], transfer)
            with zipfile.ZipFile(io.BufferedReader(remote, buffer_size=buffer_size)) as zf:
                if len({entry.filename for entry in zf.infolist()}) != len(zf.infolist()):
                    raise ValueError("Duplicate primary archive member identity")
                for entry in shard:
                    if stop.is_set():
                        return
                    actual = zf.getinfo(entry.filename)
                    identity = ("filename", "header_offset", "file_size", "compress_size", "compress_type", "CRC", "flag_bits")
                    if any(getattr(actual, key) != getattr(entry, key) for key in identity):
                        raise ValueError("Primary archive member changed between range readers")
                    data = zf.read(actual)  # ZIP CRC passes before delivery.
                    if len(data) != entry.file_size:
                        raise ValueError("Primary archive member has unexpected decoded length")
                    while not stop.is_set():
                        try:
                            completed.put((entry, data), timeout=0.2)
                            break
                        except queue.Full:
                            continue

    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="wheat-source")
    futures = []
    try:
        for index in range(workers):
            shard = entries[len(entries) * index // workers:len(entries) * (index + 1) // workers]
            if shard:
                futures.append(executor.submit(fetch, shard))
        while True:
            for future in futures:
                if future.done():
                    future.result()  # Reject a failure before publishing more queued members.
            if all(future.done() for future in futures) and completed.empty():
                break
            try:
                yield completed.get(timeout=0.2)
            except queue.Empty:
                continue
    finally:
        stop.set()
        executor.shutdown(wait=True, cancel_futures=True)


def write_json(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as out:
        json.dump(value, out, indent=2)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    tmp.replace(path)


def acquire(args):
    root = args.assets_root.resolve()
    plan_bytes = (root / "role-plan.json").read_bytes()
    plan = json.loads(plan_bytes)
    plan_sha = hashlib.sha256(plan_bytes).hexdigest()
    reserve = int(args.reserve_gib * 1024 ** 3)
    transfer = TransferBudget(10215190132 * 2)
    with make_client() as client:
        response = client.get(RECORD_URL)
        response.raise_for_status()
        record = response.json()
        archives = [f for f in record["files"] if f["key"] == "gwhd_2021.zip"]
        if len(archives) != 1:
            raise ValueError("Unexpected primary archive inventory")
        archive = archives[0]
        if archive["size"] != 10215190132 or archive["checksum"] != "md5:22b4b542c9ae7e056d7fcdeae9ecaed5":
            raise ValueError("Primary archive version differs from the audited source")
        reader = SharedRemoteZip(client, archive["links"]["self"], archive["size"], transfer)
        # Bounded read-ahead reduces per-member HTTP requests. ZipFile reads
        # members in archive order, sharing this buffer; no whole ZIP is saved.
        buffered = io.BufferedReader(reader, buffer_size=8 * 1024 * 1024)
        with zipfile.ZipFile(buffered) as zf:
            entries = {e.filename: e for e in zf.infolist()}
            if len(entries) != len(zf.infolist()):
                raise ValueError("Duplicate primary archive member identity")
            selected = []
            for image in plan["images"]:
                filename = image["source_filename"]
                if Path(filename).name != filename or Path(filename).suffix != ".png":
                    raise ValueError("Unsafe source filename")
                entry = entries["gwhd_2021/images/" + filename]
                if entry.file_size > 16 * 1024 * 1024 or entry.is_dir():
                    raise ValueError("Unexpected primary image size/type")
                selected.append(entry)
        buffered.close()
    selected.sort(key=lambda e: e.header_offset)
    if len({entry.filename for entry in selected}) != len(selected):
        raise ValueError("Duplicate filename in the immutable source role plan")
    missing = [e for e in selected if not (root / "primary" / e.filename).exists()]
    remaining = sum(e.file_size for e in missing)
    free = shutil.disk_usage(root).free
    status = {"format": "crucible.wheat-download/v1", "role_plan_sha256": plan_sha, "planned_images": len(selected), "missing_images": len(missing), "missing_image_bytes": remaining, "required_free_bytes": remaining + reserve, "available_free_bytes": free, "reserve_bytes": reserve, "download_requested": args.download, "full_archive_checksum_verified": False, "started_at": datetime.now(timezone.utc).isoformat()}
    status.update(workers=args.workers, range_budget=transfer.snapshot(), transport_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    print(json.dumps(status, indent=2), flush=True)
    if not args.download:
        return
    if free < remaining + reserve:
        raise SystemExit("Storage gate: full cohort plus working reserve does not fit; no image downloaded")
    receipt_path = root / "download-progress.json"
    receipts = json.loads(receipt_path.read_text()) if receipt_path.exists() else {"role_plan_sha256": plan_sha, "images": {}, "attempts": []}
    if receipts["role_plan_sha256"] != plan_sha:
        raise ValueError("Cannot resume a different source role plan")
    if set(receipts["images"]) - {entry.filename for entry in selected}:
        raise ValueError("Download receipts contain members outside the frozen cohort")
    attempt = {**status, "status": "RUNNING"}
    receipts["attempts"].append(attempt)
    write_json(receipt_path, receipts)
    try:
        pending = []
        for entry in selected:
            dest = root / "primary" / entry.filename
            if not dest.resolve().is_relative_to(root):
                raise ValueError("Source destination escapes asset root")
            previous = receipts["images"].get(entry.filename)
            if previous:
                if previous.get("bytes") != entry.file_size or previous.get("crc32") != f"{entry.CRC:08x}" or previous.get("crc32_verified") is not True:
                    raise ValueError("Previously pinned source member metadata changed")
                if dest.exists():
                    if dest.stat().st_size != entry.file_size or hashlib.sha256(dest.read_bytes()).hexdigest() != previous["sha256"]:
                        raise ValueError("Previously pinned source image changed")
                    continue
            pending.append(entry)
        with closing(fetch_members(archive, pending, args.workers, transfer)) as fetched:
            for entry, data in fetched:
                dest = root / "primary" / entry.filename
                if not dest.resolve().is_relative_to(root):
                    raise ValueError("Source destination escapes asset root")
                fingerprint = hashlib.sha256(data).hexdigest()
                previous = receipts["images"].get(entry.filename)
                if previous and fingerprint != previous["sha256"]:
                    raise ValueError("Re-fetched image differs from its previously pinned SHA256")
                if dest.exists() and dest.read_bytes() != data:
                    raise ValueError("Existing primary image differs from its archive member")
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    if shutil.disk_usage(root).free < entry.file_size + reserve:
                        raise OSError("Working storage reserve reached; resume after adding space")
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    if not tmp.resolve().is_relative_to(root):
                        raise ValueError("Temporary source destination escapes asset root")
                    with tmp.open("wb") as out:
                        out.write(data)
                        out.flush()
                        os.fsync(out.fileno())
                    tmp.replace(dest)
                receipts["images"][entry.filename] = {"sha256": fingerprint, "bytes": len(data), "crc32": f"{entry.CRC:08x}", "crc32_verified": True}
                snapshot = transfer.snapshot()
                attempt.update(completed_images=len(receipts["images"]), network_bytes=snapshot["completed_range_bytes"], range_budget=snapshot)
                write_json(receipt_path, receipts)
                if len(receipts["images"]) % 100 == 0:
                    print(json.dumps({"verified_images": len(receipts["images"]), "planned_images": len(selected), "network_bytes": attempt["network_bytes"]}), flush=True)
        attempt["status"] = "COMPLETED"
    except BaseException as exc:
        attempt.update(status="INTERRUPTED_OR_FAILED", error_type=type(exc).__name__, error=str(exc)[:500])
        raise
    finally:
        snapshot = transfer.snapshot()
        attempt.update(ended_at=datetime.now(timezone.utc).isoformat(), network_bytes=snapshot["completed_range_bytes"], range_budget=snapshot)
        write_json(receipt_path, receipts)
    print(json.dumps({"completed_images": len(receipts["images"]), "network_bytes": attempt["network_bytes"], "receipt": str(receipt_path)}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets-root", type=Path, default=Path("runtime/wheat-assets"))
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--reserve-gib", type=float, default=2.0)
    parser.add_argument("--workers", type=int, choices=(1, 2, 4), default=1,
                        help="Independent bounded HTTPS readers; one serialized atomic publisher")
    args = parser.parse_args()
    if args.reserve_gib < 1.5:
        raise ValueError("Keep at least 1.5 GiB working reserve")
    with acquisition_lock(args.assets_root.resolve()) if args.download else nullcontext():
        acquire(args)


if __name__ == "__main__":
    main()
