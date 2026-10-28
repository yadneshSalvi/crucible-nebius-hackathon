"""The numerical protocol. Chosen before the first fit on 2026-10-28.

This file is trusted application code, never a model-generated proposal. Changing
it changes the numerical-spec digest and invalidates existing experiment plans.
"""

from copy import deepcopy

SCHEMA = "crucible.science.v1"
FEATURES = ["Temperature", "Humidity", "Light", "CO2", "HumidityRatio"]
SEEDS = [11, 29, 47]
CANDIDATE = {
    "name": "Random forest",
    "parameters": {
        "n_estimators": 96,
        "max_depth": 8,
        "min_samples_leaf": 3,
        "max_features": "sqrt",
        "class_weight": "balanced",
        "n_jobs": 1,
        "bootstrap": True,
        "criterion": "gini",
    },
}
BASELINE = {
    "name": "Logistic regression",
    "parameters": {
        "C": 1.0,
        "solver": "lbfgs",
        "class_weight": "balanced",
        "max_iter": 1000,
        "tol": 0.0001,
        "fit_intercept": True,
    },
}
ANALYSIS = (
    "Mean of within-block candidate minus baseline balanced accuracy, first "
    "averaged over seeds. Equal weight per usable block; usable blocks contain "
    "both target classes. Two-sided 95% descriptive Student t interval over "
    "block effects, conditional on these fitted models. Two preregistered "
    "one-sided paired-block t tests at practical_delta (greater and less), "
    "Holm adjusted together at alpha=0.05. At least 6 usable blocks, finite "
    "nondegenerate uncertainty, and justified block independence are required "
    "for a directional conclusion. Seeds and sensor rows are not independent "
    "replications. No equivalence test. One registered confirmation condition; "
    "no optional stopping, tuning, or adaptive confirmation."
)
PREPROCESSING = (
    "Use the five sensor columns in fixed order; exclude date, row ID and "
    "target. Both methods receive median imputation fitted on training only; "
    "logistic regression additionally receives StandardScaler fitted on "
    "training only. Threshold P(class=1)>=0.5. No tuning or feature selection. "
    "All evaluation interventions replace a single sensor with NaN for a "
    "deterministic row-hash mask; impute using unchanged training medians. "
    "The identical mask and rows are used by both methods and all seeds."
)
CONDITIONS = [{
    "id": "original", "label": "Original sensors", "feature": None,
    "rate": 0.0, "scope": "in_scope",
    "description": "All five measured sensor columns; no evaluation dropout.",
}]
for _feature, _prefix in [("CO2", "co2"), ("Light", "light")]:
    for _rate in [25, 50, 100]:
        CONDITIONS.append({
            "id": f"{_prefix}_{_rate}",
            "label": f"{_feature} {_rate}% dropout",
            "feature": _feature, "rate": _rate / 100.0,
            "scope": "applicability",
            "description": (
                f"Replace {_rate}% (hash-selected expectation) of evaluation "
                f"{_feature} values with NaN, then use the training median. "
                "A sensor-availability applicability test outside the original claim."
            ),
        })
