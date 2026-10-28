# Wheat workbench validation — 28 October 2026

The available software and source-role work is qualified. The wheat counting experiment is **not complete**: one of 3,653 required photographs is present, no detector has been fitted on this corpus, all eight discovery cells are unrun, and final registration/evaluation/export remain gated. These limits appear in the actual UI and API.

## What was actually checked

The independent orchestrator completed fresh primary-source and data-preview bootstraps from empty temporary directories over HTTPS. The pinned documents, code excerpts, source metadata, immutable role/selection records and selected image reproduced. The selected PNG matches the official archive member and all 45 source boxes align with it. Missing-image finalization refuses the remaining 3,652 photographs and leaves the executable manifest absent. The real export endpoint returns HTTP409. See [orchestrator QA](wheat-orchestrator-qa.json) and [source audit](wheat-source-audit.md).

The real production UI passed six-width checks for overflow, accessibility, page errors, history navigation, exact image/box coordinates and keyboard-selected annotations. Root independently checked the full image at 1280×720, with readiness and UNRUN context visible. No test filled the actual runtime with fabricated predictions. Screenshots are retained under [screenshots/wheat](screenshots/wheat).

Offline tests cover analytic count/localization errors, misses/duplicates/empty cases, seed→image→session aggregation, separate label custody, source/pixel/group leakage, corrupted hashes, transform/offset/NMS lineage, lossless numeric arrays, native/no-op equivalence across envelopes, immutable final families and relocated metric replay. Control-plane tests cover truly unrun choices, stale proposals, per-pixel exposure across changed manifests, prediction-before-opening order, verifier rejection, frozen workflow export evidence and legacy-route isolation. Actual dummy child processes confirm restart cleanup for both allowed worker modules while an unrelated module remains untouched. Legacy sources still execute from their retained hash-checked packages; altered, missing or additional modules fail closed.

The final consolidated suite passed **74 tests in 16.06seconds**. TypeScript checking and the production Vite build passed, as did `git diff --check`. These are engineering checks: the relocated capsule test uses authored fixtures and does not establish a fresh replay of an unrun real-image study.

## Actual service qualification

Every call below used NVIDIA Nemotron Ultra. [The sanitized ledger](wheat-provider-qualification.json) retains provider/model/request identities, usage, failure status and the limited qualification scope. Dollar values are uncached-rate estimates, not invoices.

| Attempt | Receipt | Result | Input / output tokens | Estimate |
| --- | --- | --- | --- | --- |
| Fireworks initial source summary | d79a15ce-fc79-4f48-926c-279ed4f49ae9 | Strict schema rejection retained | 2,367 / 3,630 | $0.0101322 |
| Fireworks v1 audited summary | 31b63ef5-85f6-46aa-8c7b-dd1327281d0f | Passed structuring; expected values were supplied | 2,372 / 1,899 | $0.0059808 |
| Fireworks v2 primary excerpts | 65899456-abf1-4f82-a6ec-c57a0e66ff33 | Six source values passed local audit | 1,897 / 1,701 | $0.0052206 |
| Nebius v2 deliberate replay | c4d20c7d-31c5-496c-8620-f0a4ea2e3cea | Rejected ambiguous mathematical strings; ungrounded execution narrative retained but not accepted | 1,897 / 1,413 | $0.006136 |
| Fireworks v3 atomic extraction | fdab1c81-c548-4a8c-b4a0-661b9d886b1c | Six exact fields and conflict class passed | 1,810 / 952 | $0.0033708 |
| Nebius v3 deliberate replay | 69319c9d-ac50-4fe0-9849-f56425139cdf | Six exact fields and conflict class passed | 1,810 / 907 | $0.004531 |

The first Fireworks failure predates bounded final-content diagnostics; its request/response hashes, usage and failure remain, but its original invalid final text was not retained. Later diagnostics retain only the bounded final-answer field, excluding the provider's separate reasoning field. This field exclusion does not guarantee the semantic contents of malformed final prose.

The v1 call is correctly labeled audited-summary structuring. V2 and v3 instead read a hash-bound primary-excerpt packet (`95930c9ac197c21dbd6f62326954c706630c4bbba82deec7fc19dcda51ba84a4`); expected numeric answers stay validator-only. V3 permits ASCII decimal/e-notation strings and a finite conflict classification, with no model-written execution narrative. Trusted code supplies locators, authored execution scope and remaining limitations. The original and current source settings are not selected by favorable outcomes.

Fireworks total: four attempts, 8,446 input / 8,182 output tokens, estimated **$0.0247044**. Nebius total: two deliberately distinct qualification profiles, 3,707 input / 2,320 output tokens, estimated **$0.010667**. The final Nebius call used the exact regional Ultra model, thinking enabled, temperature1/top-p0.95, 32,000 output and 480-second bounds. Its actual elapsed time was 3.217seconds. Both Nebius calls passed a cumulative local-ledger admission and a nominal $0.12 request bound. No automatic retry or top-up occurred. Deduplicated four-project Nebius usage after these calls is **$2.37192194** within the existing authorization; this is not an account-balance measurement.

One actual Tavily advanced search returned an eligible primary SAHI source. The orchestrator accepted its predeclared recipe-enablement change in the UI. The native and degraded-input SAHI controls are enabled and remain unrun. Tavily did not return credit/charge evidence; those amounts remain unknown. Source extraction and retrieval are qualified roles, not a substitute for the pending experiment planner choosing from real detector measurements.

## Hardware and initialization

A real MPS engineering probe ran the strong Faster R-CNN ResNet50-FPN at 800/1333, batch four, Adam and the 1,000-detection cap on random dummy tensors/two dummy boxes. Three optimizer steps took 1.317, 1.058 and 0.868seconds, with finite loss, approximately 629MB process RSS and 727MB MPS allocation. Actual SAHI sliced inference made nine forwards on a blank engineering image in 1.672seconds. No scientific photograph or label entered these probes. Their historical receipt predates the prospective epoch-shuffle change; it is hardware evidence, not a full-protocol training run.

The official ResNet50 ImageNet1K V1 initialization was downloaded with TLS and byte/storage bounds: **102,530,333bytes**, SHA256 `0676ba61b6795bbe1773cffd859882e5e297624d384b6993f7c9e683e722fb8a`. All 267 tensors loaded with `weights_only=True` on CPU, were finite, and had the expected classifier/input shapes. Receipt `a88aba4c39754d0986cb566e1f92cd6e` is explicitly source-only; its preparation-manifest field is null. The utility now pins this full digest for fresh downloads. It did not fit a detector or create an executable corpus manifest.

## Work still required

Retrieve the remaining complete cohort, verify every decoded image and duplicate audit, finalize the manifest, prepare the frozen case and train all three seeds for all ten epochs. The registered corpus, strong model, image resolution and epoch count are not reduced to fit current storage. The conservative pipeline budget is approximately 31GiB free before ingestion, including one ZIP; separate extraction/fresh replay needs additional budget. Current disk remains insufficient for this path.

Then measure real discovery controls, have Nemotron choose an actually unrun experiment, execute it, inspect misses/duplicates/localization/bytes/timing, freeze one descriptive policy plus controls, predict the complete final family, open labels once, independently verify and export. A fresh real-image inference replay and final-runtime planning qualification remain pending. No confidence interval, deployment threshold, savings, adoption, novelty or independent-review claim is made. Public held-out files do not become historically untouched through a new directory.

[The README](../README.md) gives the fresh-checkout and continuation commands. [Methods](wheat-methods.md) describe the exact protocol and replay limits. No deployment, push, purchase or submission occurred during this upgrade.
