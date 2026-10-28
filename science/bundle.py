"""Allowlisted portable offline evidence, released only after verification."""

import hashlib
import io
import zipfile
from pathlib import Path

from .api import contract_signature
from .common import ScienceError, artifact, canonical_bytes, digest, immutable_bytes, read_json, utc_now
from .orchestrate import _context

REPLAY_SCRIPT = '''#!/usr/bin/env python3
"""Verify exported bytes and replay a fixed trusted plan, without inference."""
import argparse, hashlib, json, subprocess, sys
from pathlib import Path
root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--verify-only", action="store_true")
args = parser.parse_args()
manifest = json.loads((root / "manifest.json").read_text())
for name, sha in manifest["files"].items():
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise SystemExit("INTEGRITY FAILURE: " + name)
print("All exported bytes verified.")
if args.verify_only:
    raise SystemExit(0)
request = json.loads((root / "replay-request.json").read_text())
request["root"] = str(root / "case")
request_path = root / "local-replay-request.json"
request_path.write_text(json.dumps(request))
for stage in ("rerun", "reverify"):
    subprocess.run([sys.executable, "-m", "science.cli", stage, "--input", str(request_path), "--output", str(root / (stage + "-result.json"))], cwd=root, check=True)
print("Actual retraining and separate-process metric re-verification agree. This is a replay, not fresh confirmation.")
'''


def export_case(request):
    root, prepared, split, contract = _context(request)
    final_path = root / "confirmation-verification.json"
    if not final_path.exists() or read_json(final_path)["verification"]["status"] != "verified":
        raise ScienceError("VERIFICATION_REQUIRED", "Export releases heldout labels only after registered verification")
    frozen = root / "frozen_source" / "science"
    files = {}
    for path in sorted(frozen.glob("*.py")):
        files[f"science/{path.name}"] = path.read_bytes()
    if not files:
        raise ScienceError("SOURCE_SNAPSHOT_MISSING", "Cannot export without exact frozen trusted source")
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if "export" in relative.parts or any(part.startswith(".") for part in relative.parts):
            continue
        if path.suffix not in [".csv", ".json", ".txt", ".zip"] and not (relative.parts[0] == "frozen_source" and path.suffix == ".py"):
            continue
        if path.stat().st_size > 40 * 1024 * 1024:
            raise ScienceError("EXPORT_TOO_LARGE", "A scientific artifact exceeded the registered export limit")
        files[f"case/{relative.as_posix()}"] = path.read_bytes()
    replay = {key: request[key] for key in ["contract", "registration", "reproduction_accepted"] if key in request}
    replay["active_conditions"] = request.get("active_conditions", contract["active_conditions"])
    replay["root"] = "case"
    files["replay-request.json"] = canonical_bytes(replay) + b"\n"
    files["reproduce.py"] = REPLAY_SCRIPT.encode()
    files["requirements.txt"] = b"numpy==2.3.4\nscipy==1.17.1\nscikit-learn==1.9.1\njoblib==1.6.0\nthreadpoolctl==3.7.0\n"
    files["README-REPRODUCE.md"] = ("# Crucible numerical evidence\n\nExplicit authored comparison. Install the pinned Python 3.11 dependencies once, then no network, provider keys or inference are required. Run `python reproduce.py --verify-only` to verify hashes and `python reproduce.py` to actually retrain the fixed original, discovery and registered confirmation plan and reverify metrics. This releases labels after verification and is a reproducibility replay, never a new untouched confirmation.\n\nSame OS identity underlies separate trusted processes. No arbitrary code sandbox or external scientific review is claimed. The original paper and R scripts are not included.\n\n" + prepared["source"]["attribution"] + "\n").encode()
    for name in ["scientific-methods.md", "data-provenance.md", "case-registry.md"]:
        path = Path(__file__).parent.parent / "docs" / name
        if path.exists():
            files[f"docs/{name}"] = path.read_bytes()
    manifest = {"schema_version": "crucible.portable-evidence.v1", "created_at": utc_now(),
                "contract_signature": contract_signature(contract), "numerical_spec_sha256": prepared["numerical_spec_sha256"],
                "confirmation_split_sha256": prepared["confirmation_split_sha256"],
                "files": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())},
                "holdout_release": "After completed once-registered verification; replay only"}
    files["manifest.json"] = canonical_bytes(manifest) + b"\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    content = buffer.getvalue()
    sha = hashlib.sha256(content).hexdigest()
    path = immutable_bytes(root / "export" / f"crucible-{sha[:16]}.zip", content)
    return {"artifacts": [artifact(root, path, "portable_evidence", "application/zip")],
            "manifest": manifest, "export_sha256": sha, "sealed_labels_released": True}
