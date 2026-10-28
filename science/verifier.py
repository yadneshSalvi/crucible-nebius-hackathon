"""Trusted metric oracle. Only this worker joins sealed evaluation labels.

Balanced accuracy is independently implemented from binary confusion counts;
sklearn metrics are never imported. The CLI launches this in a new process.
"""

import argparse
import csv
import math
import os
import statistics
from collections import defaultdict
from pathlib import Path

from .api import contract_signature, validate_contract
from .common import ScienceError, artifact, atomic_result, digest, file_hash, immutable_bytes, immutable_json, read_json, utc_now, verify_file
from .prepare import csv_bytes, load_prepared
from .spec import BASELINE, CANDIDATE, CONDITIONS, FEATURES, NUMERICAL_SPEC, SEEDS, case_metadata


def balanced_accuracy(labels, predictions):
    """Mean sensitivity/specificity; undefined if a target class is absent."""
    if len(labels) != len(predictions) or not labels:
        raise ScienceError("METRIC_INPUT", "Labels/predictions must be nonempty and equally sized")
    counts, correct = [0, 0], [0, 0]
    for label, prediction in zip(labels, predictions):
        if label not in (0, 1) or prediction not in (0, 1):
            raise ScienceError("METRIC_INPUT", "Binary labels and predictions required")
        counts[label] += 1
        correct[label] += int(label == prediction)
    if 0 in counts:
        return None
    return 0.5 * (correct[0] / counts[0] + correct[1] / counts[1])


def holm_adjust(p_values):
    """Step-down Holm adjusted p-values in the declared family order."""
    if not p_values or any(p is None or not math.isfinite(p) or not 0 <= p <= 1 for p in p_values):
        raise ScienceError("METRIC_INPUT", "Holm requires finite p-values in [0,1]")
    order = sorted(range(len(p_values)), key=lambda i: p_values[i])
    adjusted, previous = [0.0] * len(p_values), 0.0
    for rank, index in enumerate(order):
        previous = max(previous, min(1.0, (len(p_values) - rank) * p_values[index]))
        adjusted[index] = previous
    return adjusted


def summarize_effects(effects, delta=0.02):
    """A descriptive CI and conditional directional tests, not adjusted CIs."""
    from scipy.stats import t
    n = len(effects)
    if any(not math.isfinite(x) for x in effects):
        raise ScienceError("METRIC_INPUT", "Block effects must be finite")
    mean = statistics.fmean(effects) if effects else None
    result = {"effect": mean, "ci_low": None, "ci_high": None, "standard_error": None,
              "greater_raw_p": None, "less_raw_p": None, "greater_holm_p": None, "less_holm_p": None,
              "degrees_of_freedom": n - 1 if n else None, "degenerate": True}
    if n < 2:
        return result
    se = statistics.stdev(effects) / math.sqrt(n)
    result["standard_error"] = se
    if not math.isfinite(se) or se <= 1e-14:
        return result
    quantile = float(t.ppf(0.975, n - 1))
    statistic = (mean - delta) / se
    greater, less = float(t.sf(statistic, n - 1)), float(t.cdf(statistic, n - 1))
    adjusted = holm_adjust([greater, less])
    result.update({"ci_low": max(-1.0, mean - quantile * se), "ci_high": min(1.0, mean + quantile * se),
                   "greater_raw_p": greater, "less_raw_p": less,
                   "greater_holm_p": adjusted[0], "less_holm_p": adjusted[1], "degenerate": False})
    return result


