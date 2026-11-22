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

## After separate publication and IAM approval

Publish the reviewed branch or merge commit and the Linux AMD64 image to a registry readable by the GKE nodes. Obtain the published image digest. Review the foundation plan for the additive `google_storage_bucket_iam_member.mlflow_artifacts` binding. It grants the `ml-platform/mlflow` Kubernetes identity object read, list, write and delete access on the artifacts bucket. Keep the name-based identity unique to trusted lab clusters within this project. The pod obtains credentials through the GKE metadata server and consumes the CNPG application URI through a Secret reference. PostgreSQL transport requires TLS through libpq. The tracking service is unauthenticated within the lab network. Use localhost port forwarding for operator access and restrict access to the cluster.

Enable MLflow by passing the image digest to the existing lab workflow. On a running, Terraform-managed lab, review the proposed no-op infrastructure plan before proceeding. The script checks PostgreSQL initialization before creating or resuming the Application. Stop and back up writers before changing MLflow versions. Review schema migrations separately.

```bash
export LLMOPS_MLFLOW_IMAGE=REGISTRY/REPOSITORY/mlflow@sha256:IMAGE_DIGEST
scripts/gke-up.sh --allow-public-node-egress "$(git rev-parse HEAD)"
```

Teardown sets the Application's desired replica count to zero and waits for its pods to terminate before taking the PostgreSQL backup. If teardown is cancelled after quiescing the database, verify data and reopen the database using the [lifecycle runbook](lifecycle.md) before rerunning startup with the same image digest.

## Live acceptance

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
