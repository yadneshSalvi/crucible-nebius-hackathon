"""Lossless float64 transformed boxes and NMS references; no pickle or torch."""
import os
from pathlib import Path
from .common import ScienceError, file_hash, immutable_json, inside, read_json


class PredictionWriter:
    def __init__(self):
        self.records, self.raw, self.selected, self.final = [], [], [], []
        self.raw_count, self.selected_count = 0, 0

    def add(self, row):
        import numpy as np
        raw = row["raw_predictions"]
        lookup = {(*p["box"], p["score"]): self.raw_count + i for i, p in enumerate(raw)}
        selected = []
        for prediction in row["boxes"]:
            index = lookup.get((*prediction["box"], prediction["score"]))
            if index is None:
                index = next((self.raw_count + i for i, p in enumerate(raw) if abs(p["score"] - prediction["score"]) <= 1e-6 and all(abs(a-b) <= 1e-4 for a,b in zip(p["box"], prediction["box"]))), None)
            if index is None:
                raise ScienceError("BOX_STORAGE_LINEAGE", "NMS output lacks a raw witness at the fixed lineage tolerance")
            selected.append(index)
        self.raw.append(np.asarray([[*p["box"], p["score"], p["call"]] for p in raw], dtype=np.float64).reshape(-1, 6))
        self.selected.append(np.asarray(selected, dtype=np.uint32))
        self.final.append(np.asarray([[*p["box"], p["score"]] for p in row["boxes"]], dtype=np.float64).reshape(-1, 5))
        self.records.append({**{k: v for k, v in row.items() if k not in ("raw_predictions", "boxes")},
            "raw_slice": [self.raw_count, len(raw)], "selected_slice": [self.selected_count, len(selected)]})
        self.raw_count += len(raw)
        self.selected_count += len(selected)

    def publish(self, output):
        import numpy as np
        from .wheat import ensure_free_space
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        arrays = {"raw": np.concatenate(self.raw) if self.raw else np.empty((0, 6), dtype=np.float64),
                  "selected": np.concatenate(self.selected) if self.selected else np.empty(0, dtype=np.uint32),
                  "final": np.concatenate(self.final) if self.final else np.empty((0, 5), dtype=np.float64)}
        ensure_free_space(output, sum(a.nbytes for a in arrays.values()) + 16 * 1024**2, "prediction publication")
        temporary = output / ".boxes.tmp.npz"
        np.savez_compressed(temporary, **arrays)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        path = output / "boxes.npz"
        if path.exists():
            raise ScienceError("IMMUTABLE_CONFLICT", "Numeric predictions already exist")
        os.replace(temporary, path)
        return immutable_json(output / "predictions.json", {"schema_version": "crucible.wheat.box-arrays.v1",
            "arrays": {"path": "boxes.npz", "sha256": file_hash(path), "bytes": path.stat().st_size},
            "records": self.records, "raw_count": self.raw_count, "selected_count": self.selected_count,
            "representation": "float64 raw and actual SAHI-merged coordinates/scores, uint32 raw witnesses at existing1e-4 lineage tolerance; no added rounding"})


def prediction_rows(root, index_path, depth=0):
    root, index_path = Path(root).resolve(), Path(index_path).resolve()
    if depth > 2 or not index_path.is_relative_to(root):
        raise ScienceError("PREDICTION_SCHEMA", "Prediction index nesting/path is outside authored structure")
    value = read_json(index_path)
    if isinstance(value, list):
        yield from value
        return
    if value.get("schema_version") == "crucible.wheat.seed-index.v1":
        for entry in value["seed_predictions"]:
            path = inside(root, (index_path.parent / entry["path"]).relative_to(root).as_posix())
            if file_hash(path) != entry["sha256"]:
                raise ScienceError("ARTIFACT_TAMPERED", "Seed prediction index changed")
            yield from prediction_rows(root, path, depth + 1)
        return
    if value.get("schema_version") != "crucible.wheat.box-arrays.v1" or Path(value["arrays"]["path"]).name != value["arrays"]["path"]:
        raise ScienceError("PREDICTION_SCHEMA", "Unknown numeric prediction schema/path")
    path = index_path.parent / value["arrays"]["path"]
    if file_hash(path) != value["arrays"]["sha256"]:
        raise ScienceError("ARTIFACT_TAMPERED", "Numeric predictions changed")
    import numpy as np
    try:
        with np.load(path, allow_pickle=False) as archive:
            if set(archive.files) != {"raw", "selected", "final"}:
                raise ScienceError("PREDICTION_SCHEMA", "Unexpected numeric archive members")
            raw, selected, final = archive["raw"], archive["selected"], archive["final"]
    except (ValueError, OSError) as exc:
        raise ScienceError("PREDICTION_SCHEMA", "Numeric predictions must be non-pickle arrays") from exc
    if raw.dtype != np.float64 or selected.dtype != np.uint32 or final.dtype != np.float64 or raw.shape != (value["raw_count"], 6) or selected.shape != (value["selected_count"],) or final.shape != (value["selected_count"], 5):
        raise ScienceError("PREDICTION_SCHEMA", "Numeric prediction types/shapes changed")
    cursor, final_cursor = 0, 0
    for record in value["records"]:
        start, count = record["raw_slice"]
        final_start, final_count = record["selected_slice"]
        if start != cursor or final_start != final_cursor or count < 0 or final_count < 0 or start + count > len(raw) or final_start + final_count > len(selected):
            raise ScienceError("PREDICTION_SCHEMA", "Numeric record slices must be contiguous and in bounds")
        cursor += count
        final_cursor += final_count
        members = []
        for values in raw[start:start + count].tolist():
            if not values[5].is_integer():
                raise ScienceError("PREDICTION_SCHEMA", "Forward call index must be integral")
            members.append({"box": values[:4], "score": values[4], "call": int(values[5])})
        boxes = []
        for position, index in enumerate(selected[final_start:final_start + final_count].tolist()):
            if not start <= index < start + count:
                raise ScienceError("COORDINATE_LINEAGE", "NMS reference escaped its image/recipe/seed")
            member = members[index - start]
            values = final[final_start + position].tolist()
            if abs(values[4] - member["score"]) > 1e-6 or any(abs(a-b) > 1e-4 for a,b in zip(values[:4], member["box"])):
                raise ScienceError("COORDINATE_LINEAGE", "NMS witness changed beyond fixed lineage tolerance")
            boxes.append({"box": values[:4], "score": values[4]})
        yield {**{k: v for k, v in record.items() if k not in ("raw_slice", "selected_slice")}, "raw_predictions": members, "boxes": boxes}
    if cursor != len(raw) or final_cursor != len(selected):
        raise ScienceError("PREDICTION_SCHEMA", "Unreferenced numeric predictions remain")
