"""Trusted prediction worker. This module never imports or reads sealed labels.

Its input capsule contains exactly training labels, unlabeled evaluation sensors,
and a fixed task manifest. It is not a sandbox for arbitrary code. The supervisor
launches a new process with a minimal environment and resource limits.
"""

import argparse
import csv
import hashlib
import io
import os
import platform
import resource
import time
from pathlib import Path

from .common import ScienceError, atomic_result, digest, file_hash, read_json, utc_now
from .spec import BASELINE, CANDIDATE, CONDITIONS, FEATURES, NUMERICAL_SPEC, SEEDS


def dropout_selected(row_id, feature, rate):
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    key = f"{NUMERICAL_SPEC['mask_salt']}|{feature}|{row_id}".encode()
    fraction = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") / 2**64
    return fraction < rate


def _rows(path, training):
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        expected = ["row_id", "block_id", *FEATURES] + (["target"] if training else [])
        if reader.fieldnames != expected:
            raise ScienceError("PREDICTOR_INPUT_SCHEMA", "Predictor accepts training labels and unlabeled evaluation features only")
        rows = list(reader)
    if len({row["row_id"] for row in rows}) != len(rows):
        raise ScienceError("DUPLICATE_ROW", "Duplicate predictor input row IDs")
    return rows


def _state_hash(model, method):
    if method == "candidate":
        states = []
        for estimator in model.estimators_:
            tree = estimator.tree_
            states.append({name: hashlib.sha256(getattr(tree, name).tobytes()).hexdigest()
                           for name in ["children_left", "children_right", "feature", "threshold", "value"]})
        return digest(states)
    return digest({"coef": model.coef_.tolist(), "intercept": model.intercept_.tolist(), "classes": model.classes_.tolist()})


