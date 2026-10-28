# Crucible

An executable scientific folio: an authored claim becomes a reviewed contract, a real numerical reproduction, a finite challenge, a registered confirmation and an independently recomputed, bounded conclusion.

The local app includes a licensed UCI Occupancy comparison and a controlled synthetic nonlinear case. It trains real random forests and logistic regressions in Python. NVIDIA Nemotron proposes claim wording and informative challenges; Tavily supplies an inspectable source-to-experiment change. Neither service defines the metric oracle or receives sealed confirmation labels.

This is an authored comparison on public data, **not a reproduction of the original paper's full protocol or a new feature-ablation discovery**. The UCI case uses adjacent calendar-day blocks whose independence is not established. External methodologist review and a frozen benchmark study remain pending.

## Run locally

Use Node 22.22+ and Python 3.11. The API and browser bind only to loopback.

```sh
npm ci
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
npm run build
npm start
```

Open http://127.0.0.1:4201 . API health is at http://127.0.0.1:4202/api/health . `npm run dev` runs the source UI. Keep ports 4201 and 4202 free; other projects use their own ports.

Add the authorized `FIREWORKS_AI_API_KEY` and `TAVILY_API_KEY` to the **existing parent `.env`**, or export them server-side. Do not overwrite an existing environment file. `.env.example` documents supported names. Numerical execution and portable reproduction require no model key; unavailable services report a specific error instead of substituting fake responses.

Development uses `accounts/fireworks/models/nemotron-3-ultra-nvfp4` at Fireworks, high reasoning, 32,000 output tokens, 480-second timeout, schema in the prompt and strict local validation. There is no implicit fallback. The final Nebius Ultra adapter is explicit and disabled in development; completion qualification is pending. Historical receipts retain their original provider.

First launch audits the pinned UCI data and creates two **drafts**; it does not manufacture completed runs. The data adapter fetches only the fixed licensed UCI archive and verifies all pinned hashes. It can reuse the parent workspace's audited archive. SQLite, artifacts and cases live in ignored `runtime/`. Preserve this directory to retain history and the global holdout-exposure registry.

## Walk through the evidence

1. Inspect a draft's source and fixed protocol, optionally ask Nemotron to propose wording, then review it as the local operator.
2. Lock the contract and reproduce the original condition. Two subprocess fits must return identical predictions and fitted-state fingerprints.
3. Accept reproduction, retrieve evidence and review the proposed change. Accepting the Light-sensor proposal adds actual discovery conditions.
4. Execute the finite discovery schedule, inspect every cell and the model proposal, then register one confirmation condition.
5. Generate confirmation predictions. The separate verifier joins sealed labels and checks coverage, preprocessing, provenance, metrics and the mechanical decision.
6. Acknowledge the bounded conclusion locally and export its HTML report and portable evidence ZIP.

Review records identify the actual local operator. Automated acceptance runs use **Automated local QA (agent)** and do not claim human scientific review. A new folio does not reset previously inspected confirmation labels. Exact replays are labeled; a different adaptive plan is blocked.

## Verify and reproduce

```sh
npm test
npm run typecheck
npm run build
```

With the production app already running, `npm run test:e2e` runs the committed read-only browser checks against the local library and Occupancy stages. It performs no inference or scientific mutations, and saves screenshots/axe results in ignored `web/qa-output/`. It reuses installed Chromium; on a new machine install it with `npx playwright install chromium` or set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`. `npm run test:ui-journey` separately creates a clearly labeled UI QA synthetic folio and exercises edit, review, cancellation and resume without model calls.

With the app running and providers authorized, `.venv/bin/python scripts/validate-live.py` executes actual live journeys. It incurs metered inference/retrieval and keeps real receipts. It is separate from offline tests.

After verification, extract the evidence ZIP into a new directory. Install its pinned dependencies, run `python reproduce.py --verify-only`, then `python reproduce.py`. The latter actually retrains the fixed original/discovery/confirmation plan and separately recomputes metrics without inference, retrieval or provider keys. It is a reproducibility replay, not fresh confirmation.

Read [scientific methods](docs/scientific-methods.md), [data provenance](docs/data-provenance.md), [case registry](docs/case-registry.md), [architecture](docs/architecture.md) and [third-party attribution](THIRD_PARTY.md).

Only trusted authored tabular adapters execute; arbitrary paper/repository imports and user code are unavailable. Predictor and verifier share the local OS identity, so this is not a hardened untrusted-code sandbox or external scientific independence. Cancellation fences block stale commits; remote provider termination and final billing cannot be guaranteed. Operational failure and scientific outcomes remain separate.

Original code is MIT licensed; UCI data are CC BY 4.0. The paper and original R scripts are not redistributed. No cloud deployment, paper-protocol qualification, participant research or hackathon submission has occurred. Proposed track: Best Apps and Agents.
