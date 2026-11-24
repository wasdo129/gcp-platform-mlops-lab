"""Train a deterministic Iris classifier and log it to the configured MLflow server."""

import hashlib
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import sklearn
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException
from sklearn.datasets import load_iris
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from skops.io import dump

SEED = 42
TEST_SIZE = 0.2
MAX_ITER = 200
EXPERIMENT = "phase-4-iris"


def quality(expected, predicted):
    return {
        "accuracy": float(accuracy_score(expected, predicted)),
        "macro_f1": float(f1_score(expected, predicted, average="macro", zero_division=0)),
    }


def train():
    dataset = load_iris()
    x_train, x_test, y_train, y_test = train_test_split(
        dataset.data, dataset.target, test_size=TEST_SIZE, random_state=SEED, stratify=dataset.target
    )
    model = LogisticRegression(max_iter=MAX_ITER, random_state=SEED).fit(x_train, y_train)
    dataset_digest = hashlib.sha256(
        json.dumps([dataset.data.tolist(), dataset.target.tolist()], separators=(",", ":")).encode()
    ).hexdigest()
    report = {
        "dataset": "sklearn.datasets.load_iris",
        "dataset_sha256": dataset_digest,
        "features": dataset.feature_names,
        "classes": dataset.target_names.tolist(),
        "train_rows": len(x_train),
        "test_rows": len(x_test),
        "metrics": quality(y_test, model.predict(x_test)),
    }
    return model, report


def run_training(client):
    experiment = client.get_experiment_by_name(EXPERIMENT)
    if experiment is not None:
        experiment_id = experiment.experiment_id
    else:
        try:
            experiment_id = client.create_experiment(EXPERIMENT)
        except MlflowException as exc:
            if exc.error_code != "RESOURCE_ALREADY_EXISTS":
                raise
            experiment_id = client.get_experiment_by_name(EXPERIMENT).experiment_id

    run = client.create_run(experiment_id)
    run_id = run.info.run_id
    try:
        if run.info.artifact_uri != f"mlflow-artifacts:/{experiment_id}/{run_id}/artifacts":
            raise RuntimeError("Expected the lab's proxied MLflow artifact store.")
        model, report = train()
        params = {
            "algorithm": type(model).__name__,
            "sklearn_version": sklearn.__version__,
            "random_seed": SEED,
            "test_size": TEST_SIZE,
            "max_iter": MAX_ITER,
            "solver": model.solver,
            "dataset": report["dataset"],
            "dataset_sha256": report["dataset_sha256"],
        }
        for name, value in params.items():
            client.log_param(run_id, name, value, synchronous=True)
        for name, value in report["metrics"].items():
            client.log_metric(run_id, name, value, synchronous=True)
        with TemporaryDirectory() as directory:
            dump(model, Path(directory) / "model.skops")
            (Path(directory) / "training-report.json").write_text(json.dumps(report, indent=2) + "\n")
            client.log_artifacts(run_id, directory)
        client.set_terminated(run_id, status="FINISHED")
        if client.get_run(run_id).info.status != "FINISHED":
            raise RuntimeError("MLflow did not confirm a FINISHED run.")
    except Exception:
        try:
            client.set_terminated(run_id, status="FAILED")
        except Exception:
            print("Could not mark the run FAILED.", file=sys.stderr)
        raise
    return {"run_id": run_id, "experiment_id": experiment_id, "metrics": report["metrics"]}


def main():
    try:
        print(json.dumps(run_training(MlflowClient(tracking_uri=os.environ["MLFLOW_TRACKING_URI"]))))
    except Exception as exc:
        print(f"Iris training failed ({type(exc).__name__}).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