DEFAULT_ACTIVE = ["original", "co2_25", "co2_50", "co2_100"]
OCCUPANCY_URL = "https://archive.ics.uci.edu/dataset/357/occupancy-detection"
OCCUPANCY_ZIP_URL = "https://archive.ics.uci.edu/static/public/357/occupancy+detection.zip"
OCCUPANCY_ZIP_SHA256 = "4ae3f46aa98eedff564a9f6924d1635173e2fd2c816004342a9be93076d3a81a"
OFFICIAL_FILES = {
    "train": {"name": "datatraining.txt", "rows": 8143,
              "sha256": "b2c4d0ce2b9e4e453c476f7125ef31aeec2d1f5c7f5572d0e80de3df6521ab56"},
    "discovery": {"name": "datatest.txt", "rows": 2665,
                  "sha256": "1b92c7c1b2838963464fa891a610cf3c5db4becb7189189b29b330107a584c7f"},
    "confirmation": {"name": "datatest2.txt", "rows": 9752,
                     "sha256": "d026d1bd5aeccd4aff4f3b3710d48e40613bd5fc370db7e61bbdcaa50d985095"},
}
GENERATOR = {
    "id": "authored-xor-groups-v1",
    "split_seeds": {"train": 103001, "discovery": 103002, "confirmation": 103003},
    "groups": {"train": 16, "discovery": 12, "confirmation": 24},
    "rows_per_group": 64,
    "target": "XOR of centered Light and CO2 signs, flipped independently with probability 0.05",
    "label_noise": 0.05,
    "group_structure": "Independent pseudo-random generator streams per group, with group-level nuisance offsets. No group shared across splits.",
}
NUMERICAL_SPEC = {
    "schema_version": SCHEMA,
    "protocol_chosen_at": "2026-10-28 before first Crucible fit or outcomes",
    "features": FEATURES,
    "candidate": CANDIDATE,
    "baseline": BASELINE,
    "seeds": SEEDS,
    "preprocessing": PREPROCESSING,
    "analysis": ANALYSIS,
    "allowed_conditions": CONDITIONS,
    "default_active_conditions": DEFAULT_ACTIVE,
    "alpha": 0.05,
    "default_practical_delta": 0.02,
    "min_blocks": 6,
    "interval_coverage": 0.95,
    "tuning_trials_per_method": 0,
    "threshold": 0.5,
    "mask_salt": "crucible-sensor-mask-v1",
    "stopping_rule": "All 3 seeds and all active discovery cells, then one registered confirmation condition once. No optional stopping.",
    "worker": {"cpu_seconds": 180, "wall_seconds": 240, "threads": 1, "max_output_bytes": 33554432},
    "occupancy": {"files": OFFICIAL_FILES, "archive_sha256": OCCUPANCY_ZIP_SHA256,
                  "grouping": "UTC-naive recorded calendar date, no timezone conversion",
                  "independence_established": False},
    "synthetic": GENERATOR,
}
COMMON_LIMITATIONS = [
    "This is an authored local method comparison, not a reproduction of a published paper protocol or a novel feature-ablation finding.",
    "Only trusted authored adapters execute. Separate subprocesses use the same OS identity; this is not a security sandbox or an independent scientific reviewer.",
    "No external methodologist review, participant study, frozen large benchmark, or generalization across datasets has been completed.",
    "Intervals are descriptive 95% intervals conditional on these trained models, not Holm-adjusted simultaneous intervals; failure to reject is not equivalence.",
]
CASES = {
    "occupancy": {
        "adapter_id": "occupancy", "title": "Office occupancy under sensor loss",
        "case_kind": "authored_public_data",
        "claim": "With all five recorded sensors, the authored random forest exceeds logistic regression by at least 0.02 mean day-level balanced accuracy on the official confirmation file's usable days.",
        "population": "One office room in the UCI Occupancy Detection data, official datatest2.txt confirmation file, calendar days containing both occupancy classes. This does not cover new buildings or missing-sensor settings.",
        "split": "Preserve official files exactly: datatraining.txt training, datatest.txt discovery, datatest2.txt confirmation. Discovery (Feb 2–4) precedes training (Feb 4–10); confirmation is Feb 11–18. Never concatenate or random-split the rows.",
        "unit": "recorded calendar day containing both classes",
        "independence_established": False,
        "limitations": COMMON_LIMITATIONS + [
            "The confirmation file covers only eight adjacent days in one room; usable two-class days are fewer. Between-day independence is unestablished, so the real-data verdict remains inconclusive despite any conditional directional p-value.",
            "Discovery predates training. This split is not a pure forward temporal validation study and does not reproduce a paper's protocol.",
            "The public dataset can be historically known to a model; sealed local label handling does not prove benchmark decontamination.",
        ],
    },
    "synthetic": {
        "adapter_id": "synthetic", "title": "A controlled nonlinear sensor system",
        "case_kind": "controlled_synthetic",
        "claim": "With all five generated sensors, the authored random forest exceeds logistic regression by at least 0.02 mean group-level balanced accuracy on untouched independent confirmation groups.",
        "population": "Fresh independent groups from authored-xor-groups-v1, conditional on the fixed training set and seeds. This synthetic control is not a discovery about public research.",
        "split": "Fixed generator v1: 16 training, 12 discovery and 24 confirmation groups of 64 rows each. Separate split seeds 103001,103002,103003; independent per-group streams and no shared group across partitions.",
        "unit": "independent generated group containing both classes",
        "independence_established": True,
        "limitations": COMMON_LIMITATIONS + [
            "Explicitly controlled synthetic data with a known nonlinear XOR generator; it demonstrates the machinery, not real-world scientific validity.",
            "Group independence follows the authored pseudorandom generator construction. The fixed training set is shared and the inference conditions on it.",
        ],
    },
}


def case_metadata(adapter_id):
    if adapter_id not in CASES:
        raise ValueError("Only the trusted occupancy and synthetic adapters are supported")
    return deepcopy(CASES[adapter_id])
