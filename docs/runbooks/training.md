# Phase 4. On-demand Iris training

A CPU-only Job trains scikit-learn logistic regression on the bundled Iris dataset. The job uses a stratified 80/20 split with seed 42, then records the split, dataset fingerprint, scikit-learn version, hyperparameters, test accuracy and macro F1. It logs `training-report.json` and `model.skops` to the existing MLflow tracking service. MLflow proxies artifacts to GCS using its own identity. The training pod uses the internal Service and has no Google credentials or mounted Kubernetes API token.

The Job template is tracked in Git under `gitops/jobs/iris-training`. It is outside every Argo CD Application path. The local renderer injects a published SHA-256 image digest and replaces the template name with `generateName`. Creating the rendered Job is an explicit operator action. Job deadlines, no automatic retry and a one-hour TTL bound its lifetime.

## Phase 4 acceptance record

GKE end-to-end acceptance passed on 24 November 2026 from Git revision `e943a0367c4643f676eb3ed140a6269f64343f1a`.

| Check | Result |
| --- | --- |
| Platform resource optimization | PASS. Effective CPU requests fell from 1915m to 1675m on the 1930m node. |
| Training image publication | PASS. Registry tag `iris-e943a03` resolved to `sha256:421896ca71f69b63f6baaf78711b949d401a97c3d06ccae2cc3be781f5022ca1` with a runnable Linux AMD64 manifest. |
| Training Job | `iris-training-62q5n` completed with exit code 0, 16 seconds of container runtime and 0 restarts. |
| MLflow | Experiment `3`, run `68500034ede741fc8534d88cb253fca7`, status `FINISHED`. |
| Metrics | Accuracy `0.9666666667`, macro F1 `0.9665831245`. Values matched the Job log, SDK and training report. |
| SDK and GCS artifact verification | PASS. Both SHA-256 hashes matched independent GCS reads. |
| Model deserialization and inference | PASS. The skops model required no trusted-type overrides and produced 150 predictions. |
| Platform health after training | PASS. Five Argo CD Applications were Synced and Healthy. PostgreSQL was Ready and MLflow returned HTTP health OK. Both retained their Pod UIDs and zero restarts. MemoryPressure was false. |

| Artifact | SHA-256 |
| --- | --- |
| `model.skops` | `e9000a27c903864b90c08919698e326fc0c241a18716efd7227bd074aea901bc` |
| `training-report.json` | `c37c15271c2c05f63feed085e1bbc0e79108733489dbeb3ac8386035d7e90909` |

## Build and publish after approval

```bash
repository=europe-west3-docker.pkg.dev/project-557b18ac-4cdc-4a40-b3e/llmops-images
gcloud artifacts repositories describe llmops-images --location=europe-west3 \
  --project=project-557b18ac-4cdc-4a40-b3e
image="$repository/iris-training"
tag="iris-$(git rev-parse --short HEAD)"
docker buildx build --platform linux/amd64 --load -t "$image:$tag" apps/training
# After approval to publish:
gcloud auth configure-docker "${repository%%/*}"
docker push "$image:$tag"
digest=$(gcloud artifacts docker images describe "$image:$tag" \
  --project=project-557b18ac-4cdc-4a40-b3e --format='value(image_summary.digest)')
training_image="$image@$digest"
scripts/render-training-job.sh "$training_image" > /tmp/iris-training-job.json
```

The Dockerfile uses Python 3.12 and hash-verified packages for Linux AMD64. CI builds the image and runs unit tests on its native AMD64 runner. Regenerate the lock with the same command used for MLflow in the [MLflow runbook](mlflow.md), substituting the training requirements paths. Use an approved publication identity. The configured GKE node identity pulls from the existing repository.

## Submit and inspect after approval

```bash
export KUBECONFIG="$HOME/.llmops-lab/lab.kubeconfig"
kubectl -n ml-platform get deploy mlflow
kubectl describe node
# After approval to create a training Job:
job=$(kubectl create -f /tmp/iris-training-job.json -o jsonpath='{.metadata.name}')
kubectl -n ml-platform get job "$job"
kubectl -n ml-platform logs -f "job/$job" --pod-running-timeout=2m
kubectl -n ml-platform wait --for=condition=Complete "job/$job" --timeout=6m
```

