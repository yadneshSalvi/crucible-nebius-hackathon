"""Retrieve the entire predefined source cohort without a second full ZIP copy.

Default mode is an asset/disk audit. --download requires enough space for every
missing image plus the declared working reserve. It never narrows the cohort.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import zipfile

import httpx

from qualify_wheat_assets import RECORD_URL, RemoteZip


def write_json(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as out:
        json.dump(value, out, indent=2)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets-root", type=Path, default=Path("runtime/wheat-assets"))
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--reserve-gib", type=float, default=2.0)
    args = parser.parse_args()
    if args.reserve_gib < 1.5:
        raise ValueError("Keep at least 1.5 GiB working reserve")
    root = args.assets_root.resolve()
    plan_bytes = (root / "role-plan.json").read_bytes()
    plan = json.loads(plan_bytes)
    plan_sha = hashlib.sha256(plan_bytes).hexdigest()
    reserve = int(args.reserve_gib * 1024 ** 3)
    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "Crucible-source-audit/1.0"}) as client:
        response = client.get(RECORD_URL)
        response.raise_for_status()
        record = response.json()
        archive = next(f for f in record["files"] if f["key"] == "gwhd_2021.zip")
        if archive["size"] != 10215190132 or archive["checksum"] != "md5:22b4b542c9ae7e056d7fcdeae9ecaed5":
            raise ValueError("Primary archive version differs from the audited source")
        reader = RemoteZip(client, archive["links"]["self"], archive["size"], budget=archive["size"] * 2)
        # Bounded read-ahead reduces per-member HTTP requests. ZipFile reads
        # members in archive order, sharing this buffer; no whole ZIP is saved.
        buffered = io.BufferedReader(reader, buffer_size=8 * 1024 * 1024)
        with zipfile.ZipFile(buffered) as zf:
            entries = {e.filename: e for e in zf.infolist()}
            selected = []
            for image in plan["images"]:
                filename = image["source_filename"]
                if Path(filename).name != filename or Path(filename).suffix != ".png":
                    raise ValueError("Unsafe source filename")
                entry = entries["gwhd_2021/images/" + filename]
                if entry.file_size > 16 * 1024 * 1024 or entry.is_dir():
                    raise ValueError("Unexpected primary image size/type")
                selected.append(entry)
            selected.sort(key=lambda e: e.header_offset)
            missing = [e for e in selected if not (root / "primary" / e.filename).exists()]
            remaining = sum(e.file_size for e in missing)
            free = shutil.disk_usage(root).free
            status = {"format": "crucible.wheat-download/v1", "role_plan_sha256": plan_sha, "planned_images": len(selected), "missing_images": len(missing), "missing_image_bytes": remaining, "required_free_bytes": remaining + reserve, "available_free_bytes": free, "reserve_bytes": reserve, "download_requested": args.download, "full_archive_checksum_verified": False, "started_at": datetime.now(timezone.utc).isoformat()}
            print(json.dumps(status, indent=2), flush=True)
            if not args.download:
                return
            if free < remaining + reserve:
                raise SystemExit("Storage gate: full cohort plus working reserve does not fit; no image downloaded")
            receipt_path = root / "download-progress.json"
            receipts = json.loads(receipt_path.read_text()) if receipt_path.exists() else {"role_plan_sha256": plan_sha, "images": {}, "attempts": []}
            if receipts["role_plan_sha256"] != plan_sha:
                raise ValueError("Cannot resume a different source role plan")
            attempt = {**status, "status": "RUNNING"}
            receipts["attempts"].append(attempt)
            write_json(receipt_path, receipts)
            try:
                for index, entry in enumerate(selected):
                    dest = root / "primary" / entry.filename
                    if not dest.resolve().is_relative_to(root):
                        raise ValueError("Source destination escapes asset root")
                    previous = receipts["images"].get(entry.filename)
                    if dest.exists() and previous:
                        if hashlib.sha256(dest.read_bytes()).hexdigest() != previous["sha256"]:
                            raise ValueError("Previously pinned source image changed")
                        continue
                    if not dest.exists() and shutil.disk_usage(root).free < entry.file_size + reserve:
                        raise OSError("Working storage reserve reached; resume after adding space")
                    data = zf.read(entry)  # CRC verified by ZipFile before write.
                    fingerprint = hashlib.sha256(data).hexdigest()
                    if dest.exists() and dest.read_bytes() != data:
                        raise ValueError("Existing primary image differs from its archive member")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if not dest.exists():
                        tmp = dest.with_suffix(dest.suffix + ".part")
                        with tmp.open("wb") as out:
                            out.write(data)
                            out.flush()
                            os.fsync(out.fileno())
                        tmp.replace(dest)
                    receipts["images"][entry.filename] = {"sha256": fingerprint, "bytes": len(data), "crc32": f"{entry.CRC:08x}", "crc32_verified": True}
                    attempt.update(completed_images=len(receipts["images"]), network_bytes=reader.received)
                    write_json(receipt_path, receipts)
                    if (index + 1) % 100 == 0:
                        print(json.dumps({"verified_images": len(receipts["images"]), "planned_images": len(selected), "network_bytes": reader.received}), flush=True)
                attempt["status"] = "COMPLETED"
            except BaseException as exc:
                attempt.update(status="INTERRUPTED_OR_FAILED", error_type=type(exc).__name__, error=str(exc)[:500])
                raise
            finally:
                attempt.update(ended_at=datetime.now(timezone.utc).isoformat(), network_bytes=reader.received)
                write_json(receipt_path, receipts)
            print(json.dumps({"completed_images": len(receipts["images"]), "network_bytes": reader.received, "receipt": str(receipt_path)}), flush=True)


if __name__ == "__main__":
    main()
