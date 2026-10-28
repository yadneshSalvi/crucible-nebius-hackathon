"""Inspect the primary GWHD ZIP through bounded, verified HTTP byte ranges.

No validation/test labels or images are opened by default. This is asset
qualification, not a downloaded full-archive checksum or WILDS split claim.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

import httpx

RECORD_URL = "https://zenodo.org/api/records/5092309"


class RemoteZip(io.RawIOBase):
    def __init__(self, client, url, size, budget=64 * 1024 * 1024):
        self.client, self.url, self.size = client, url, size
        self.position, self.received, self.budget = 0, 0, budget
        self.requests = []

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        pos = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        if not 0 <= pos <= self.size:
            raise ValueError("Out-of-bounds archive seek")
        self.position = pos
        return pos

    def read(self, count=-1):
        count = self.size - self.position if count < 0 else min(count, self.size - self.position)
        if count == 0:
            return b""
        if count > 32 * 1024 * 1024 or self.received + count > self.budget:
            raise ValueError("Bounded metadata/image retrieval budget exceeded")
        start, end = self.position, self.position + count - 1
        with self.client.stream("GET", self.url, headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"}) as response:
            response.raise_for_status()
            if response.status_code != 206 or response.headers.get("content-range") != f"bytes {start}-{end}/{self.size}":
                raise ValueError("Server did not honor exact byte range; refusing full download")
            chunks, got = [], 0
            for chunk in response.iter_bytes():
                got += len(chunk)
                if got > count:
                    raise ValueError("Response exceeded requested byte range")
                chunks.append(chunk)
            data = b"".join(chunks)
        if len(data) != count:
            raise ValueError("Truncated archive byte range")
        self.requests.append({"start": start, "end": end, "bytes": count})
        self.received += count
        self.position += count
        return data

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("runtime/wheat-assets"))
    parser.add_argument("--member", action="append", default=[], help="Exact discovered member; only training/metadata/rights files initially")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Crucible-source-audit/1.0"}) as client:
        response = client.get(RECORD_URL)
        response.raise_for_status()
        record = response.json()
        files = [f for f in record["files"] if f["key"] == "gwhd_2021.zip"]
        if len(files) != 1:
            raise ValueError("Unexpected primary archive inventory")
        archive = files[0]
        remote = RemoteZip(client, archive["links"]["self"], archive["size"])
        with zipfile.ZipFile(remote) as zf:
            entries = zf.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise ValueError("Duplicate archive member identity")
            metadata = [e for e in entries if not e.is_dir() and Path(e.filename).suffix.lower() not in {".png", ".jpg", ".jpeg"}]
            manifest = {"record_url": RECORD_URL, "archive": {"name": archive["key"], "size": archive["size"], "published_checksum": archive["checksum"], "download_url": archive["links"]["self"]}, "license_metadata": record.get("metadata", {}).get("license"), "entries": len(entries), "image_entries": sum(Path(e.filename).suffix.lower() in {".png", ".jpg", ".jpeg"} for e in entries), "metadata_members": [{"name": e.filename, "uncompressed_bytes": e.file_size, "compressed_bytes": e.compress_size, "crc32": f"{e.CRC:08x}"} for e in metadata], "retrieved": [], "limits": ["Range-inspected ZIP directory; full archive checksum has not been verified", "No scientific result or WILDS split equivalence established", "No validation/test member is opened by the default inspection"]}
            for name in args.member:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or "\\" in name or re.search(r"(^|[/_.-])(test|val|valid|validation)([/_.-]|$)", name, re.I):
                    raise ValueError("Unsafe or unreleased validation/test member")
                entry = zf.getinfo(name)
                if entry.file_size > 32 * 1024 * 1024 or entry.is_dir():
                    raise ValueError("Member exceeds inspection size limit")
                data = zf.read(name)  # zipfile verifies each member's CRC.
                dest = args.output / "primary" / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists() and dest.read_bytes() != data:
                    raise ValueError("An existing immutable source member changed")
                dest.write_bytes(data)
                manifest["retrieved"].append({"member": name, "path": str(dest), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "crc32_verified": True})
        manifest["network_bytes"] = remote.received
        manifest["ranges"] = remote.requests
        fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:16]
        output = args.output / ("archive-inspection-" + fingerprint + ".json")
        output.write_text(json.dumps(manifest, indent=2) + "\n")
        print(json.dumps({"manifest": str(output), **{k: manifest[k] for k in ("archive", "license_metadata", "entries", "image_entries", "metadata_members", "retrieved", "network_bytes")}}, indent=2))


if __name__ == "__main__":
    main()