A successful job reports its run ID, experiment ID and metrics. For failure, inspect `kubectl -n ml-platform describe job "$job"`, events and job logs. A script error exits nonzero. If a run was created, the script attempts to mark it `FAILED`. If the server is unreachable during that attempt, the run can remain open.

## Verify the run and saved model

Forward `svc/mlflow` to localhost as described in the [MLflow runbook](mlflow.md). Use a Python 3.12 environment with the training dependencies. Replace the run ID with the value from the Job log. The commands derive the experiment ID and artifact path from the live run. Use an operator identity with read access to the GCS objects. The training pod only uses the MLflow API.

```bash
export MLFLOW_TRACKING_URI=http://127.0.0.1:5000
export TRAINING_RUN_ID=REPLACE_WITH_RUN_ID
python - <<'PY'
import hashlib
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from mlflow import MlflowClient
from sklearn.datasets import load_iris
from skops.io import get_untrusted_types, load

client = MlflowClient()
run_id = os.environ["TRAINING_RUN_ID"]
run = client.get_run(run_id)
if run.info.status != "FINISHED" or run.info.run_id != run_id:
    raise SystemExit("Expected the requested run to be FINISHED.")
prefix = f"/{run.info.experiment_id}/{run_id}/artifacts"
if run.info.artifact_uri != f"mlflow-artifacts:{prefix}":
    raise SystemExit("Unexpected run artifact URI. Check the tracking server's artifact destination.")
gcs_prefix = "gs://project-557b18ac-4cdc-4a40-b3e-ml-artifacts/mlflow" + prefix
with TemporaryDirectory() as directory:
    downloads = {}
    for name in ("model.skops", "training-report.json"):
        path = Path(client.download_artifacts(run_id, name, directory))
        with path.open("rb") as stream:
            sdk_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        # Independently read the same object with the operator's GCS read access.
        content = subprocess.check_output(["gcloud", "storage", "cat", f"{gcs_prefix}/{name}"])
        gcs_hash = hashlib.sha256(content).hexdigest()
        if sdk_hash != gcs_hash:
            raise SystemExit(f"SHA-256 mismatch: {name}")
        print(f"{name} SHA-256 {sdk_hash}")
        downloads[name] = path

    report = json.loads(downloads["training-report.json"].read_text())
    if report["metrics"] != dict(run.data.metrics):
        raise SystemExit("Report and tracking metrics differ.")
    if get_untrusted_types(file=downloads["model.skops"]):
        raise SystemExit("The model contains unexpected types. Investigate before loading.")
    model = load(downloads["model.skops"])
    print(run.info.run_id, run.info.artifact_uri, run.data.metrics)
    print("Predictions:", model.predict(load_iris().data[:3]).tolist())
PY
```

Run the same create command again for a new Job and a new run in `phase-4-iris`. Save logs and the run ID before the TTL controller removes the Job. With separate cleanup approval, `kubectl -n ml-platform delete job "$job"` removes the Job and pod sooner. MLflow metadata and artifacts persist independently.

## Resources and cost

The Job requests 100m CPU and 320Mi memory, with limits of 500m CPU and 512Mi memory. OpenMP and the supported BLAS backends are limited to one thread. CPU requests reserve scheduler capacity and affect relative CPU shares under contention. The 500m quota caps the container at runtime.

Apply the [single-node CPU budget](gke-resource-budget.md) before submitting a Job. The observed pre-change allocation left only 15m CPU available. Recheck live node allocation and MLflow readiness after rollout, and run one training Job at a time. Check scheduler events if it remains Pending. Memory limits are overcommitted, so retain the memory and restart checks during the run.

The Job shares the existing billed node and does not provision a VM. Image storage and pull traffic, GCS operations and artifact bytes, and the time the lab stays up are the incremental cost drivers.
