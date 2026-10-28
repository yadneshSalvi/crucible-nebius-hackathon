"""Bind primary GWHD records to fixed site roles without running a detector.

Trusted ingestion can normalize public labels but prints no final-role labels.
A usable manifest is emitted only after every planned image is present and
pixel/coordinate checks complete. The incomplete catalog never permits fitting.
"""
from __future__ import annotations

import argparse
import collections
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

TRAIN_CSV_SHA256 = "1af1d8e386643afe8cd1b41d89ca2634d3212908bdbe58a9d7cd5b32e4048176"
METADATA_SHA256 = "1fb0a498a4a2d3fff2424b65ecbc41f0ca10d5fc26137b09ffc42c8f3f92d49a"
FINAL = {"NMBU_1", "NMBU_2", "ULiège-GxABT_1"}
ILLUSTRATION = "0077c64686e9712d9b8efcd930ce5b0d68c72d8fb50ee99ed01ff2fd73e6d1d2"
SOURCE_PROVENANCE = {
    "record_url": "https://zenodo.org/records/5092309",
    "archive_member_origin": "gwhd_2021.zip",
    "archive_published_md5": "22b4b542c9ae7e056d7fcdeae9ecaed5",
    "full_archive_checksum_verified": False,
    "attribution": "Etienne David and the Global Wheat Head Dataset 2021 contributors; acquisition-session identities retained",
    "license_status": "Different statements in the primary record and WILDS distribution description; both retained",
    "license_statements": [
        {"value": "CC BY 4.0", "source": "https://zenodo.org/api/records/5092309", "license_url": "https://creativecommons.org/licenses/by/4.0/"},
        {"value": "MIT", "source": "https://wilds.stanford.edu/datasets/#globalwheat"},
    ],
    "annotation_source": {"member": "gwhd_2021/competition_train.csv", "sha256": TRAIN_CSV_SHA256},
    "metadata_source": {"member": "gwhd_2021/metadata_dataset.csv", "sha256": METADATA_SHA256},
    "modifications": "Authored session/site partitions; conflicting source IDs quarantined; metadata correction recorded; source xyxy annotations normalized to xywh; original PNG bytes retained",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def immutable(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Immutable source catalog object changed: {path.name}")
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".catalog-", delete=False) as out:
            temporary = Path(out.name)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError(f"Immutable source catalog object changed: {path.name}")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def publish_pending(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    temporary.replace(path)


def parse_boxes(value):
    if value == "no_box":
        return []
    boxes = []
    for group in value.split(";"):
        parts = group.split()
        if len(parts) != 4:
            raise ValueError("Invalid author box encoding")
        x1, y1, x2, y2 = map(float, parts)
        if not all(math.isfinite(v) for v in (x1, y1, x2, y2)) or not (0 <= x1 < x2 <= 1024 and 0 <= y1 < y2 <= 1024):
            raise ValueError("Invalid author coordinates; no silent clipping or empty substitution")
        boxes.append([x1, y1, x2 - x1, y2 - y1])
    return boxes


def select_illustration(root, rows):
    candidates = sorted(row["image_name"] for row in rows if row["domain"] == "Rres_1")
    if not candidates or candidates[0] != ILLUSTRATION + ".png":
        raise ValueError("The fixed source-only illustration identity changed")
    expected = {"source_csv_sha256": TRAIN_CSV_SHA256, "source_split": "competition_train",
                "selection_rule": "Lexicographically first image_name within the predefined development session Rres_1",
                "session_id": "Rres_1", "image_id": candidates[0], "detector_outcomes_seen": False,
                "scope": "Authored public-data discovery illustration; never final evaluation"}
    path = root / "illustration-selection.json"
    if path.exists():
        retained = json.loads(path.read_bytes())
        if any(retained.get(key) != value for key, value in expected.items()) or not retained.get("selected_at"):
            raise ValueError("The retained illustration selection differs from the source-only rule")
        return  # Preserve the original timestamp and exact receipt bytes.
    immutable(path, encoded({**expected, "selected_at": datetime.now(timezone.utc).isoformat()}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets-root", type=Path, default=Path("runtime/wheat-assets"))
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    root = args.assets_root.resolve()
    primary = root / "primary/gwhd_2021"
    csv_data = (primary / "competition_train.csv").read_bytes()
    metadata_data = (primary / "metadata_dataset.csv").read_bytes()
    if sha(csv_data) != TRAIN_CSV_SHA256 or sha(metadata_data) != METADATA_SHA256:
        raise ValueError("Primary annotation or metadata identity differs from audited bytes")
    raw_rows = sorted(csv.DictReader(csv_data.decode().splitlines()), key=lambda r: r["image_name"])
    if len(raw_rows) != 3657:
        raise ValueError("Unexpected primary record coverage")
    by_filename = collections.defaultdict(list)
    for row in raw_rows:
        by_filename[row["image_name"]].append(row)
    # Every source occurrence of an ambiguous ID is retained in the audit and
    # excluded. Never choose one source annotation or site to improve a result.
    ambiguous = [{"image_id": Path(name).stem, "reason": "Repeated source filename with ambiguous session/annotation identity", "occurrences": [{"session_id": r["domain"], "annotation_encoding_sha256": sha(r["BoxesString"].encode())} for r in group]} for name, group in by_filename.items() if len(group) > 1]
    rows = [group[0] for group in by_filename.values() if len(group) == 1]
    if len(rows) != 3653 or len(ambiguous) != 2:
        raise ValueError("Primary ambiguity audit differs from reviewed source")
    # Select from source identities before any image/annotation processing. No
    # detector output participates; a fresh checkout can reproduce this choice.
    select_illustration(root, rows)
    meta = {r["name"].casefold(): r for r in csv.DictReader(metadata_data.decode().splitlines(), delimiter=";")}
    roles, catalog = [], []
    for row in rows:
        filename, session = row["image_name"], row["domain"]
        if Path(filename).name != filename or Path(filename).suffix != ".png":
            raise ValueError("Unsafe primary image name")
        m = meta[session.casefold()]
        location = "Eschikon" if session == "ETHZ_1" else m["location"]
        role = "final" if session in FINAL else "discovery" if session == "Rres_1" else "train"
        if role == "train" and m["country"] not in {"France", "Switzerland"}:
            raise ValueError("Unreviewed training country")
        image_id = Path(filename).stem
        group_id = m["country"] + "/" + location
        roles.append({"image_id": image_id, "source_filename": filename, "session_id": session, "group_id": group_id, "role": role})
    plan = {"format": "crucible.wheat-role-plan/v1", "source_csv_sha256": TRAIN_CSV_SHA256, "metadata_sha256": METADATA_SHA256, "selection": "All unambiguous competition_train records, predefined session/site roles, no outcome selection", "source_rows": len(raw_rows), "ambiguous_source_id_quarantine": ambiguous, "images": roles, "illustration_image_id": ILLUSTRATION, "duplicate_rule": "Quarantine every ambiguous source ID occurrence and every member of exact decoded-pixel duplicate groups spanning roles, before fitting", "metadata_corrections": [{"session_id": "ETHZ_1", "field": "location", "raw": "Usask", "reviewed": "Eschikon", "source": "WILDS supplement Table11, PDFpage27/printed26"}], "limits": ["Authored new split of public competition training data; not official WILDS", "No independent custodian, practitioner requirement or fresh data", "Two final sites support descriptive finite-corpus results, not sampling CIs", "Exact hashes cannot establish absence of all near duplicates or overlapping plots"]}
    immutable(root / "role-plan.json", encoded(plan))
    missing = []
    for row, role_row in zip(rows, roles):
        image_id = role_row["image_id"]
        # Values are not logged or supplied to adaptive planners. Each role has
        # a separate target path so the runtime can enforce its release boundary.
        annotation = {"image_id": image_id, "bbox_format": "xywh", "boxes": parse_boxes(row["BoxesString"]), "source_format": "xyxy", "source_csv_sha256": TRAIN_CSV_SHA256}
        ann_path = root / "annotations" / role_row["role"] / (image_id + ".json")
        ann_bytes = encoded(annotation)
        immutable(ann_path, ann_bytes)
        path = primary / "images" / row["image_name"]
        image = {**role_row, "path": str(path), "annotation_path": str(ann_path), "annotation_sha256": sha(ann_bytes), "bbox_format": "xywh", "width": 1024, "height": 1024, "dimensions_verified": False, "sha256": None, "pixel_sha256": None}
        if path.exists():
            from PIL import Image
            data = path.read_bytes()
            with Image.open(path) as im:
                if im.size != (1024, 1024) or im.mode != "RGB":
                    raise ValueError("Unexpected primary image dimensions or color mode")
                # Match the trusted detector/oracle identity: raw decoded RGB
                # bytes; mode and fixed dimensions are validated immediately above.
                image.update(sha256=sha(data), pixel_sha256=sha(im.tobytes()), dimensions_verified=True)
        else:
            missing.append(image_id)
        catalog.append(image)
    groups = collections.defaultdict(list)
    for image in catalog:
        if image["pixel_sha256"]:
            groups[image["pixel_sha256"]].append(image)
    quarantined = [g for g in groups.values() if len({i["role"] for i in g}) > 1]
    excluded_ids = {i["image_id"] for g in quarantined for i in g}
    output = {"format": "crucible.wheat-asset-catalog/v1", "prepared": not missing, "role_plan_sha256": sha(encoded(plan)), "images": catalog, "missing_images": missing, "quarantined_cross_role_duplicate_groups": [[i["image_id"] for i in g] for g in quarantined], "illustration_image_id": ILLUSTRATION, "limits": plan["limits"]}
    output["source_provenance"] = SOURCE_PROVENANCE
    output["source_selection_audit"] = {key: plan[key] for key in (
        "selection", "source_rows", "ambiguous_source_id_quarantine", "duplicate_rule", "metadata_corrections")}
    publish_pending(root / "catalog.pending.json", encoded(output))
    if args.finalize:
        if missing:
            raise ValueError(f"Cannot finalize: {len(missing)} planned images are missing")
        if ILLUSTRATION in excluded_ids:
            raise ValueError("The preselected illustration is quarantined; require an explicit source-only replacement rule")
        manifest = {**output, "format": "crucible.wheat-assets/v1", "images": [i for i in catalog if i["image_id"] not in excluded_ids]}
        data = encoded(manifest)
        immutable(root / ("manifest-" + sha(data)[:20] + ".json"), data)
        immutable(root / "manifest.json", data)
    print(json.dumps({"planned_records": len(catalog), "planned_roles": dict(collections.Counter(i["role"] for i in catalog)), "available_images": len(catalog) - len(missing), "missing_images": len(missing), "cross_role_duplicate_groups": len(quarantined), "finalized": bool(args.finalize), "catalog": str(root / "catalog.pending.json")}, indent=2))


if __name__ == "__main__":
    main()
