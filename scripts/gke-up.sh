#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/lab-common.sh
source "$(dirname "$0")/lab-common.sh"
# shellcheck source=scripts/postgres-restore.sh
source "$REPO/scripts/postgres-restore.sh"

[[ $# == 2 || $# == 3 ]] ||
  die "Usage: $0 --allow-public-node-egress GIT_COMMIT_SHA [BACKUP.dump]"
[[ "$1" == --allow-public-node-egress ]] || die "Phase 2 requires explicitly approved public node egress."
revision=$2
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || die "Supply a full GitHub commit SHA."
archive=${3-}
if [[ $# == 3 ]]; then
  [[ -f "$archive" && -s "$archive" && -r "$archive" && ! -L "$archive" ]] ||
    die "Expected a readable, non-empty backup file: $archive"
fi
require_commands gcloud gke-gcloud-auth-plugin kubectl helm jq curl
check_project
check_terraform
begin_lifecycle

# Check GitHub visibility before starting any billable resources.
raw="https://raw.githubusercontent.com/wasdo129/gcp-platform-mlops-lab/$revision"
for manifest in argocd/config.yaml cloudnative-pg/cluster.yaml smoke/deployment.yaml; do
  curl -fsSL --max-time 20 "$raw/gitops/apps/$manifest" -o "$WORK_DIR/source.yaml"
  cmp -s "$WORK_DIR/source.yaml" "$REPO/gitops/apps/$manifest" ||
    die "Local manifest differs from the published revision: $manifest"
done
helm show chart argo-cd --repo https://argoproj.github.io/argo-helm --version 10.17.2 >/dev/null
helm show chart cloudnative-pg --repo https://cloudnative-pg.github.io/charts --version 0.29.2 >/dev/null

gcloud compute machine-types describe e2-standard-2 --project="$PROJECT" --zone="$ZONE" \
  --format='table(name,guestCpus,memoryMb)'
gcloud iam service-accounts describe "gke-lab-nodes@$PROJECT.iam.gserviceaccount.com" --project="$PROJECT" \
  --format='value(email)'
gcloud container clusters list --project="$PROJECT" --format='table(name,location,status)'
init_lab_backend
tf plan -input=false -lock-timeout=30s -var=allow_public_node_egress=true -out="$WORK_DIR/create.tfplan"
# A failed retry must never replace or delete a live database cluster.
tf show -json "$WORK_DIR/create.tfplan" | jq -e '
  all(.resource_changes[]? | select(.mode == "managed");
    .change.actions == ["create"] or .change.actions == ["no-op"])
' >/dev/null || die "Lab up accepts create-only or no-op plans."
confirm "CREATE $PROJECT/$ZONE/$CLUSTER"
tf apply -input=false -lock-timeout=30s "$WORK_DIR/create.tfplan"

[[ ! -L "$KUBECONFIG" ]] || die "Unexpected kubeconfig symlink."
gcloud container clusters get-credentials "$CLUSTER" --project="$PROJECT" --zone="$ZONE" --dns-endpoint
check_target
k get storageclass standard-rwo -o json |
  jq -e '.provisioner == "pd.csi.storage.gke.io" and .volumeBindingMode == "WaitForFirstConsumer"' >/dev/null ||
  die "The expected GKE Persistent Disk CSI StorageClass is unavailable."
k get nodes -L cloud.google.com/gke-nodepool
k create namespace "$NAMESPACE" --dry-run=client -o yaml | k apply -f -

k create namespace argocd --dry-run=client -o yaml | k apply -f -
k apply -f "$REPO/gitops/apps/argocd/config.yaml"
helm upgrade --install argocd argo-cd --repo https://argoproj.github.io/argo-helm \
  --version 10.17.2 --namespace argocd --create-namespace \
  --values "$REPO/gitops/bootstrap/values.yaml" --kube-context "$CONTEXT" \
  --wait --timeout 10m
k wait --for=condition=Established crd/applications.argoproj.io --timeout=90s

apply_app() {
  sed "s/@GIT_REVISION@/$revision/g" "$REPO/gitops/applications/$1.yaml" | k apply -f -
}

wait_app() {
  k -n argocd wait --for=jsonpath='{.status.sync.revision}'="$2" \
    --for=jsonpath='{.status.sync.status}'=Synced \
    --for=jsonpath='{.status.health.status}'=Healthy "application/$1" --timeout=10m
}

apply_app argocd-config
wait_app argocd-config "$revision"
apply_app cpu-smoke
apply_app operator
wait_app cloudnative-pg 0.29.2
k wait --for=condition=Established crd/clusters.postgresql.cnpg.io --timeout=90s
k -n cnpg-system wait --for=condition=Available deployment -l app.kubernetes.io/instance=cloudnative-pg --timeout=180s
# Prove webhook connectivity and readiness before letting Argo sync the custom resource.
for attempt in {1..12}; do
  if k --request-timeout=10s apply --dry-run=server -f "$REPO/gitops/apps/cloudnative-pg/cluster.yaml" >/dev/null; then
    break
  fi
  [[ "$attempt" != 12 ]] || die "CNPG admission dry run failed. Check the webhook and control-plane firewall."
  sleep 5
done
apply_app postgres
wait_app postgres "$revision"
k -n "$NAMESPACE" wait --for=condition=Ready "cluster.postgresql.cnpg.io/$PG_CLUSTER" --timeout=180s
wait_app cpu-smoke "$revision"
k -n "$NAMESPACE" rollout status deployment/cpu-smoke --timeout=120s

prepare_postgres
database_uid=$(k -n "$NAMESPACE" get cluster.postgresql.cnpg.io "$PG_CLUSTER" -o jsonpath='{.metadata.uid}')
database_id=$(database_identity)
[[ -n "$database_uid" && -n "$database_id" ]] || die "Database identity is missing."
initialized=$(k -n "$NAMESPACE" get configmap database-initialized --ignore-not-found -o json)
if [[ -z "$initialized" ]]; then
  if [[ -z "$archive" ]]; then
    # Fixed-width UTC filenames sort chronologically. Bash leaves an unmatched glob intact.
    for candidate in "$BACKUP_DIR"/????-??-??_??????.dump; do
      if [[ -f "$candidate" ]]; then archive=$candidate; fi
    done
  fi
  if [[ -n "$archive" ]]; then
    restore_database "$archive"
  else
    confirm "INITIALIZE EMPTY mlflow"
  fi
  [[ $(sql mlflow 'SELECT current_database()') == mlflow ]] || die "Database connectivity verification failed."
  [[ $(database_identity) == "$database_id" ]] || die "Database identity changed during initialization."
  k -n "$NAMESPACE" create configmap database-initialized \
    --from-literal="clusterUID=$database_uid" --from-literal="databaseID=$database_id"
  sql postgres 'ALTER DATABASE mlflow CONNECTION LIMIT -1' >/dev/null
else
  jq -e --arg uid "$database_uid" --arg id "$database_id" \
    '.data.clusterUID == $uid and .data.databaseID == $id' <<<"$initialized" >/dev/null ||
    die "The database initialization marker belongs to a different CNPG Cluster."
  [[ -z "$archive" ]] || die "Database is already initialized. Explicit restore requires a fresh database."
fi
[[ $(sql postgres "SELECT datconnlimit = -1 FROM pg_database WHERE datname = 'mlflow'") == t ]] ||
  die "Database is closed to clients. Review the recovery runbook."
[[ $(sql mlflow 'SELECT current_database()') == mlflow ]] || die "Database connectivity verification failed."

k get nodes
k -n argocd get applications
k -n "$NAMESPACE" get cluster,pods,pvc
printf 'Database ready. MLflow is scheduled for Phase 3.\n'
