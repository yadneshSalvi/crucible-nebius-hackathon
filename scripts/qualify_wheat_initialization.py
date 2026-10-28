"""Audit/download one official initialization after the source contract freezes.

No arbitrary checkpoint URL is accepted. The manifest pins the actual full SHA256
before fitting; the filename prefix is independently checked against TorchVision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime, timezone
import urllib.request
import uuid

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
URL = "https://download.pytorch.org/models/resnet50-0676ba61.pth"
NAME = "ResNet50_Weights.IMAGENET1K_V1"
EXPECTED_SHA256 = "0676ba61b6795bbe1773cffd859882e5e297624d384b6993f7c9e683e722fb8a"
MAX_BYTES = 160 * 1024 * 1024
RESERVE = 1536 * 1024 * 1024


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets-root", type=Path, default=PROJECT / "runtime/wheat-assets")
    parser.add_argument("--case-root", type=Path, default=PROJECT / "runtime/cases/wheat-resolution-v1")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--source-only", action="store_true", help="Qualify official source bytes before corpus preparation; never authorizes fitting")
    args = parser.parse_args()
    root = args.assets_root.resolve()
    if not args.download:
        print(json.dumps({"name": NAME, "url": URL, "downloaded": False,
            "requires": "Complete audited corpus preparation and at least 160 MiB plus 1.5 GiB free reserve",
            "rights": "TorchVision code license and pretrained weight/source-data terms are distinct"}, indent=2))
        return
    from science.wheat import SPEC, TRAINING, load
    from science.common import digest
    from torchvision.models import ResNet50_Weights
    if args.source_only:
        packet_sha = hashlib.sha256((PROJECT / "docs/wheat-source-packet.json").read_bytes()).hexdigest()
        if packet_sha != "95930c9ac197c21dbd6f62326954c706630c4bbba82deec7fc19dcda51ba84a4":
            raise ValueError("Source-only qualification requires the reviewed primary packet")
        prepared = {"manifest_sha256": None, "numerical_spec_sha256": digest(SPEC)}
    else:
        prepared, _ = load(args.case_root)
    if TRAINING["initialization"] != NAME or ResNet50_Weights.IMAGENET1K_V1.url != URL:
        raise ValueError("The frozen protocol or installed official weights identity changed")
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "initialization.json"
    target = root / "resnet50-0676ba61.pth"
    if manifest.exists():
        existing = json.loads(manifest.read_text())
        with target.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if existing.get("sha256") != actual or actual != EXPECTED_SHA256 or existing.get("source_url") != URL or existing.get("name") != NAME:
            raise ValueError("Retained initialization manifest or checkpoint changed")
        print(json.dumps({"status": "verified_existing", "sha256": actual, "manifest": str(manifest)}))
        return
    if target.exists():
        raise ValueError("Unregistered checkpoint already exists; inspect it rather than silently adopting it")
    if shutil.disk_usage(root).free < MAX_BYTES + RESERVE:
        raise OSError("Initialization storage gate: preserve the working reserve; no download started")
    ident = uuid.uuid4().hex
    receipt_path = root / ("initialization-attempt-" + ident + ".json")
    partial = root / ("initialization-" + ident + ".partial")
    receipt = {"id": ident, "name": NAME, "source_url": URL, "status": "started",
        "started_at": datetime.now(timezone.utc).isoformat(), "bytes": 0,
        "scope": "source_bytes_only; full corpus and preparation still required before fitting" if args.source_only else "source_bytes_for_prepared_corpus",
        "prepared_manifest_sha256": prepared["manifest_sha256"], "numerical_spec_sha256": prepared["numerical_spec_sha256"]}
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    try:
        # No credentials are used. TLS remains verified; unexpected redirects
        # fail closed rather than silently fetching another checkpoint.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        request = urllib.request.Request(URL, headers={"User-Agent": "Crucible-initialization-audit/1.0"})
        checksum = hashlib.sha256()
        with opener.open(request, timeout=60) as response, partial.open("xb") as output:
            if response.status != 200:
                raise ValueError("Official initialization download did not return HTTP200")
            while chunk := response.read(1024 * 1024):
                receipt["bytes"] += len(chunk)
                if receipt["bytes"] > MAX_BYTES or shutil.disk_usage(root).free < len(chunk) + RESERVE:
                    raise OSError("Initialization byte/storage limit reached; partial attempt retained")
                output.write(chunk)
                checksum.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        sha = checksum.hexdigest()
        if sha != EXPECTED_SHA256:
            raise ValueError("Official checkpoint does not match the independently retained full SHA256")
        import torch
        tensors = torch.load(partial, map_location="cpu", weights_only=True)
        if tuple(tensors["conv1.weight"].shape) != (64, 3, 7, 7) or tuple(tensors["fc.weight"].shape) != (1000, 2048):
            raise ValueError("Official initialization tensor shapes differ from ResNet-50 ImageNet1K")
        if not all(isinstance(tensor, torch.Tensor) and torch.isfinite(tensor).all().item() for tensor in tensors.values()):
            raise ValueError("Official initialization contains invalid or non-finite tensors")
        receipt.update(weights_only_load=True, tensors=len(tensors), tensor_values_finite=True)
        partial.rename(target)
        target.chmod(0o444)
        value = {"name": NAME, "path": target.name, "sha256": sha, "bytes": receipt["bytes"], "source_url": URL,
                 "license": "TorchVision BSD-3-Clause code; pretrained weights and ImageNet source-data terms remain separately attributed, with no separate weight-specific license asserted",
                 "license_source": "https://github.com/pytorch/vision/blob/v0.29.2/LICENSE",
                 "qualification_receipt": receipt_path.name, "preparation_manifest_sha256": prepared["manifest_sha256"]}
        value["qualification_scope"] = receipt["scope"]
        with manifest.open("x") as output:
            json.dump(value, output, indent=2)
            output.write("\n")
        receipt.update(status="succeeded", sha256=sha)
        print(json.dumps({"status": "qualified", "sha256": sha, "bytes": receipt["bytes"], "manifest": str(manifest)}))
    except BaseException as exc:
        receipt.update(status="failed", error_type=type(exc).__name__, error=str(exc)[:1000])
        raise
    finally:
        receipt["ended_at"] = datetime.now(timezone.utc).isoformat()
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
