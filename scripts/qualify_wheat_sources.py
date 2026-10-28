"""Retrieve pinned primary documents for the bounded source-extraction packet.

This qualifies document bytes, not the original experiment or human review.
Previously inspected excerpts remain explicitly authored packet selections.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

import httpx


PROJECT = Path(__file__).resolve().parents[1]
SOURCES = {
    "https://proceedings.mlr.press/v139/koh21a/koh21a-supp.pdf": {
        "name": "wilds-supplement.pdf",
        "download_url": "https://proceedings.mlr.press/v139/koh21a/koh21a-supp.pdf",
        "sha256": "d00f0afa5e6422270a15ccd8d07871864f8629497762a0711f6949870d8c8403",
        "bytes": 14955121,
    },
    "https://github.com/p-lambda/wilds/blob/472677590de351857197a9bf24958838c39c272b/examples/configs/datasets.py": {
        "name": "wilds-datasets.py",
        "download_url": "https://raw.githubusercontent.com/p-lambda/wilds/472677590de351857197a9bf24958838c39c272b/examples/configs/datasets.py",
        "sha256": "149f79ebde45112a96d16787cbaaf9c475a3c6fc2ea4adf2b62ec33faebf1435",
        "bytes": 18729,
    },
}


def verify(path, source):
    if path.stat().st_size != source["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
        raise ValueError("Primary source bytes differ from pinned audit: " + source["name"])


def retrieve(client, path, source):
    if path.exists():
        verify(path, source)
        return "verified_existing"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".source-", suffix=".part", delete=False) as out:
            temporary = Path(out.name)
            received = 0
            with client.stream("GET", source["download_url"]) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    received += len(chunk)
                    if received > source["bytes"]:
                        raise ValueError("Primary response exceeds audited source size")
                    out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        verify(temporary, source)
        try:
            os.link(temporary, path)
        except FileExistsError:
            verify(path, source)
        return "retrieved_and_verified"
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=PROJECT / "runtime/wheat-sources")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    packet_bytes = (PROJECT / "docs/wheat-source-packet.json").read_bytes()
    packet = json.loads(packet_bytes)
    if {s["source_id"] for s in packet["sources"]} != set(SOURCES):
        raise ValueError("Packet source inventory differs from pinned audit")
    records = []
    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "Crucible-source-audit/1.0"}) as client:
        for source in packet["sources"]:
            expected = SOURCES[source["source_id"]]
            if source["sha256"] != expected["sha256"] or source["bytes"] != expected["bytes"]:
                raise ValueError("Packet source identity differs from pinned audit")
            result = retrieve(client, args.output / expected["name"], expected)
            records.append({**expected, "status": result})
    # The code excerpt has an exact line-addressed correspondence. PDF excerpts
    # were selected from the rendered primary page; do not claim a fresh OCR run.
    config = (args.output / "wilds-datasets.py").read_text().splitlines()
    code_source = next(s for s in packet["sources"] if s["kind"] == "pinned_current_repository_defaults")
    if code_source["excerpt"] != "\n".join(config[n - 1].strip() for n in (442, 443, 444)):
        raise ValueError("Code excerpt differs from pinned source lines")
    target = args.output / "extraction-packet.json"
    if target.exists() and target.read_bytes() != packet_bytes:
        raise ValueError("Existing source packet differs; retain and review it before changing versions")
    target.write_bytes(packet_bytes)
    report = {"packet_sha256": hashlib.sha256(packet_bytes).hexdigest(), "sources": records,
              "code_excerpt_verified": True, "pdf_excerpts": "Previously selected from inspected rendered page; source PDF bytes verified",
              "scientific_result": False, "independent_human_review": False}
    (args.output / "packet-qualification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