def run_prediction(task_path, output_dir):
    # Imports are intentionally lazy: metadata/prepare do not initialize BLAS.
    import numpy as np
    import scipy
    import sklearn
    import joblib
    import threadpoolctl
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits

    task_path = Path(task_path).resolve()
    capsule = task_path.parent
    task = read_json(task_path)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if task.get("numerical_spec_sha256") != digest(NUMERICAL_SPEC):
        raise ScienceError("NUMERICAL_SPEC_CHANGED", "Task numerical spec does not match trusted worker")
    by_id = {c["id"]: c for c in CONDITIONS}
    condition_ids = task.get("condition_ids")
    if not isinstance(condition_ids, list) or not condition_ids or len(set(condition_ids)) != len(condition_ids) or not set(condition_ids) <= set(by_id):
        raise ScienceError("INVALID_CONDITION", "Prediction condition is outside the fixed lattice")
    for key in ["training", "evaluation"]:
        record = task[key]
        if Path(record["name"]).name != record["name"]:
            raise ScienceError("PREDICTOR_INPUT_SCHEMA", "Capsule paths must be flat filenames")
        if file_hash(capsule / record["name"]) != record["sha256"]:
            raise ScienceError("ARTIFACT_TAMPERED", "Predictor input hash mismatch")
    train = _rows(capsule / task["training"]["name"], True)
    evaluation = _rows(capsule / task["evaluation"]["name"], False)
    if set(r["row_id"] for r in train) & set(r["row_id"] for r in evaluation):
        raise ScienceError("SPLIT_LEAKAGE", "Training and evaluation row identities overlap")
    x_train = np.asarray([[float(row[name]) for name in FEATURES] for row in train])
    y_train = np.asarray([int(row["target"]) for row in train])
    x_evaluation = np.asarray([[float(row[name]) for name in FEATURES] for row in evaluation])
    if set(y_train.tolist()) != {0, 1} or not np.isfinite(x_train).all() or not np.isfinite(x_evaluation).all():
        raise ScienceError("PREDICTOR_INPUT_SCHEMA", "Registered source needs finite sensors and binary training classes")
    started_at, started = utc_now(), time.perf_counter()
    cpu_started = time.process_time()
    fit_receipts = []
    fields = ["split", "condition_id", "row_id", "block_id", "seed", "method", "prediction", "probability"]
    prediction_path = output_dir / "predictions.csv"
    with prediction_path.open("x", newline="") as handle, threadpool_limits(limits=1):
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for seed in SEEDS:
            for method, definition in [("candidate", CANDIDATE), ("baseline", BASELINE)]:
                fit_start, fit_cpu = time.perf_counter(), time.process_time()
                imputer = SimpleImputer(strategy="median")
                x_imputed = imputer.fit_transform(x_train)
                scaler = None
                if method == "candidate":
                    model = RandomForestClassifier(**definition["parameters"], random_state=seed)
                    fit_x = x_imputed
                else:
                    scaler = StandardScaler()
                    fit_x = scaler.fit_transform(x_imputed)
                    model = LogisticRegression(**definition["parameters"], random_state=seed)
                model.fit(fit_x, y_train)
                if method == "baseline" and int(model.n_iter_.max()) >= BASELINE["parameters"]["max_iter"]:
                    raise ScienceError("MODEL_NOT_CONVERGED", "Logistic regression hit its registered iteration limit")
                fit_elapsed = time.perf_counter() - fit_start
                fit_cpu_seconds = time.process_time() - fit_cpu
                preprocessing = {
                    "fit_split": "train", "fit_row_ids_sha256": digest([r["row_id"] for r in train]),
                    "evaluation_fit_rows": 0, "imputer_statistics": imputer.statistics_.tolist(),
                    "scaler_mean": scaler.mean_.tolist() if scaler is not None else None,
                    "scaler_scale": scaler.scale_.tolist() if scaler is not None else None,
                }
                fit_receipts.append({
                    "seed": seed, "method": method, "parameters": {**definition["parameters"], "random_state": seed},
                    "fit_rows": len(train), "tuning_trials": 0, "fit_wall_seconds": fit_elapsed,
                    "fit_cpu_seconds": fit_cpu_seconds, "fitted_state_sha256": _state_hash(model, method),
                    "preprocessing": preprocessing,
                    "iterations": int(model.n_iter_.max()) if method == "baseline" else None,
                })
                for condition_id in condition_ids:
                    condition = by_id[condition_id]
                    values = x_evaluation.copy()
                    if condition["feature"]:
                        index = FEATURES.index(condition["feature"])
                        mask = [dropout_selected(r["row_id"], condition["feature"], condition["rate"]) for r in evaluation]
                        values[np.asarray(mask), index] = np.nan
                    transformed = imputer.transform(values)
                    if scaler is not None:
                        transformed = scaler.transform(transformed)
                    probabilities = model.predict_proba(transformed)[:, int(np.where(model.classes_ == 1)[0][0])]
                    for row, probability in zip(evaluation, probabilities.tolist()):
                        writer.writerow({"split": task["split"], "condition_id": condition_id,
                                         "row_id": row["row_id"], "block_id": row["block_id"],
                                         "seed": seed, "method": method,
                                         "prediction": int(probability >= NUMERICAL_SPEC["threshold"]),
                                         "probability": repr(probability)})
    usage = resource.getrusage(resource.RUSAGE_SELF)
    peak_bytes = int(usage.ru_maxrss if platform.system() == "Darwin" else usage.ru_maxrss * 1024)
    receipt = {
        "schema_version": "crucible.prediction.v1", "started_at": started_at,
        "completed_at": utc_now(), "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu_started, "peak_rss_bytes": peak_bytes,
        "pid": os.getpid(), "parent_pid": os.getppid(),
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
                        "scikit_learn": sklearn.__version__, "joblib": joblib.__version__,
                        "threadpoolctl": threadpoolctl.__version__, "platform": platform.platform(),
                        "machine": platform.machine(), "processor": platform.processor(),
                        "threads": 1, "provider_credentials_present": any("API_KEY" in key or "TOKEN" in key for key in os.environ)},
        "isolation": "Trusted authored worker in a separate local subprocess, minimal environment, CPU/wall/file limits. Same OS identity; not a security sandbox; no arbitrary user imports.",
        "numerical_spec_sha256": digest(NUMERICAL_SPEC), "input_manifest_sha256": file_hash(task_path),
        "contract_signature": task["contract_signature"], "source_code": task["source_code"],
        "training_sha256": task["training"]["sha256"], "evaluation_sha256": task["evaluation"]["sha256"],
        "split": task["split"], "condition_ids": condition_ids,
        "row_count": len(evaluation) * len(condition_ids) * len(SEEDS) * 2,
        "evaluation_rows": len(evaluation), "fit_receipts": fit_receipts,
        "predictions": {"name": prediction_path.name, "sha256": file_hash(prediction_path), "bytes": prediction_path.stat().st_size},
    }
    atomic_result(output_dir / "receipt.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        run_prediction(args.manifest, args.output_dir)
    except ScienceError as exc:
        print(__import__("json").dumps(exc.as_dict()))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
