"""Source pinning, timestamp audit and sealed split construction. No model fits."""

import csv
import io
import json
import math
import ssl
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from .api import get_case, numerical_spec_sha256
from .common import ScienceError, artifact, digest, file_hash, immutable_bytes, immutable_json, read_json, source_digests, utc_now, verify_file
from .spec import FEATURES, GENERATOR, NUMERICAL_SPEC, OCCUPANCY_URL, OCCUPANCY_ZIP_SHA256, OCCUPANCY_ZIP_URL, OFFICIAL_FILES


def csv_bytes(fields, rows):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


def _source_archive(source_zip):
    if source_zip:
        content = Path(source_zip).read_bytes()
    else:
        try:
            # Certifi is an optional trusted CA bundle, never a TLS bypass.
            try:
                import certifi
                context = ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                context = ssl.create_default_context()
            request = urllib.request.Request(OCCUPANCY_ZIP_URL, headers={"User-Agent": "Crucible authored research adapter/1.0"})
            with urllib.request.urlopen(request, context=context, timeout=40) as response:
                content = response.read(8 * 1024 * 1024 + 1)
        except (OSError, urllib.error.URLError) as exc:
            raise ScienceError("SOURCE_UNAVAILABLE", "Verified UCI download failed. Supply the pinned official archive with --source-zip; TLS verification remains enabled.", True) from exc
    if len(content) > 8 * 1024 * 1024:
        raise ScienceError("SOURCE_TOO_LARGE", "Official archive exceeds the registered size limit")
    import hashlib
    if hashlib.sha256(content).hexdigest() != OCCUPANCY_ZIP_SHA256:
        raise ScienceError("SOURCE_HASH_MISMATCH", "UCI archive differs from the preregistered official archive")
    return content


def _occupancy(root, source_zip):
    archive = _source_archive(source_zip)
    immutable_bytes(root / "source" / "occupancy.zip", archive)
    splits = {}
    audits = []
    timestamp_sets = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        if set(bundle.namelist()) != {v["name"] for v in OFFICIAL_FILES.values()}:
            raise ScienceError("SOURCE_FORMAT", "Unexpected archive members; no arbitrary archives accepted")
        for split, expected in OFFICIAL_FILES.items():
            entry = bundle.getinfo(expected["name"])
            if entry.file_size > 2 * 1024 * 1024 or entry.is_dir():
                raise ScienceError("SOURCE_FORMAT", "Unexpected official file size or directory")
            content = bundle.read(expected["name"])
            path = immutable_bytes(root / "source" / expected["name"], content)
            if file_hash(path) != expected["sha256"]:
                raise ScienceError("SOURCE_HASH_MISMATCH", f"Official file hash changed: {expected['name']}")
            reader = csv.reader(io.StringIO(content.decode("utf-8")))
            header = next(reader)
            if header != ["date", *FEATURES, "Occupancy"]:
                raise ScienceError("SOURCE_FORMAT", "Unexpected sensor columns")
            rows = []
            timestamps = []
            row_ids = set()
            for line, raw in enumerate(reader, start=2):
                if len(raw) != 8:
                    raise ScienceError("SOURCE_FORMAT", f"Unexpected row width in {expected['name']}:{line}")
                index, date, *values = raw
                moment = datetime.strptime(date, "%Y-%m-%d %H:%M:%S")
                row_id = f"{expected['name']}:{index}"
                if row_id in row_ids:
                    raise ScienceError("DUPLICATE_ROW", "Repeated official file-qualified row ID")
                row_ids.add(row_id)
                x = [float(v) for v in values[:-1]]
                if any(not math.isfinite(v) for v in x) or values[-1] not in ("0", "1"):
                    raise ScienceError("SOURCE_FORMAT", "Nonfinite sensors or nonbinary labels")
                rows.append({"row_id": row_id, "block_id": moment.date().isoformat(),
                             **dict(zip(FEATURES, x)), "target": int(values[-1])})
                timestamps.append(date)
            if len(rows) != expected["rows"] or len(set(timestamps)) != len(timestamps):
                raise ScienceError("DATA_AUDIT_FAILED", "Row count or timestamp-uniqueness audit failed")
            if timestamps != sorted(timestamps):
                raise ScienceError("DATA_AUDIT_FAILED", "Official file is not timestamp ordered")
            timestamp_sets[split] = set(timestamps)
            splits[split] = rows
            audits.append({"split": split, "name": expected["name"], "rows": len(rows),
                           "sha256": expected["sha256"], "timestamp_min": min(timestamps),
                           "timestamp_max": max(timestamps), "calendar_days": len({r["block_id"] for r in rows}),
                           "missing_values": 0, "duplicate_timestamps": 0,
                           "label_distribution": "Sealed for evaluation; not released by preparation"})
    overlap = []
    for left, right in [("train", "discovery"), ("train", "confirmation"), ("discovery", "confirmation")]:
        count = len(timestamp_sets[left] & timestamp_sets[right])
        overlap.append({"left": left, "right": right, "overlap": count})
        if count:
            raise ScienceError("SPLIT_LEAKAGE", "Official timestamp overlap detected")
    audit = {"performed_before_training": True, "files": audits,
             "cross_file_timestamp_overlap": overlap,
             "discovery_before_training": True,
             "note": "Official datatest predates datatraining. File-local original numeric row IDs repeat across files; file-qualified IDs preserve identity. Calendar days do not establish independence. Dates and IDs are never features."}
    source = {
        "title": "UCI Occupancy Detection · authored comparison",
        "url": OCCUPANCY_URL, "license": "CC BY 4.0",
        "attribution": "Candanedo, L. (2016). Occupancy Detection [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5X01N. Data licensed CC BY 4.0; https://creativecommons.org/licenses/by/4.0/.",
        "description": "Public timestamped office sensors. Crucible preserves official files, authors its own Python comparison and introduces explicitly labeled evaluation dropout; no paper-protocol reproduction or novelty claim.",
        "sha256": OCCUPANCY_ZIP_SHA256, "kind": "authored_public_data",
        "source_span": "UCI dataset documentation: three submitted training/testing files; target Occupancy; sensor variables and CC BY 4.0. The local comparison sentence is authored, not a paper quotation.",
        "files": audits, "audit": audit,
    }
    return splits, source


