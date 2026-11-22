#!/usr/bin/env python3
"""Write a unique smoke run and verify metadata and artifact round trips."""

import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from mlflow import MlflowClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tracking_uri", help="Tracking URL, typically http://127.0.0.1:5000")
    args = parser.parse_args()
    client = MlflowClient(tracking_uri=args.tracking_uri)
    marker = uuid4().hex
    experiment_id = client.create_experiment(f"phase-3-smoke-{marker}")
    run = client.create_run(experiment_id)
    run_id = run.info.run_id
    print(f"Smoke experiment_id={experiment_id} run_id={run_id}", flush=True)

    try:
        if not run.info.artifact_uri.startswith("mlflow-artifacts:/"):
            raise RuntimeError(f"Expected a proxied artifact URI, got {run.info.artifact_uri}")
        client.log_param(run_id, "marker", marker)
        client.log_metric(run_id, "roundtrip", 1.0)
        with TemporaryDirectory() as directory:
            source = Path(directory) / "probe.txt"
            source.write_text(f"{marker}\n", encoding="utf-8")
            expected_digest = hashlib.sha256(source.read_bytes()).hexdigest()
            client.log_artifact(run_id, str(source))
            source.unlink()
            downloaded = Path(client.download_artifacts(run_id, source.name, directory))
            if hashlib.sha256(downloaded.read_bytes()).hexdigest() != expected_digest:
                raise RuntimeError("Artifact SHA-256 mismatch.")

        observed = client.get_run(run_id)
        if observed.data.params.get("marker") != marker or observed.data.metrics.get("roundtrip") != 1.0:
            raise RuntimeError("Tracking metadata round trip failed.")
    except Exception:
        client.set_terminated(run_id, status="FAILED")
        raise
    client.set_terminated(run_id, status="FINISHED")

    print(json.dumps({
        "experiment_id": experiment_id,
        "run_id": run_id,
        "marker": marker,
        "artifact_uri": observed.info.artifact_uri,
        "artifact_sha256": expected_digest,
    }))


if __name__ == "__main__":
    main()
