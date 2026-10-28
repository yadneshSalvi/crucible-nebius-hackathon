# Trusted science worker interface

This package contains authored adapters only. No model-produced source or arbitrary import is accepted. The Python CLI runs without provider credentials and starts predictor/verifier children in the inherited process group. The parent API owns job persistence, global holdout-use enforcement, reviews, retrieval/model calls and user-facing cancellation fences.

```python
from science.api import get_case, prepare_case

metadata = get_case("occupancy")  # pure; metadata["contract"], title, limits
prepared = prepare_case("occupancy", case_root, source_zip=official_archive)
```

`get_case` supports only `occupancy` and `synthetic`. It performs no IO, model fitting, library initialization or retrieval. `prepare_case` is idempotent for an identical prepared root, verifies all retained input bytes, preserves originals, writes sanitized files and separate labels, and snapshots exact trusted Python source. It rejects source drift. An incomplete preparation resumes with its immutable preparation identity; changed trusted source needs a fresh root.

```sh
python -m science.cli prepare --adapter occupancy --root CASE_ROOT --source-zip OCCUPANCY_ZIP --output PREPARED.json
python -m science.cli prepare --adapter synthetic --root CASE_ROOT --output PREPARED.json
python -m science.cli reproduce --input REQUEST.json --output RESULT.json
python -m science.cli explore --input REQUEST.json --output RESULT.json
python -m science.cli predict --input REQUEST.json --output RESULT.json
python -m science.cli verify --input REQUEST.json --output RESULT.json
python -m science.cli export --input REQUEST.json --output RESULT.json
python -m science.cli rerun --input REQUEST.json --output RESULT.json
python -m science.cli reverify --input REQUEST.json --output RESULT.json
```

All stage errors exit 2 and publish `{ "error": { "code": "UPPERCASE_CODE", "message": "specific cause", "recoverable": false } }`. Failed/cancelled/timed-out attempts never produce scientific refutations. Errors and immutable attempt inputs remain available for review. Output publication is atomic; incomplete scientific artifacts are not successful evidence.

`REQUEST.json` has the following fields:

```json
{
  "root": "/absolute/case/root",
  "contract": { "locked": true, "...": "full returned/reviewed contract" },
  "reproduction_accepted": true,
  "active_conditions": ["original", "co2_25", "co2_50", "co2_100"],
  "registration": {
    "condition_id": "original",
    "registered_at": "2026-10-28T00:00:00Z",
    "reviewer_name": "Local operator"
  }
}
```

The contract must match the returned protected population, methods, split, preprocessing, metric, alpha, seeds, allowed lattice, analysis text and numerical-spec/confirmation-split hashes. Only claim text, the reviewed practical margin (0–0.10), normal local review metadata and the permitted schedule may differ. Margin/claim enter the fixed contract signature. Changing the active discovery schedule does not change this signature: the API can pass an accepted EvidenceChange's `active_conditions` separately without rewriting the locked contract. Unchanged numerical methods remain mandatory. Submitted text never becomes executable instructions.

`reproduce` needs the locked contract; the other review fields are not used. `explore` additionally requires accepted reproduction and an actual retained reproduction result. `predict` and `verify` require accepted reproduction and the registration's reviewer/name/time. The worker freezes a scientific registration before prediction. Its own registration digest can differ from the API review-record digest because it binds the numerical implementation, split, actual margin and analysis. A repeat with identical scientific fields is replay; a different condition/analysis is rejected. The parent must enforce global holdout reuse across different folio roots.

All artifact paths in results are relative to the case root and include sha256, bytes, name, kind and media_type. At preparation, `data_artifacts` is the **internal** integrity envelope; raw source files and label files have `private:true`. Public `artifacts` excludes those files entirely. Original archives contain heldout targets, so publishing only the sanitized feature CSV while exposing the raw archive would defeat the boundary. Never send internal source bytes, labels, roots or full attempt inputs to inference providers. The planner receives released aggregates, not raw evaluation targets.

Result shapes:

| Stage | Returned fields |
| --- | --- |
| prepare | source, contract, manifest_sha256, confirmation_split_sha256, numerical_spec_sha256, trusted_code, trusted_code_sha256, source_files, source_snapshot_dir, artifacts, internal data_artifacts, limitations |
| reproduce | observations, artifacts, receipts, prediction_manifest, replay_prediction_manifest, replay with exact prediction/fitted-state agreement |
| explore | observations, artifacts, receipts, prediction_manifest, schedule |
| predict | prediction_manifest, artifacts, receipts, empty observations; no evaluation labels joined |
| verify | verification, observations, conclusion, artifacts, receipts, metric audit |
| export | artifacts containing portable ZIP, manifest, export_sha256, sealed_labels_released |
| rerun | actual training receipts/artifacts and exact prediction agreement for original, retained discovery and registered confirmation plans |
| reverify | normal verified result plus numerical agreement; no fitting or inference |

Observations use decimal balanced-accuracy levels/effects, not percent strings. UI values should multiply levels by 100 for percentages and effects/intervals by 100 for percentage points. Fields include phase, condition_id, condition_label, scope, candidate, baseline, effect, ci_low, ci_high, blocks, total_blocks, rows, analyzed_rows, excluded_blocks, seeds, seed_effects, unit, interval_method, warning and artifact_sha256. Null means undefined, never zero. `blocks` is usable day/group count, never row count × seed count. `seed_effects` are `{seed,effect}` records.

The verified decision is an object with outcome, direction and reasons. Conclusions use `supported_in_tested_scope`, `boundary_identified`, `evidence_against_registered_claim` or `inconclusive`. The occupancy adapter always stays inconclusive in this release because adjacent-day independence is unestablished. The explicitly synthetic groups exercise the full decision path without asserting real-world external validity.

`frozen_source/science/` is the exact Python package to place at the export's `science/`. The portable case directory must also include every internal envelope member, including source/occupancy.zip and frozen_source/science/*.py. Replays load frozen code rather than silently replacing it with current source. `rerun` performs new fits of the frozen plan and compares real prediction hashes; `reproduce`/`predict` can reuse a previously completed exact result and must not be advertised as retraining.

Execution receipt commands are a labeled portable representation (`python -m ...` and paths relative to the worker cwd). Oracle request roots are relative to the verifier's cwd. Bounded diagnostics normalize home/source prefixes at creation. Hashes therefore survive export relocation without rewriting sealed artifacts. Replays require the pinned Python 3.11 numerical dependencies to be installed once and then require no network, retrieval, model keys or inference.

Run the source audit before the training suite:

```sh
python -m unittest discover -s tests -p test_science.py -k Test01 -v
python -m unittest discover -s tests -p test_science.py -v
```

The official-file test is skipped only if the explicitly pinned archive is unavailable locally; all controlled synthetic, oracle, corruption and offline replay tests remain runnable without downloading data.