def mechanical_decision(summary, usable_blocks, independent, scope, reproduction_accepted):
    reasons = []
    if not reproduction_accepted:
        reasons.append("Original-condition deterministic reproduction has not been accepted")
    if usable_blocks < NUMERICAL_SPEC["min_blocks"]:
        reasons.append(f"Only {usable_blocks} usable blocks; protocol requires at least 6")
    if not independent:
        reasons.append("Independence of adjacent calendar-day blocks is unestablished")
    if summary["degenerate"] or summary["ci_low"] is None:
        reasons.append("Uncertainty is undefined or degenerate")
    if reasons:
        return {"outcome": "inconclusive", "direction": None, "reasons": reasons}
    if summary["greater_holm_p"] <= 0.05:
        return {"outcome": "supported_in_tested_scope", "direction": "greater_than_delta",
                "reasons": ["Registered greater-than-margin test passes Holm adjustment within this tested setting"]}
    if summary["less_holm_p"] <= 0.05:
        if scope == "in_scope":
            return {"outcome": "evidence_against_registered_claim", "direction": "less_than_delta",
                    "reasons": ["Registered less-than-margin test passes Holm adjustment; this need not be a ranking reversal"]}
        return {"outcome": "boundary_identified", "direction": "less_than_delta",
                "reasons": ["The superiority margin does not transfer to this sensor-loss setting; an applicability boundary does not refute the original sensor-complete claim"]}
    return {"outcome": "inconclusive", "direction": None,
            "reasons": ["Neither direction passes Holm adjustment; this is not evidence of equivalence"]}


def _read_csv(path, expected_fields):
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != expected_fields:
            raise ScienceError("VERIFIER_SCHEMA", f"Unexpected columns in {Path(path).name}")
        return list(reader)


def _check_preprocessing(root, split_manifest, receipt):
    import numpy as np
    training = _read_csv(verify_file(root, split_manifest["splits"]["train"]["features"]),
                         ["row_id", "block_id", *FEATURES, "target"])
    values = np.asarray([[float(row[key]) for key in FEATURES] for row in training])
    medians, mean, scale = np.median(values, axis=0), values.mean(axis=0), values.std(axis=0)
    scale[scale == 0] = 1.0
    train_ids_sha = digest([row["row_id"] for row in training])
    expected_fits = {(seed, method) for seed in SEEDS for method in ["candidate", "baseline"]}
    actual = set()
    for fit in receipt.get("fit_receipts", []):
        key = (fit.get("seed"), fit.get("method"))
        if key in actual or key not in expected_fits:
            raise ScienceError("FIT_ACCOUNTING", "Unexpected or duplicated training seed/method")
        actual.add(key)
        definition = CANDIDATE if fit["method"] == "candidate" else BASELINE
        if fit.get("parameters") != {**definition["parameters"], "random_state": fit["seed"]}:
            raise ScienceError("UNDECLARED_PARAMETERS", "Fitted parameters differ from the locked spec")
        if fit.get("fit_rows") != len(training) or fit.get("tuning_trials") != 0:
            raise ScienceError("FIT_ACCOUNTING", "Wrong training count or undeclared tuning")
        prep = fit.get("preprocessing", {})
        if prep.get("fit_split") != "train" or prep.get("evaluation_fit_rows") != 0 or prep.get("fit_row_ids_sha256") != train_ids_sha:
            raise ScienceError("PREPROCESSING_LEAKAGE", "Preprocessing was not bound to training rows only")
        try:
            imputer_ok = np.allclose(prep.get("imputer_statistics", []), medians, rtol=1e-12, atol=1e-12)
            scaler_ok = (np.allclose(prep.get("scaler_mean", []), mean, rtol=1e-11, atol=1e-11)
                         and np.allclose(prep.get("scaler_scale", []), scale, rtol=1e-11, atol=1e-11)) if fit["method"] == "baseline" else prep.get("scaler_mean") is None and prep.get("scaler_scale") is None
        except (ValueError, TypeError):
            imputer_ok = scaler_ok = False
        if not imputer_ok or not scaler_ok:
            raise ScienceError("PREPROCESSING_LEAKAGE", "Imputer/scaler statistics differ from independent training-only recomputation")
        for name in ["fit_wall_seconds", "fit_cpu_seconds"]:
            if not isinstance(fit.get(name), (int, float)) or not math.isfinite(fit[name]) or fit[name] < 0:
                raise ScienceError("RESOURCE_RECEIPT", "Missing actual finite training timing")
    if actual != expected_fits:
        raise ScienceError("FIT_ACCOUNTING", "All registered seeds and methods must be fitted")
    if receipt.get("environment", {}).get("provider_credentials_present") is not False:
        raise ScienceError("WORKER_ENVIRONMENT", "Worker not attested free of provider credentials")
    if receipt.get("cpu_seconds", math.inf) > NUMERICAL_SPEC["worker"]["cpu_seconds"] + 1:
        raise ScienceError("RESOURCE_RECEIPT", "Worker exceeded registered CPU envelope")


