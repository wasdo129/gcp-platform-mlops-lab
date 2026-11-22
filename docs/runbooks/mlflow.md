# Phase 3. MLflow Tracking

## Review and validate locally

From the repository root, run the Helm and Kubernetes schema checks:

```bash
scripts/validate-gitops.sh
terraform fmt -check -recursive infra/terraform
for root in infra/terraform/{foundation,gke-lab}; do
  terraform -chdir="$root" init -backend=false -input=false -lockfile=readonly
  terraform -chdir="$root" validate
done
docker buildx build --platform linux/amd64 --load -t llmops-mlflow:3.18.0 apps/mlflow
```

The image contains the hash-locked Python 3.12 Linux dependencies. To regenerate the lock after a reviewed version change, use `uv 0.9.30`:

```bash
uv pip compile --python-version 3.12 --python-platform x86_64-manylinux_2_28 \
  --generate-hashes --no-annotate --no-header \
  -o apps/mlflow/requirements.lock apps/mlflow/requirements.in
```

Run the local image with the same UID and a read-only root filesystem:

```bash
docker run --rm --platform linux/amd64 --entrypoint python llmops-mlflow:3.18.0 \
  -c 'import os, mlflow, psycopg2, google.cloud.storage; assert os.getuid() == 10001; assert mlflow.__version__ == "3.18.0"'
docker run --rm -d --name llmops-mlflow-local --platform linux/amd64 \
  --read-only --tmpfs /tmp:rw,mode=1777 -p 127.0.0.1:15000:5000 \
  llmops-mlflow:3.18.0 --host=0.0.0.0 --workers=1 --serve-artifacts \
  --backend-store-uri=sqlite:////tmp/mlflow.db --artifacts-destination=/tmp/artifacts
curl --retry 20 --retry-connrefused --retry-delay 2 -fsS http://127.0.0.1:15000/health
docker stop llmops-mlflow-local
```

## 1. Publish the reviewed image after approval

Use an approved Docker-format Artifact Registry repository. The operator needs repository writer access and the GKE **node** service account needs repository reader access. The MLflow Kubernetes ServiceAccount is used for GCS. Confirm the repository name and permissions before pushing. Repository creation and permission changes require separate approval if missing.

```bash
project=project-557b18ac-4cdc-4a40-b3e
region=europe-west3
registry_repo=llmops-images  # Replace with the approved existing repository name.
gcloud artifacts repositories describe "$registry_repo" --location "$region" --project "$project"
gcloud auth configure-docker "$region-docker.pkg.dev"
image="$region-docker.pkg.dev/$project/$registry_repo/mlflow"
tag="3.18.0-$(git rev-parse --short HEAD)"
docker buildx build --platform linux/amd64 --load -t "$image:$tag" apps/mlflow
docker push "$image:$tag"
digest=$(gcloud artifacts docker images describe "$image:$tag" --project "$project" \
  --format='value(image_summary.digest)')
printf '%s\n' "$digest" | grep -Eq '^sha256:[0-9a-f]{64}$'
export LLMOPS_MLFLOW_IMAGE="$image@$digest"
```

## 2. Apply bucket IAM after approval

Use the Terraform foundation state that already owns the artifacts bucket. Review the entire plan and proceed only if it adds the two MLflow member grants and makes no unrelated changes. The `ml-platform/mlflow` identity can create, get and list objects in the artifact bucket. Use unique artifact paths because the identity cannot overwrite or delete existing objects. The name-based identity persists across lab clusters in the same workload pool. [Cloud Storage roles](https://docs.cloud.google.com/storage/docs/access-control/iam-roles)

```bash
umask 077
terraform -chdir=infra/terraform/foundation init -input=false -lockfile=readonly
terraform -chdir=infra/terraform/foundation plan -out=mlflow-iam.tfplan
terraform -chdir=infra/terraform/foundation show mlflow-iam.tfplan
# After approving the specific IAM changes in this plan:
terraform -chdir=infra/terraform/foundation apply mlflow-iam.tfplan
```

## 3. Deploy to the existing GKE cluster after approval

Use the published Git SHA checked out locally and the published image digest from step 1. The command uses the lab kubeconfig and checks the initialized PostgreSQL identity before submitting the Argo CD Application. It uses no Terraform. The pod mounts only the CNPG public CA certificate. Libpq verifies both the CA and the CNPG RW service hostname using `verify-full`. The tracking Service is unauthenticated inside the lab network. Keep operator access on localhost with port forwarding.

```bash
scripts/mlflow-up.sh "$(git rev-parse HEAD)" "$LLMOPS_MLFLOW_IMAGE"
```

Teardown waits for Argo CD to reconcile zero desired replicas and for the MLflow pods to disappear before the PostgreSQL backup. If teardown is interrupted before destroy starts, the script reports that MLflow may be paused and the database may still be closed. Verify the cluster and database first, reopen PostgreSQL if needed using the [lifecycle runbook](lifecycle.md), then rerun `scripts/mlflow-up.sh` with the same digest. If destroy started, inspect GKE and Terraform state before any recovery attempt.

## 4. Verify PostgreSQL, GCS and the SDK

In one terminal, forward the internal Service:

```bash
export KUBECONFIG="$HOME/.llmops-lab/lab.kubeconfig"
kubectl -n ml-platform port-forward --address 127.0.0.1 svc/mlflow 5000:5000
```

In another terminal with MLflow 3.18.0 installed, run:

```bash
python scripts/mlflow-smoke.py http://127.0.0.1:5000
```

Record the reported run ID, marker, artifact URI and SHA-256. Verify independently that the metadata and object landed in the configured backends. Use the same lab kubeconfig for the SQL query. Use an authorized operator identity to inspect GCS.

```bash
export KUBECONFIG="$HOME/.llmops-lab/lab.kubeconfig"
run_id=REPLACE_WITH_SMOKE_RUN_ID
experiment_id=REPLACE_WITH_SMOKE_EXPERIMENT_ID
primary=$(kubectl -n ml-platform get cluster/mlflow-postgres -o jsonpath='{.status.currentPrimary}')
kubectl -n ml-platform exec -i "$primary" -c postgres -- \
  psql -X -w -U postgres -d mlflow -v ON_ERROR_STOP=1 -v run_id="$run_id" <<'SQL'
SELECT r.run_uuid, r.status, p.value AS marker, m.value AS roundtrip
FROM runs r
JOIN params p ON p.run_uuid = r.run_uuid AND p.key = 'marker'
JOIN latest_metrics m ON m.run_uuid = r.run_uuid AND m.key = 'roundtrip'
WHERE r.run_uuid = :'run_id';
SQL
gcloud storage cat "gs://project-557b18ac-4cdc-4a40-b3e-ml-artifacts/mlflow/$experiment_id/$run_id/artifacts/probe.txt" \
  | shasum -a 256
```

Expect one SQL row with the reported marker, status `FINISHED` and metric `1`. Expect the GCS content hash to match the SDK download. This is the Phase 3 completion criterion. Cluster recreation and restore of MLflow records are a separate exercise.
