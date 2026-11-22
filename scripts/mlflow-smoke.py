#!/usr/bin/env python3
"""Write a unique smoke run and verify metadata and artifact round trips."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen
from uuid import uuid4


class SmokeFailure(Exception):
    """A diagnostic that is safe to print without a response body or URL."""


def tracking_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise argparse.ArgumentTypeError("Invalid HTTP tracking URL.") from None
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.query
        or parsed.fragment
        or any(char.isspace() for char in value)
        or port == 0
    ):
        raise argparse.ArgumentTypeError("Expected an HTTP(S) tracking URL without credentials, query or fragment.")
    return value.rstrip("/")


def check_health(uri: str) -> None:
    try:
        with urlopen(f"{uri}/health", timeout=5) as response:
            if response.status != 200:
                raise SmokeFailure(f"/health returned HTTP {response.status}.")
    except HTTPError as exc:
        raise SmokeFailure(f"/health returned HTTP {exc.code}.") from None
    except (URLError, OSError) as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        if isinstance(reason, TimeoutError):
            raise SmokeFailure("/health timed out. Check pod readiness and the port-forward.") from None
        if isinstance(reason, ConnectionRefusedError):
            raise SmokeFailure("/health connection refused. Check pod readiness and the port-forward.") from None
        raise SmokeFailure(f"/health is unreachable ({type(reason).__name__}).") from None


def run_smoke(client) -> dict:
    marker = uuid4().hex
    stage = "create experiment"
    run_id = None
    try:
        experiment_id = client.create_experiment(f"phase-3-smoke-{marker}")
        stage = "create run"
        run = client.create_run(experiment_id)
        run_id = run.info.run_id
        print(f"Smoke experiment_id={experiment_id} run_id={run_id}", file=sys.stderr)
        stage = "verify proxied storage"
        artifact_uri = f"mlflow-artifacts:/{experiment_id}/{run_id}/artifacts"
        if run.info.artifact_uri != artifact_uri:
            raise SmokeFailure("Expected the default proxied artifact URI for this run.")
        stage = "write tracking metadata"
        client.log_param(run_id, "marker", marker, synchronous=True)
        client.log_metric(run_id, "roundtrip", 1.0, synchronous=True)
        with TemporaryDirectory() as directory:
            source = Path(directory) / "probe.txt"
            source.write_text(f"{marker}\n", encoding="utf-8")
            expected_digest = hashlib.sha256(source.read_bytes()).hexdigest()
            stage = "upload artifact"
            client.log_artifact(run_id, str(source))
            source.unlink()
            stage = "download artifact"
            downloaded = Path(client.download_artifacts(run_id, source.name, directory))
            stage = "verify artifact SHA-256"
            if hashlib.sha256(downloaded.read_bytes()).hexdigest() != expected_digest:
                raise SmokeFailure("Artifact SHA-256 mismatch.")

        stage = "finish run"
        client.set_terminated(run_id, status="FINISHED")
        stage = "read back finished run"
        observed = client.get_run(run_id)
        if (
            observed.info.status != "FINISHED"
            or observed.info.artifact_uri != artifact_uri
            or observed.data.params.get("marker") != marker
            or observed.data.metrics.get("roundtrip") != 1.0
        ):
            raise SmokeFailure("Tracking metadata or terminal status did not match.")
    except Exception as exc:
        if run_id is not None:
            try:
                client.set_terminated(run_id, status="FAILED")
            except Exception as cleanup:
                print(f"Could not mark run FAILED ({type(cleanup).__name__}).", file=sys.stderr)
        detail = str(exc) if isinstance(exc, SmokeFailure) else type(exc).__name__
        raise SmokeFailure(f"{stage}: {detail}") from None

    return {
        "experiment_id": experiment_id,
        "run_id": run_id,
        "marker": marker,
        "artifact_uri": artifact_uri,
        "artifact_sha256": expected_digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tracking_uri", type=tracking_url, help="Tracking URL, typically http://127.0.0.1:5000")
    args = parser.parse_args()
    os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"] = "10"
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] = "0"
    os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
    os.environ["MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT"] = "true"
    try:
        from mlflow import MlflowClient
    except ModuleNotFoundError:
        print("MLflow SDK unavailable. Install mlflow-skinny==3.18.0 in a virtual environment.", file=sys.stderr)
        return 1

    try:
        check_health(args.tracking_uri)
        result = run_smoke(MlflowClient(tracking_uri=args.tracking_uri))
    except SmokeFailure as exc:
        print(f"MLflow smoke failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
