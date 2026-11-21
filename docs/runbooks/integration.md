# Validation and recovery acceptance

## Offline

CI runs Terraform format and backend-disabled validation, Bash syntax, ShellCheck, shfmt, actionlint, yamllint, Helm lint/template, Kubernetes schema validation, and custom-resource schema validation using the pinned charts. Dependency downloads need internet access. These checks need no Google credentials or live Kubernetes API.

## Local PostgreSQL integration

Run `scripts/test-postgres-local.sh` with PostgreSQL 17 server and client executables, expect and jq on PATH. The test starts a disposable server using a private Unix socket and port, creates a restricted application owner, seeds a row, dumps and checks the archive, recreates the database and restores into it. It also verifies corrupt archive rejection, preservation of the prior dump after a failed backup, and refusal to overwrite a populated database. It uses PostgreSQL native tooling and local stub commands for GKE identity and exec. It cannot prove CNPG, DNS endpoint connectivity or cloud deletion. If using Docker for a separate local Kubernetes rehearsal, first confirm the daemon is running. Use a disposable context, a local StorageClass and manual Kubernetes operations. The GKE scripts deliberately reject a local context.

## Opt-in GKE integration

Get separate approvals for foundation creation, lab creation and lab deletion. Read the [controlled deployment runbook](lifecycle.md). Deploy the published revision and initialize an empty database for the first run. Do the following in the dedicated context.

```bash
export KUBECONFIG="$HOME/.llmops-lab/lab.kubeconfig"
kubectl config current-context
kubectl -n ml-platform rollout status deployment/cpu-smoke
kubectl -n ml-platform wait --for=condition=Ready cluster/mlflow-postgres --timeout=90s
primary=$(kubectl -n ml-platform get cluster/mlflow-postgres -o jsonpath='{.status.currentPrimary}')
before=$(kubectl get namespace ml-platform -o jsonpath='{.metadata.uid}')
kubectl -n ml-platform exec -i "$primary" -c postgres -- psql -X -v ON_ERROR_STOP=1 -U postgres -d mlflow <<'SQL'
SET ROLE mlflow;
CREATE TABLE public.lab_recovery_check (id integer PRIMARY KEY, payload text NOT NULL);
INSERT INTO public.lab_recovery_check VALUES (1, 'survived-recreation');
SQL
scripts/gke-down.sh
```

Record the exact verified archive path printed by teardown, its byte count, and the CSI disk handle. Verify the lab cluster is absent and both foundation buckets still exist using read-only gcloud inventory. Obtain explicit approval to recreate GKE. Pass the archive from that teardown.

```bash
archive="$HOME/llmops-backups/postgresql/YYYY-MM-DD_HHMMSS.dump"
scripts/gke-up.sh --allow-public-node-egress "$(git rev-parse HEAD)" "$archive"
after=$(kubectl get namespace ml-platform -o jsonpath='{.metadata.uid}')
test "$before" != "$after"
primary=$(kubectl -n ml-platform get cluster/mlflow-postgres -o jsonpath='{.status.currentPrimary}')
result=$(kubectl -n ml-platform exec "$primary" -c postgres -- psql -X -qAt -v ON_ERROR_STOP=1 \
  -U postgres -d mlflow -c 'SET ROLE mlflow' \
  -c 'SELECT payload FROM public.lab_recovery_check WHERE id = 1')
test "$result" = survived-recreation
```

Record the differing namespace UIDs, exact selected archive and successful row assertion. Verify PostgreSQL accepts the generated application credentials through the internal RW service before connecting MLflow. Test failure handling using an invalid archive on a fresh database and a cancelled destroy confirmation. A standalone restore must reject corrupt input and a second restore into a populated database. Finish with a newly approved backup-aware teardown and reconcile any remaining PDs.

## GPU opt-in

GPU tests start in Phase 6 after separate eligibility, quota, cost and provisioning approval. Neither offline nor local workflows create GCP resources.

## Learning check

Explain how the archive stays consistent during teardown, what can bypass the database connection gate, and which resources can still incur charges after the GKE control plane disappears. Use the two cluster identities and restored row as evidence.
