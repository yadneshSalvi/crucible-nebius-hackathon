# Crucible local integration contract

## Ownership
Lead: `api/`, `contracts/`, root package/config/dependencies, `scripts/`, API/integration tests and release docs.
Science worker: `science/`, `tests/test_science.py`, `docs/scientific-methods.md`, `docs/case-registry.md`, `docs/data-provenance.md`.
UI worker: `web/` only (including entry, components, CSS and fonts). Do not edit root package/config.

No arbitrary repositories or submitted Python execute. Science is trusted authored local code. UI 4201, API 4202. Root owns CUA. Workers may use Playwright.

## API
Base `/api`. JSON. `GET /health` includes provider capability/route. `GET /folios` returns `{folios: FolioSummary[]}`. `POST /folios` body `{adapter_id:'occupancy'|'synthetic', title?: string, claim?: string}` creates draft. `GET /folios/{id}` returns complete Folio. `GET /folios/{id}/events?after=0` -> `{events: Event[], next: number}`. `GET /folios/{id}/export` zip; `/report` HTML. `GET /artifacts/{sha}` safe artifact.

Mutations: JSON POST `/folios/{id}/actions/{action}`, include `revision` and `idempotency_key` UUID. Errors `{error:{code,message,recoverable}}`. Actions return updated Folio (long jobs begin with 202). Poll folio during run at 1500ms. Never simulate progress.

Actions:
- `propose_contract`: actual NVIDIA draft from source context; cannot edit oracle. Long job.
- `update_contract`: body `claim`, `title`, `practical_delta` (0..0.1); only draft. Immutable prior revisions.
- `lock_contract`: body `reviewer_name`,`review_note`; local operator review; external methodologist pending.
- `reproduce`: long job, original condition training/discovery with deterministic replay. `accept_reproduction` body `reviewer_name`.
- `retrieve`: long job, real Tavily source receipts and proposed EvidenceChange.
- `accept_evidence`/`reject_evidence`: body `reviewer_name`,`reason`; accepting changes actual exploration schedule within locked allowed lattice.
- `explore`: long job, finite active discovery conditions; model ranks valid IDs using discovery aggregates. Failed proposals remain recorded. User may choose observed condition even if model fails.
- `register_confirmation`: body `condition_id`,`reviewer_name`; freezes one condition before holdout use. Holdout cannot serve adaptively different plans. `confirm`: long job, sealed predictions. `verify`: long job, separate trusted verifier joins sealed labels and computes mechanical decision.
- `review_conclusion`: body `reviewer_name`,`review_note`; local operator acknowledgement, never external scientific sign-off.
- `cancel`: current job. `resume`: operational attempt after failed/cancelled/interrupted; cannot turn completed confirmation into a new hypothesis.

## Folio shape
`{id,adapter_id,title,claim,case_kind:'authored_public_data'|'controlled_synthetic',created_at,updated_at,revision,stage,status,source,contract,run,evidence_change,observations,proposals,registration,verification,conclusion,receipts,events,artifacts,limitations}`.

`status`: draft, reviewed, running, baseline_review, reproduced, evidence_review, explored, confirmation_locked, confirmation_ready, review_ready, complete, cancel_requested, cancelled, interrupted, failed.
`stage`: contract, reproduction, challenge, confirmation, folio.

`source`: `{title,url,license,attribution,description,sha256,files:[{name,sha256,rows,split}],audit,kind,source_span}`; initially null, display truthful loading/unavailable.
`contract`: `{schema_version,revision,sha256,claim,population,candidate,baseline,metric,practical_delta,alpha,analysis,split,preprocessing,seeds,allowed_conditions,active_conditions,scope,approval,model_proposal,locked}`. Most rich fields are strings, except seeds array, conditions array, candidate/baseline `{name,parameters}`, approval object. Metric `balanced_accuracy`. `allowed_conditions` objects `{id,label,feature,rate,scope:'in_scope'|'applicability',description}`. Original condition ID `original`.
`run`: null or `{id,action,status,started_at,updated_at,heartbeat_at,checkpoint,completed_units,total_units,unit_label,attempt,error,can_resume}`.
`evidence_change`: null or `{id,status:'proposed'|'accepted'|'rejected'|'context_only',query,queried_at,source:{title,url,excerpt},assumption,before:string[],after:string[],explanation,decision,receipt_id}`.
`observations`: array `{id,phase:'reproduction'|'discovery'|'confirmation',condition_id,condition_label,scope,candidate,baseline,effect,ci_low,ci_high,blocks,rows,seeds,seed_effects,unit,interval_method,warning,artifact_sha256}`. Nullable numbers; decimals not percentages. Never invent an observation.
`proposals`: array `{condition_id,rank,rationale,expected_information,scope}` from validated real model response. User-selected available conditions usable if model fails.
`registration`: null or `{condition_id,registered_at,sha256,reviewer_name,analysis,holdout_status}`.
`verification`: null or `{status:'verified'|'rejected',sha256,checks:[{name,passed,detail}],metrics,decision,method,independence,artifact_sha256}`.
`conclusion`: null or `{outcome,title,statement,scope,limitations:string[],references:string[],review}`.
`receipts`: sanitized `{id,kind,provider,model,status,request_id,started_at,elapsed_ms,input_tokens,output_tokens,estimated_cost_usd,error,purpose}`. Raw secrets/reasoning never sent to client.
`events`: `{seq,type,message,created_at,run_id}`. `artifacts`: `{sha256,name,media_type,kind,bytes}`. `limitations`: string[].

## Science interface
`python -m science.cli prepare --adapter occupancy|synthetic --root PATH` establishes hashes, split manifest, trusted plan and separate sealed labels before fits/outcomes. All runtime is ignored. Numerical commands run in separate subprocess with no provider credentials. Worker must promptly finalize exact interface, pure helpers `science.api.get_case(adapter_id)` and `prepare_case(adapter_id, root)` preferable. Export includes locked source, data, plan, predictions and independent verifier, rerunnable offline without inference.