def _synthetic(root):
    import numpy as np
    splits, audits = {}, []
    for split, seed in GENERATOR["split_seeds"].items():
        rows = []
        children = np.random.SeedSequence(seed).spawn(GENERATOR["groups"][split])
        for group, child in enumerate(children):
            rng = np.random.default_rng(child)
            n = GENERATOR["rows_per_group"]
            x1, x2 = rng.uniform(-1, 1, (2, n))
            group_offset = rng.normal(0, 0.15)
            other = rng.normal(size=(n, 3))
            y = np.logical_xor(x1 > 0, x2 > 0)
            y = np.logical_xor(y, rng.random(n) < GENERATOR["label_noise"])
            for row in range(n):
                rows.append({
                    "row_id": f"{split}:group-{group:03d}:row-{row:03d}",
                    "block_id": f"{split}:group-{group:03d}",
                    "Temperature": float(22 + group_offset + other[row, 0]),
                    "Humidity": float(40 + 3 * group_offset + 4 * other[row, 1]),
                    "Light": float(500 * (x1[row] + 1)),
                    "CO2": float(700 + 200 * x2[row]),
                    "HumidityRatio": float(0.006 + 0.0003 * other[row, 2]),
                    "target": int(y[row]),
                })
        raw = immutable_bytes(root / "source" / f"synthetic-{split}.csv",
                              csv_bytes(["row_id", "block_id", *FEATURES, "target"], rows))
        audits.append({"name": raw.name, "split": split, "rows": len(rows),
                       "groups": len(children), "sha256": file_hash(raw),
                       "missing_values": 0, "duplicate_row_ids": 0})
        splits[split] = rows
    source = {
        "title": "Controlled nonlinear sensor groups · synthetic",
        "url": None,
        "license": "Authored synthetic data; CC0-1.0 dedication in this evidence package",
        "attribution": "Crucible authored controlled synthetic generator v1 (2026). Explicitly synthetic; no external study or paper result.",
        "description": "XOR occupancy with 5% independent label noise and independent generated groups. All numerical generator choices were fixed before the first fit.",
        "sha256": digest({"generator": GENERATOR, "files": audits}),
        "kind": "controlled_synthetic", "source_span": GENERATOR["target"],
        "files": audits,
        "audit": {"performed_before_training": True, "generator": GENERATOR,
                  "split_overlap": 0, "group_overlap": 0, "label_distribution": "Evaluation labels sealed"},
    }
    return splits, source


def load_prepared(root, check_code=True):
    root = Path(root).resolve()
    result = read_json(root / "prepared.json")
    for record in result["data_artifacts"]:
        verify_file(root, record)
    if result["numerical_spec_sha256"] != numerical_spec_sha256():
        raise ScienceError("NUMERICAL_SPEC_CHANGED", "Trusted numerical protocol differs from the prepared envelope")
    if check_code and result["trusted_code"] != source_digests():
        raise ScienceError("TRUSTED_CODE_CHANGED", "Trusted scientific source changed after preparation; prepare a fresh case before any new fit")
    split = read_json(root / "split-manifest.json")
    if digest(split) != result["manifest_sha256"]:
        raise ScienceError("MANIFEST_TAMPERED", "Split manifest digest changed")
    return result, split


