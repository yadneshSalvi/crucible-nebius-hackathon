"""Public wheat workbench metadata. This module never opens evaluation labels."""
from __future__ import annotations

from .store import now

STUDY_ID = "wheat-resolution-v1"
RECIPE_IDS = (
    "native_full", "native_noop", "retain_768", "retain_512", "retain_256",
    "native_tiles", "degraded_tiles256", "native_multiscale",
)
TILED_RECIPES = {"native_tiles", "degraded_tiles256"}
FINAL_CONTROLS = ("native_full", "native_tiles", "native_multiscale")
LIMITATIONS = [
    "A new source-informed experiment on a fixed public GWHD corpus; it does not reproduce the original WILDS numerical result.",
    "No independent methodological reviewer, phenotyping practitioner, or externally validated operating threshold is available. This is a research and benchmark workbench, not evidence of adoption or impact.",
    "Public availability and possible historical label exposure are retained. A local registration is not fresh prospective collection or independent custody.",
    "Acquisition sessions can share fields, sensors, or annotation processes. Results describe this finite corpus; no sampling confidence interval or geographical causal claim is made.",
    "Pixels retained before upload is a digital resampling intervention. It does not simulate flight altitude, a new camera, or plant biology.",
    "SAHI and multiscale inference are established methods. Tiling cannot reconstruct discarded pixels; measured runtime and upload bytes remain part of the comparison.",
    "The verifier uses separate trusted code and a separate process under the same local OS user. This is neither hostile-code isolation nor independent human scientific review.",
]


def recipes() -> list[dict]:
    descriptions = [
        ("native_full", "Native · full image", 1024, "Retain all source pixels and run the fixed detector once."),
        ("native_noop", "Pixel-identical control", 1024, "Repeat a bit-identical native canvas to audit deterministic prediction and coordinate lineage."),
        ("retain_768", "768 px · full image", 768, "Retain 768 pixels before upload; decode and restore the common canvas before the fixed detector."),
        ("retain_512", "512 px · full image", 512, "Retain 512 pixels before upload; decode and restore the common canvas before the fixed detector."),
        ("retain_256", "256 px · full image", 256, "Retain 256 pixels before upload; decode and restore the common canvas before the fixed detector."),
        ("native_tiles", "Native · SAHI tiles", 1024, "Run the attributed SAHI sliced-inference baseline on native retained pixels; merge overlapping detections."),
        ("degraded_tiles256", "256 px · SAHI tiles", 256, "Apply the same tiled recipe after detail has already been discarded; a diagnostic, not pixel recovery."),
        ("native_multiscale", "Native · multiscale", 1024, "Compare a declared full-image multiscale budget with tiled inference; report actual resources rather than assume equal cost."),
    ]
    return [{"id": key, "label": label, "retained_width": width, "description": description,
             "attribution_url": "https://obss.github.io/sahi/predict/" if key in TILED_RECIPES else None,
             "parameters": {"retained_width": width, "coordinate_space": "original_xywh"}}
            for key, label, width, description in descriptions]


def source_fields() -> list[dict]:
    supplement = "https://proceedings.mlr.press/v139/koh21a/koh21a-supp.pdf"
    revision = "472677590de351857197a9bf24958838c39c272b"
    current = f"https://github.com/p-lambda/wilds/blob/{revision}/examples/configs/datasets.py"
    candidates = [
        {"value": {"epochs": 10, "learning_rate": 0.0001, "weight_decay": 0.0001},
         "source_title": "WILDS original supplement", "url": supplement, "locator": "GlobalWheat, PDF page 27 (printed page 26)"},
        {"value": {"epochs": 12, "learning_rate": 0.00001, "weight_decay": 0.001},
         "source_title": "Pinned current WILDS defaults", "url": current, "locator": "globalwheat configuration"},
    ]
    return [
        {"key": "original_run_identity", "label": "Which published run does this reproduce?", "candidates": candidates,
         "status": "unresolved", "critical": True,
         "reason": "Published supplement and current defaults describe different protocols. The original executable run/split/checkpoint package is not qualified. The workbench therefore labels this a new source-informed experiment."},
        {"key": "experiment_lane", "label": "Executed experiment", "candidates": [], "status": "reviewer_chosen",
         "selected_value": "New source-informed finite-corpus experiment",
         "reason": "Authored local operator choice before fitting; no independent reviewer is claimed."},
        {"key": "dataset_license", "label": "Dataset rights and attribution", "candidates": [
            {"value": "CC BY 4.0", "source_title": "Zenodo record metadata", "url": "https://zenodo.org/records/5092309"},
            {"value": "MIT", "source_title": "WILDS GlobalWheat description", "url": "https://wilds.stanford.edu/datasets/"}],
         "status": "unresolved", "selected_value": "Retain both statements and full dataset attribution",
         "reason": "The public sources differ. The source audit records the discrepancy rather than silently choosing a more convenient license."},
        {"key": "primary_metric", "label": "Application measurement", "candidates": [], "status": "reviewer_chosen",
         "selected_value": "Equal-session mean absolute count error, signed count bias, and explicit localization diagnostics",
         "reason": "Authored descriptive metrics. Count error is not WILDS detection accuracy; no practitioner acceptance threshold or broad confidence interval is asserted."},
        {"key": "tiling", "label": "Corrective recipe attribution", "candidates": [
            {"value": "SAHI sliced inference", "source_title": "SAHI official prediction documentation", "url": "https://obss.github.io/sahi/predict/", "locator": "Sliced inference"}],
         "status": "source_supported", "selected_value": "Known SAHI baseline; initially disabled pending a recorded source-to-recipe change",
         "reason": "The allowed finite family includes native and degraded-input tiling. A successful accepted runtime retrieval enables these actual recipes."},
        {"key": "initialization_ambiguity", "label": "Initialization is not the original executable run", "candidates": [
            {"value": "ImageNet pretraining", "source_title": "WILDS original supplement", "url": supplement, "locator": "H.5.2, PDF page 27"},
            {"value": "pretrained=True detector construction (COCO weights), then replace prediction head", "source_title": "Pinned current WILDS detector", "url": f"https://github.com/p-lambda/wilds/blob/{revision}/examples/models/detection/fasterrcnn.py", "locator": "Faster R-CNN model initialization"}],
         "status": "unresolved", "selected_value": "Official ImageNet ResNet-50 V1 backbone, an explicit new-experiment choice",
         "reason": "Neither source statement alone proves the exact original run's executable initialization. The new experiment does not inherit that claim."},
    ]