def verify_predictions(request):
    root = Path(request["root"]).resolve()
    prepared, manifest = load_prepared(root)
    contract = validate_contract(request["contract"], prepared)
    phase = request["phase"]
    if phase not in ["reproduction", "discovery", "confirmation"]:
        raise ScienceError("INVALID_PHASE", "Unknown verification phase")
    split = "confirmation" if phase == "confirmation" else "discovery"
    envelope = request["prediction_manifest"]
    receipt = read_json(verify_file(root, envelope["receipt"]))
    prediction_path = verify_file(root, envelope["predictions"])
    conditions = request["condition_ids"]
    if receipt.get("contract_signature") != contract_signature(contract):
        raise ScienceError("CONTRACT_MISMATCH", "Predictions are not bound to this contract")
    if receipt.get("source_code") != prepared["trusted_code"]:
        raise ScienceError("TRUSTED_CODE_CHANGED", "Prediction source differs from prepared code")
    if receipt.get("numerical_spec_sha256") != prepared["numerical_spec_sha256"]:
        raise ScienceError("NUMERICAL_SPEC_CHANGED", "Receipt numerical spec changed")
    if receipt.get("split") != split or receipt.get("condition_ids") != conditions:
        raise ScienceError("UNREGISTERED_PREDICTION", "Condition/split does not match requested phase")
    expected = manifest["splits"][split]
    if receipt.get("training_sha256") != manifest["splits"]["train"]["features"]["sha256"] or receipt.get("evaluation_sha256") != expected["features"]["sha256"]:
        raise ScienceError("SPLIT_LEAKAGE", "Receipt does not bind exact training/evaluation data")
    if receipt.get("predictions", {}).get("sha256") != envelope["predictions"]["sha256"]:
        raise ScienceError("ARTIFACT_TAMPERED", "Prediction bytes differ from their receipt")
    task_path = verify_file(root, envelope["input_manifest"])
    task = read_json(task_path)
    if file_hash(task_path) != receipt.get("input_manifest_sha256"):
        raise ScienceError("ARTIFACT_TAMPERED", "Prediction capsule differs from the worker receipt")
    if task.get("split") != split or task.get("condition_ids") != conditions or task.get("contract_signature") != contract_signature(contract):
        raise ScienceError("UNREGISTERED_PREDICTION", "Predictor capsule does not match the registered plan")
    for role, split_name, header in [("training", "train", ["row_id", "block_id", *FEATURES, "target"]),
                                      ("evaluation", split, ["row_id", "block_id", *FEATURES])]:
        name = task.get(role, {}).get("name", "")
        if not name or Path(name).name != name:
            raise ScienceError("PREDICTOR_INPUT_SCHEMA", "Unexpected capsule filename")
        path = task_path.parent / name
        expected_sha = manifest["splits"][split_name]["features"]["sha256"]
        if file_hash(path) != expected_sha or task[role].get("sha256") != expected_sha:
            raise ScienceError("PREDICTOR_INPUT_SCHEMA", "Capsule differs from the exact training or unlabeled evaluation file")
        _read_csv(path, header)
    if phase == "confirmation":
        registration = read_json(root / "confirmation-registration.json")
        body = {key: value for key, value in registration.items() if key != "sha256"}
        if registration.get("sha256") != digest(body) or registration.get("contract_signature") != contract_signature(contract) or registration.get("confirmation_split_sha256") != prepared["confirmation_split_sha256"]:
            raise ScienceError("REGISTRATION_TAMPERED", "Frozen confirmation registration changed")
        if conditions != [registration["condition_id"]] or envelope.get("registration_sha256") != registration["sha256"]:
            raise ScienceError("UNREGISTERED_PREDICTION", "Predictions differ from once-registered confirmation")
    _check_preprocessing(root, manifest, receipt)
    label_rows = _read_csv(verify_file(root, expected["labels"]), ["row_id", "target"])
    if len(label_rows) != expected["rows"] or len({r["row_id"] for r in label_rows}) != len(label_rows):
        raise ScienceError("SEALED_LABEL_COVERAGE", "Wrong or duplicate sealed label rows")
    try:
        labels = {row["row_id"]: int(row["target"]) for row in label_rows}
    except ValueError as exc:
        raise ScienceError("SEALED_LABEL_SCHEMA", "Invalid sealed labels") from exc
    expected_ids = set(expected["row_ids"])
    if set(labels) != expected_ids or set(labels.values()) - {0, 1}:
        raise ScienceError("SEALED_LABEL_COVERAGE", "Sealed labels do not cover frozen split")
    fields = ["split", "condition_id", "row_id", "block_id", "seed", "method", "prediction", "probability"]
    rows = _read_csv(prediction_path, fields)
    expected_count = len(expected_ids) * len(conditions) * len(SEEDS) * 2
    if len(rows) != expected_count or receipt.get("row_count") != expected_count or receipt.get("evaluation_rows") != len(expected_ids):
        raise ScienceError("PREDICTION_COUNT", "Prediction or declared sample count is wrong")
    keys, by_group, joined = set(), defaultdict(list), []
    for row in rows:
        try:
            seed, prediction, probability = int(row["seed"]), int(row["prediction"]), float(row["probability"])
        except ValueError as exc:
            raise ScienceError("PREDICTION_SCHEMA", "Invalid numeric prediction field") from exc
        key = (row["condition_id"], row["row_id"], seed, row["method"])
        if key in keys:
            raise ScienceError("DUPLICATE_PREDICTION", "Duplicate condition/row/seed/method")
        keys.add(key)
        if row["split"] != split or row["condition_id"] not in conditions or row["row_id"] not in expected_ids or seed not in SEEDS or row["method"] not in ["candidate", "baseline"]:
            raise ScienceError("PREDICTION_COVERAGE", "Unexpected split, condition, row, seed or method")
        if row["block_id"] != expected["row_blocks"][row["row_id"]]:
            raise ScienceError("BLOCK_TAMPERED", "Block identity differs from split manifest")
        if not math.isfinite(probability) or not 0 <= probability <= 1 or prediction not in [0, 1] or prediction != int(probability >= NUMERICAL_SPEC["threshold"]):
            raise ScienceError("PREDICTION_SCHEMA", "Probability/threshold/prediction mismatch")
        joined.append({**row, "target": labels[row["row_id"]]})
        by_group[(row["condition_id"], row["block_id"], seed, row["method"])].append((labels[row["row_id"]], prediction))
    expected_keys = {(condition, row_id, seed, method) for condition in conditions for row_id in expected_ids for seed in SEEDS for method in ["candidate", "baseline"]}
    if keys != expected_keys:
        raise ScienceError("PREDICTION_COVERAGE", "Predictions do not provide exact paired coverage")
    block_labels, block_rows = defaultdict(set), defaultdict(int)
    for row_id, label in labels.items():
        block = expected["row_blocks"][row_id]
        block_labels[block].add(label)
        block_rows[block] += 1
    usable = sorted(block for block, classes in block_labels.items() if classes == {0, 1})
    excluded = [{"block_id": block, "rows": block_rows[block], "reason": "Single target class; block balanced accuracy undefined"}
                for block in sorted(block_rows) if block not in usable]
    lookup = {c["id"]: c for c in CONDITIONS}
    observations, summaries, block_tables = [], {}, []
    case = case_metadata(prepared["adapter_id"])
    for condition_id in conditions:
        candidate_scores, baseline_scores, effects = [], [], []
        seed_effects = {seed: [] for seed in SEEDS}
        for block in usable:
            candidates, baselines = [], []
            for seed in SEEDS:
                scores = {}
                for method in ["candidate", "baseline"]:
                    pairs = by_group[(condition_id, block, seed, method)]
                    scores[method] = balanced_accuracy([p[0] for p in pairs], [p[1] for p in pairs])
                candidates.append(scores["candidate"])
                baselines.append(scores["baseline"])
                seed_effects[seed].append(scores["candidate"] - scores["baseline"])
                block_tables.append({"condition_id": condition_id, "block_id": block, "seed": seed,
                                     "candidate": scores["candidate"], "baseline": scores["baseline"],
                                     "effect": scores["candidate"] - scores["baseline"], "rows": block_rows[block]})
            candidate, baseline = statistics.fmean(candidates), statistics.fmean(baselines)
            candidate_scores.append(candidate)
            baseline_scores.append(baseline)
            effects.append(candidate - baseline)
        summary = summarize_effects(effects, contract["practical_delta"])
        summaries[condition_id] = summary
        warnings = ["Seeds describe training variability, averaged within blocks; they are not independent sampling units."]
        if len(usable) < 6:
            warnings.append(f"Only {len(usable)} usable blocks; protocol minimum is 6.")
        if not case["independence_established"]:
            warnings.append("Adjacent-day independence unestablished: CI/p-values are descriptive conditional diagnostics and verdict remains inconclusive.")
        if excluded:
            warnings.append(f"{len(excluded)} single-class blocks ({sum(b['rows'] for b in excluded)} rows) excluded by the preregistered metric; every row still has predictions.")
        if summary["degenerate"]:
            warnings.append("Uncertainty undefined or degenerate; no equivalence inference.")
        observations.append({
            "id": digest({"phase": phase, "condition": condition_id, "predictions": envelope["predictions"]["sha256"], "contract": contract_signature(contract)})[:24],
            "phase": phase, "condition_id": condition_id, "condition_label": lookup[condition_id]["label"], "scope": lookup[condition_id]["scope"],
            "candidate": statistics.fmean(candidate_scores) if candidate_scores else None,
            "baseline": statistics.fmean(baseline_scores) if baseline_scores else None,
            "effect": summary["effect"], "ci_low": summary["ci_low"], "ci_high": summary["ci_high"],
            "blocks": len(usable), "total_blocks": len(block_rows), "rows": len(expected_ids),
            "analyzed_rows": sum(block_rows[block] for block in usable), "excluded_blocks": excluded,
            "seeds": list(SEEDS), "seed_effects": [{"seed": seed, "effect": statistics.fmean(values) if values else None} for seed, values in seed_effects.items()],
            "unit": case["unit"], "interval_method": "95% descriptive Student t interval over seed-averaged usable block effects; not multiplicity adjusted", "warning": warnings,
        })
    return _persist_result(root, request, prepared, receipt, observations, summaries, block_tables, joined, fields, case, lookup)


