"""Small audited IO primitives. Runtime artifacts are immutable and root-relative."""

import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class ScienceError(Exception):
    def __init__(self, code, message, recoverable=False):
        super().__init__(message)
        self.code, self.message, self.recoverable = code, message, recoverable

    def as_dict(self):
        return {"error": {"code": self.code, "message": self.message, "recoverable": self.recoverable}}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inside(root, relative):
    root = Path(root).resolve()
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ScienceError("UNSAFE_PATH", "Artifact paths must be relative to the case root")
    resolved = (root / rel).resolve()
    if not resolved.is_relative_to(root):
        raise ScienceError("UNSAFE_PATH", "Artifact escapes the case root")
    return resolved


def immutable_bytes(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != value:
            raise ScienceError("IMMUTABLE_CONFLICT", f"Immutable artifact changed: {path.name}")
        return path
    # Never open the published name for writing. A killed writer may leave an
    # ignored sibling temp, but cannot expose a truncated immutable object.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != value:
                raise ScienceError("IMMUTABLE_CONFLICT", f"Immutable artifact changed: {path.name}")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def immutable_json(path, value):
    return immutable_bytes(path, canonical_bytes(value) + b"\n")


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (ValueError, OSError) as exc:
        raise ScienceError("INVALID_JSON", f"Cannot read {Path(path).name}: {type(exc).__name__}") from exc


def verify_file(root, record):
    path = inside(root, record["path"])
    if not path.is_file() or file_hash(path) != record["sha256"]:
        raise ScienceError("ARTIFACT_TAMPERED", f"Hash mismatch or missing artifact: {record['path']}")
    return path


def artifact(root, path, kind="data", media_type=None):
    path = Path(path).resolve()
    rel = path.relative_to(Path(root).resolve()).as_posix()
    if media_type is None:
        media_type = "application/json" if path.suffix == ".json" else "text/csv" if path.suffix == ".csv" else "application/octet-stream"
    return {"path": rel, "name": path.name, "sha256": file_hash(path), "bytes": path.stat().st_size,
            "kind": kind, "media_type": media_type}


def source_digests():
    """Only source, no pycache or runtime. No model can supply a replacement."""
    folder = Path(__file__).parent
    return {p.name: file_hash(p) for p in sorted(folder.glob("*.py"))}


def finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ScienceError("INVALID_CONTRACT", f"{name} must be a finite number")
    return float(value)


def atomic_result(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_bytes(canonical_bytes(value) + b"\n")
    temporary.replace(path)
