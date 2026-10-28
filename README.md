# Crucible

An image-first research workbench for measuring how wheat-head counts change when pixels are discarded before upload. Authentic Global Wheat Head Dataset photographs and boxes sit beside a fixed detector protocol, known SAHI controls, an unrun-experiment planner, independent numerical checks and a registered final comparison.

This is a **new source-informed experiment on a finite public corpus**, not exact WILDS reproduction, an algorithmic novelty claim or a validated field policy. Independent reviewers, practitioner thresholds, acquisition-unit independence and adoption evidence are unavailable. Source annotations are real; detector cells remain explicitly unrun until actual fitting and inference finish.

The retained Occupancy and XOR folios are available through **History**. Their results, failures and exposure history remain intact. Occupancy remains inconclusive (−1.5729 percentage points; day independence unestablished); the nonlinear result applies to its generator only.

## Run locally

Use Node 22.22+ and Python 3.11 for the API and tests. Both services bind to loopback.

```sh
npm ci
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
npm run build
npm start
```

Open [the workbench](http://127.0.0.1:4201). API health is at [4202/api/health](http://127.0.0.1:4202/api/health). `npm run dev` serves the source UI. Keep ports 4201 and 4202 free.

Read authorized `FIREWORKS_AI_API_KEY`, `TAVILY_API_KEY` and optional `NEBIUS_API_KEY` from the **existing parent `.env`**, or export them server-side. Do not overwrite an existing file or use browser `VITE_*` secrets. `.env.example` documents routing and optional asset/runtime locations. Numerical execution and replay require no model key.

Development uses Fireworks `accounts/fireworks/models/nemotron-3-ultra-nvfp4`, high reasoning, 32,000 output tokens, a 480-second timeout and strict local validation. Nebius uses `nvidia/Nemotron-3-Ultra-550b-a55b` on the explicit US-central Token Factory route, thinking enabled, temperature 1/top-p 0.95 and the same output/time bounds. No provider or smaller-model fallback exists. The bounded source role has passed actual qualification on both routes; real experiment-planning and scientific workflow qualification remain pending. Every attempt, including rejected output, remains recorded.

SQLite, objects and cases live in ignored `runtime/`. Preserve **the entire existing runtime** when moving to another volume: a new directory cannot make previously exposed public images untouched. The process boundary is trusted local software sharing one OS identity, not an untrusted-code sandbox or independent human custody.

## Bootstrap the wheat sources

The API environment includes Pillow for catalog and verifier tests. Detector training has a separate Python 3.13 environment; install its complete lock without relying on another machine's cache:

```sh
python3.13 -m venv .venv-wheat
.venv-wheat/bin/python -m pip install --require-hashes -r requirements-wheat.lock
```

Retrieve the pinned primary documents and small archive members first. TLS, byte limits, CRC and SHA checks stay enabled. Source bootstrap checks exact code lines and retains the PDF excerpt's previously rendered-page provenance; it does not claim fresh OCR.

```sh
.venv/bin/python scripts/qualify_wheat_sources.py
.venv/bin/python scripts/qualify_wheat_assets.py --member gwhd_2021/competition_train.csv --member gwhd_2021/metadata_dataset.csv
.venv/bin/python scripts/prepare_wheat_catalog.py
```

The catalog freezes source-only roles and the lexicographic discovery-image selection before outcomes. It quarantines all four contradictory rows for two duplicate image IDs. The eligible inventory is 3,653 unique photographs: 3,011 training, 432 discovery and 210 final. Final boxes occupy a separate private annotation store. This is trusted ingestion of public labels, not historical benchmark decontamination.

To show the fixed discovery photograph before full ingestion:

```sh
.venv/bin/python scripts/qualify_wheat_assets.py --member gwhd_2021/images/0077c64686e9712d9b8efcd930ce5b0d68c72d8fb50ee99ed01ff2fd73e6d1d2.png
.venv/bin/python scripts/prepare_wheat_catalog.py
```

Restart the API after this initial bootstrap. The UI releases this image's 45 source boxes, with no simulated predictions.

```sh
.venv/bin/python scripts/download_wheat_catalog.py
```

This audit reports missing image bytes and available disk. In the recorded partial state, 3,652 photographs need another 6,450,846,275 bytes. Ingestion alone needs about 9 GB free including reserve. **Allow approximately 31 GiB free before ingestion for the conservative full pipeline and one evidence ZIP**: three Adam resumes, three final models, checkpoint temporaries, lossless predictions, metadata, one capsule and a 2 GiB reserve. A separate extraction/fresh-inference replay workspace and new dependency installation require additional space. Stage gates use actual manifests and disk space, without assuming favorable counts or compression.

Source images use verified hardlinks on one filesystem. Cross-filesystem copies require their full additional budget. Large NPZ predictions, model files and the ZIP stay in the numerical case rather than being duplicated into browser objects. No corpus, resolution, epoch or model reduction bypasses storage admission.

Once sufficient storage exists, retrieve every eligible photograph and finalize its dimensions, decoded pixel identity and duplicate audit:

```sh
.venv/bin/python scripts/download_wheat_catalog.py --download
.venv/bin/python scripts/prepare_wheat_catalog.py --finalize
```

Only successful finalization creates `runtime/wheat-assets/manifest.json`. Missing bytes or duplicate identity/pixels fail closed. On another volume, pass `--output`/`--assets-root` to source utilities and set `CRUCIBLE_WHEAT_MANIFEST` for the server. If changing `CRUCIBLE_RUNTIME`, migrate the complete existing runtime and preserve all source records and the role plan.

The official ImageNet initialization can be qualified separately while full data are pending, using `scripts/qualify_wheat_initialization.py --download --source-only` in `.venv-wheat`. This checks official bytes, full SHA and finite tensor shapes; it never authorizes fitting or marks the corpus prepared.

## Execute the registered workflow

The browser and CLI share the authenticated, revision-checked API. These are explicit actions, not an unattended paid retry loop. Source compilation and retrieval can run while image ingestion is pending:

```sh
.venv/bin/python scripts/wheat_action.py compile_sources --wait
.venv/bin/python scripts/wheat_action.py retrieve --wait
```

Inspect the returned primary SAHI citation and proposed change. Acceptance enables the predeclared native and already-degraded tiled recipes without changing detector, metric or data roles.

```sh
.venv/bin/python scripts/wheat_action.py accept_evidence --operator "Local operator" --reason "Reviewed the primary SAHI source and declared recipe change."
.venv/bin/python scripts/wheat_action.py prepare --wait
.venv-wheat/bin/python scripts/qualify_wheat_initialization.py --download
.venv/bin/python scripts/wheat_action.py train --wait
```

The initialization utility accepts only the official ResNet50 ImageNet1K V1 URL and records its full SHA before fitting. It rechecks an existing qualified file. With external paths, pass `--assets-root` and `--case-root`. No COCO detector checkpoint is silently substituted.

The authored protocol trains seeds 11/29/47 with ResNet50-FPN at 800/1333, FrozenBatchNorm, three trainable backbone layers, Adam at learning rate 1e-4/decay 1e-4, batch four, ten epochs and a 1,000-detection cap. Every seed/epoch deterministically shuffles the entire corpus and retains the order hash. Epoch ten is used without validation selection or early stopping. Dummy MPS qualification supplies engineering capability, not detector results or a full-training timing guarantee.

Measure initial controls, then ask Nemotron to choose a **still-unrun** experiment:

```sh
.venv/bin/python scripts/wheat_action.py run_cell --cell native_full --wait
.venv/bin/python scripts/wheat_action.py run_cell --cell native_noop --wait
.venv/bin/python scripts/wheat_action.py run_cell --cell retain_256 --wait
.venv/bin/python scripts/wheat_action.py plan_next --wait
.venv/bin/python scripts/wheat_action.py execute_plan --wait
.venv/bin/python scripts/wheat_action.py status
```

Complete `native_tiles` and `native_multiscale` if they remain unrun, using `run_cell --cell ... --wait`. Inspect counts, misses, duplicates, localization, encoded bytes and actual timing. Nemotron receives released discovery aggregates; it supplies neither labels nor metrics. Every width uses the same lossless PNG codec. Native/no-op byte and prediction equivalence must pass. Nine multiscale forwards match the tile count, not necessarily its cost.

Register one explicitly chosen completed recipe. Its policy and fixed native/SAHI/multiscale controls freeze together with source/code/split/checkpoint identities and the exact discovery parent. Discovery and family expansion then stop:

```sh
.venv/bin/python scripts/wheat_action.py register --cell retain_256 --operator "Local operator"
.venv/bin/python scripts/wheat_action.py evaluate --wait
.venv/bin/python scripts/wheat_action.py build_export --wait
```

The example selects `retain_256` for a descriptive comparison, not a preclaimed successful policy. All final predictions finish before the separate verifier opens labels. The global per-pixel exposure registry survives restarts and manifest renaming. Undefined metrics stay null; seeds average within image, then session. No independence-based interval or invented acceptable-error threshold is supplied.

## Verify and replay

```sh
npm test
npm run build
node web/qa-wheat-actual.mjs
.venv/bin/python scripts/wheat_ledger.py
```

Tests use authored engineering fixtures, not scientific outcomes. Read-only browser QA checks six widths, real image/box alignment, keyboard selection, accessibility and History navigation. Legacy read-only QA is `npm run test:e2e`; the separate mutating synthetic UI journey is `npm run test:ui-journey`. A new machine needs Playwright Chromium or `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`.

The Nebius qualification utility defaults to a cumulative four-project budget audit. Its explicit `--execute` mode serves the already authorized, one-shot source replay and refuses a previously attempted profile. It preserves failures, never tops up, and does not inherit account authorization in a fresh checkout. Full scientific qualification remains separate.

A wheat ZIP is unavailable until final verification. Extract a completed capsule into a new directory with sufficient space, install its recorded dependencies, then run:

```sh
python reproduce.py --verify-only
python reproduce.py --metrics-only
python reproduce.py
```

These check hashes, independently recompute metrics without Torch, and perform fresh inference from retained checkpoints followed by verification. No network or provider key is needed after installing dependencies. This is replay, not retraining or fresh confirmation. Legacy tabular capsules separately retrain their frozen plan. Old folios dispatch the retained hash-checked source package; changed or additional modules cannot silently authorize an old run.

Read [wheat methods](docs/wheat-methods.md), [primary-source audit](docs/wheat-source-audit.md), [validation and limits](docs/wheat-validation.md), [legacy methods](docs/scientific-methods.md) and [third-party attribution](THIRD_PARTY.md). No cloud deployment, independent practitioner study or hackathon submission has occurred.