def _persist_result(root, request, prepared, receipt, observations, summaries, block_tables, joined, fields, case, lookup):
    phase, envelope, contract = request["phase"], request["prediction_manifest"], request["contract"]
    checks = [{"name": name, "passed": True, "detail": detail} for name, detail in [
        ("Source and split hashes", "Pinned source data, sealed labels, frozen split and fixed numerical specification match their envelopes"),
        ("Separate verifier process", f"Verifier PID {os.getpid()}, predictor PID {receipt['pid']}; same OS identity, no external scientific review"),
        ("Exact paired row coverage", "All expected rows × seeds × methods × conditions exactly once, including every single-class block"),
        ("Training-only preprocessing", "Independent training-median/scaler recomputation agrees; zero evaluation-fit rows attested"),
        ("Methods and resources", "Every seed/method accounted, fixed parameters, no tuning, actual training/resource receipts, no provider credentials in worker environment"),
        ("Independent metric implementation", "Binary confusion-count balanced accuracy recomputed without sklearn metrics; seeds averaged within blocks"),
        ("Inference accounting", "Descriptive t interval is separate from Holm's two directional tests; small B/unestablished independence prevent directional conclusions"),
    ]]
    if phase == "confirmation":
        checks.append({"name": "Confirmation preregistration", "passed": True, "detail": "One condition/analysis fingerprint registered before prediction; adaptive second conditions rejected"})
    payload = {"schema_version": "crucible.verified-metrics.v1", "phase": phase,
               "contract_signature": contract_signature(contract), "predictions_sha256": envelope["predictions"]["sha256"],
               "observations": observations, "block_metrics": block_tables,
               "conditional_directional_tests": summaries, "checks": checks,
               "verifier": {"pid": os.getpid(), "at": utc_now(), "source_code": prepared["trusted_code"],
                            "independent_process": os.getpid() != receipt["pid"], "same_os_identity": True}}
    key = digest({"phase": phase, "predictions": envelope["predictions"]["sha256"], "contract": contract_signature(contract)})
    metrics_path = root / "verified" / f"{key}.json"
    if metrics_path.exists():
        old = read_json(metrics_path)
        for name in ["observations", "block_metrics", "conditional_directional_tests"]:
            if old[name] != payload[name]:
                raise ScienceError("REVERIFY_DISAGREEMENT", "Numerical re-verification disagrees with retained evidence")
        payload, checks = old, old["checks"]
    else:
        immutable_json(metrics_path, payload)
    joined_path = root / "verified" / f"{key}-paired-predictions.csv"
    immutable_bytes(joined_path, csv_bytes([*fields, "target"], joined))
    metrics_artifact = artifact(root, metrics_path, "verified_metrics")
    joined_artifact = artifact(root, joined_path, "verified_paired_predictions")
    for observation in observations:
        observation["artifact_sha256"] = metrics_artifact["sha256"]
    result = {"observations": observations, "artifacts": [metrics_artifact, joined_artifact],
              "receipts": [{"id": f"verifier-{key[:16]}", "kind": "verification", "provider": "local CPU",
                            "model": "independent confusion-count metric oracle", "status": "succeeded", "started_at": utc_now(),
                            "purpose": f"{phase} sealed-label verification"}], "metrics": payload}
    if phase == "confirmation":
        condition_id, observation = request["condition_ids"][0], observations[0]
        decision = mechanical_decision(summaries[condition_id], observation["blocks"], case["independence_established"],
                                       lookup[condition_id]["scope"], request.get("reproduction_accepted") is True)
        verification = {
            "status": "verified", "sha256": metrics_artifact["sha256"], "checks": checks,
            "metrics": {"observation": observation, "directional_tests": summaries[condition_id],
                        "comparison_family": "greater and less than practical_delta; Holm across both",
                        "alpha": 0.05, "practical_delta": contract["practical_delta"],
                        "independent_blocks_established": case["independence_established"]},
            "decision": decision,
            "method": "Separate trusted verifier joins sealed labels and recomputes paired metrics under the preregistered block-level rule",
            "independence": "Separate code/process under same OS identity; not external scientific review or a security sandbox",
            "artifact_sha256": metrics_artifact["sha256"],
        }
        titles = {"inconclusive": "The registered test is inconclusive",
                  "supported_in_tested_scope": "Superiority is supported within the tested scope",
                  "boundary_identified": "A sensor-availability boundary is identified",
                  "evidence_against_registered_claim": "Evidence against the registered superiority margin"}
        effect_text = "undefined" if observation["effect"] is None else f"{observation['effect'] * 100:+.2f} percentage points"
        statement = (f"Across {observation['blocks']} usable blocks ({case['unit']}), the seed-averaged candidate-minus-baseline effect was {effect_text}. "
                     + ". ".join(decision["reasons"]) + ".")
        conclusion = {"outcome": decision["outcome"], "title": titles[decision["outcome"]], "statement": statement,
                      "scope": {"condition_id": condition_id, "classification": lookup[condition_id]["scope"],
                                "population": contract["population"], "claim": contract["claim"], "practical_delta": contract["practical_delta"]},
                      "limitations": case["limitations"],
                      "references": [prepared["source"]["url"]] if prepared["source"].get("url") else [], "review": None}
        result.update({"verification": verification, "conclusion": conclusion})
        immutable_json(root / "confirmation-verification.json", {"verification": verification, "conclusion": conclusion,
                                                                  "observations": observations, "artifacts": result["artifacts"]})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        atomic_result(args.output, verify_predictions(read_json(args.request)))
    except ScienceError as exc:
        atomic_result(args.output, exc.as_dict())
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