def initial_study() -> dict:
    created = now()
    recipe_list = recipes()
    return {
        "schema_version": "crucible.wheat.workbench.v1", "id": STUDY_ID,
        "adapter_id": "wheat", "case_kind": "source_informed_public_benchmark", "revision": 1,
        "title": "How much of the field must we keep?",
        "claim": "Measure the effect of pixels retained before upload on a fixed wheat-head detector and this declared public image corpus.",
        "experiment_kind": "New source-informed experiment", "status": "assets_pending", "stage": "wheat",
        "created_at": created, "updated_at": created,
        "scope": "A locked, finite public-corpus experiment in wheat-head counting.",
        "limitations": LIMITATIONS.copy(), "asset": None, "recipes": recipe_list,
        "cells": [{"id": recipe["id"], "recipe_id": recipe["id"], "label": recipe["label"],
                   "retained_width": recipe["retained_width"], "width": recipe["retained_width"],
                   "status": "disabled" if recipe["id"] in TILED_RECIPES else "unrun",
                   "enabled": recipe["id"] not in TILED_RECIPES,
                   "disabled_reason": "Accept an actual primary-source retrieval to enable this declared SAHI recipe." if recipe["id"] in TILED_RECIPES else None,
                   "transform": None, "predictions": [], "missed_target_ids": [], "metrics": None,
                   "aggregate": None, "score_threshold": 0.5, "iou_threshold": 0.5}
                  for recipe in recipe_list],
        "source_fields": source_fields(), "source_compilation": None,
        "training": {"status": "not_started", "detector": "Faster R-CNN · ResNet-50 FPN", "device": "Awaiting actual capability qualification",
                     "checkpoint_sha256": None, "epochs": 10, "detail": "Source, initialization, and exact authored training settings freeze before fitting."},
        "contract": {}, "prepared": False, "run": None, "observations": [], "artifacts": [],
        "evidence_change": None, "evidence_history": [], "planning_history": [],
        "registration": {"status": "not_registered", "review_status": "Local automated operator only; external methodological review unavailable",
                         "requirement": {"kind": "descriptive_benchmark", "practitioner_threshold": None},
                         "detail": "One selected policy and the fixed native, SAHI, and multiscale controls freeze together before final labels open."},
        "custody": {"status": "not_prepared", "dataset_fingerprint": None, "split_manifest_sha256": None,
                    "exposure_status": "Public benchmark; historical exposure unknown", "external_custodian": None,
                    "public_benchmark_caveat": "Locally withheld public images do not become new or independently collected evidence."},
        "planning": {"status": "not_started", "proposal": None, "next_cell_id": None,
                     "rationale": "Nemotron will choose an enabled, genuinely unrun experiment from released discovery evidence only."},
        "decision": {"status": "not_established", "label": "Measure first. Keep the claim bounded.",
                     "reason": "Actual detector measurements are pending. A practitioner requirement and external review are not established.",
                     "limitations": ["No adoption, yield, savings, or scientific novelty claim."]},
        "verification": None, "final_evaluation": None, "export_url": None,
    }