def prepare_case(adapter_id, root, source_zip=None):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / "prepared.json").exists():
        prepared, _ = load_prepared(root)
        if prepared["adapter_id"] != adapter_id:
            raise ScienceError("ADAPTER_MISMATCH", "A prepared case root cannot change adapter")
        return prepared
    case = get_case(adapter_id)
    identity_path = root / "preparation-identity.json"
    if identity_path.exists():
        identity = read_json(identity_path)
        if identity["adapter_id"] != adapter_id or identity["trusted_code"] != source_digests() or identity["numerical_spec_sha256"] != numerical_spec_sha256():
            raise ScienceError("PREPARATION_IDENTITY_CHANGED", "Interrupted preparation belongs to a different adapter/source version; use a fresh root")
    else:
        identity = {"adapter_id": adapter_id, "created_at": utc_now(), "trusted_code": source_digests(),
                    "numerical_spec_sha256": numerical_spec_sha256()}
        immutable_json(identity_path, identity)
    # This precedes data parsing and all outcomes. It is part of the source chain.
    immutable_json(root / "numerical-spec.json", NUMERICAL_SPEC)
    if adapter_id == "occupancy":
        splits, source = _occupancy(root, source_zip)
    else:
        splits, source = _synthetic(root)
    split_manifest = {"schema_version": "crucible.split.v1", "adapter_id": adapter_id,
                      "numerical_spec_sha256": numerical_spec_sha256(), "features": FEATURES,
                      "splits": {}}
    data_artifacts = []
    all_ids, all_blocks = set(), set()
    for split, rows in splits.items():
        ids = [row["row_id"] for row in rows]
        if len(ids) != len(set(ids)) or all_ids.intersection(ids):
            raise ScienceError("SPLIT_LEAKAGE", "Duplicate or overlapping file-qualified row identities")
        all_ids.update(ids)
        block_ids = sorted({row["block_id"] for row in rows})
        # Calendar days may cross official training/discovery file boundaries.
        # Exact timestamps, rather than day labels, were checked for occupancy.
        if adapter_id == "synthetic" and all_blocks.intersection(block_ids):
            raise ScienceError("SPLIT_LEAKAGE", "Synthetic groups overlap")
        all_blocks.update(block_ids)
        fields = ["row_id", "block_id", *FEATURES] + (["target"] if split == "train" else [])
        clean = [{key: row[key] for key in fields} for row in rows]
        feature_path = immutable_bytes(root / "data" / f"{split}.csv", csv_bytes(fields, clean))
        labels_path = immutable_bytes(root / "sealed" / f"{split}-labels.csv",
                                      csv_bytes(["row_id", "target"], [{"row_id": r["row_id"], "target": r["target"]} for r in rows]))
        labels_path.chmod(0o600)
        feature_record = artifact(root, feature_path, "training_data" if split == "train" else "unlabeled_features")
        label_record = {**artifact(root, labels_path, "sealed_labels"), "private": True}
        data_artifacts.extend([feature_record, label_record])
        split_manifest["splits"][split] = {
            "rows": len(rows), "row_ids": ids,
            "block_ids": block_ids, "row_blocks": {r["row_id"]: r["block_id"] for r in rows},
            "features": feature_record, "labels": label_record,
        }
    (root / "sealed").chmod(0o700)
    confirmation_sha = digest(split_manifest["splits"]["confirmation"])
    split_manifest["confirmation_split_sha256"] = confirmation_sha
    source["confirmation_split_sha256"] = confirmation_sha
    source["numerical_spec_sha256"] = numerical_spec_sha256()
    source["retrieved_at"] = identity["created_at"]
    immutable_json(root / "split-manifest.json", split_manifest)
    immutable_json(root / "source-manifest.json", source)
    immutable_json(root / "trusted-code.json", source_digests())
    source_files = []
    for original in sorted(Path(__file__).parent.glob("*.py")):
        snapshot = immutable_bytes(root / "frozen_source" / "science" / original.name, original.read_bytes())
        source_files.append(artifact(root, snapshot, "trusted_source", "text/x-python"))
    data_artifacts.extend(source_files)
    for path in sorted((root / "source").iterdir()):
        if path.is_file():
            data_artifacts.append({**artifact(root, path, "original_source"), "private": True})
    for name in ["preparation-identity.json", "numerical-spec.json", "source-manifest.json", "split-manifest.json", "trusted-code.json"]:
        data_artifacts.append(artifact(root, root / name, "manifest"))
    case["contract"]["confirmation_split_sha256"] = confirmation_sha
    prepared = {
        "schema_version": "crucible.prepared.v1", "adapter_id": adapter_id,
        "source": source, "contract": case["contract"],
        "manifest_sha256": digest(split_manifest),
        "confirmation_split_sha256": confirmation_sha,
        "numerical_spec_sha256": numerical_spec_sha256(),
        "trusted_code": source_digests(), "data_artifacts": data_artifacts,
        "trusted_code_sha256": digest(source_digests()),
        "source_files": source_files, "source_snapshot_dir": "frozen_source",
        "artifacts": [record for record in data_artifacts if not record.get("private")],
        "limitations": case["limitations"],
        "created_at": identity["created_at"],
    }
    immutable_json(root / "prepared.json", prepared)
    return prepared
