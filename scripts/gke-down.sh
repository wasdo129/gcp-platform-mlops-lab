#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/lab-common.sh
source "$(dirname "$0")/lab-common.sh"
# shellcheck source=scripts/postgres-backup.sh
source "$REPO/scripts/postgres-backup.sh"

[[ $# == 0 ]] || die "Usage: $0"
require_commands gcloud shasum
check_project
check_terraform
begin_lifecycle
check_target
init_lab_backend
[[ $(tf output -raw cluster_id) == "$CLUSTER_ID" ]] || die "Terraform state targets a different cluster."

state_addresses=$(tf state list)
[[ "$state_addresses" != *"google_container_node_pool.serving["* ]] ||
  die "Remove the temporary serving pool before platform teardown. See docs/runbooks/qwen-serving.md."
serving_pools=$(gcloud container node-pools list --cluster="$CLUSTER" --zone="$ZONE" --project="$PROJECT" --format=json)
jq -e 'type == "array" and all(.[]; .name != "serving")' <<<"$serving_pools" >/dev/null ||
  die "A serving pool is still live. Reconcile it with Terraform state before teardown."
prepare_postgres

identity=$(database_identity)
[[ -n "$identity" ]] || die "Database identity is missing."
printf 'Stop client workloads and verify that other administrators have stopped writes.\n' >&2
confirm "QUIESCE $CLUSTER/$NAMESPACE/mlflow"
prepare_postgres
[[ $(database_identity) == "$identity" ]] || die "Target database changed during confirmation."
destroy_started=false
teardown_exit() {
  local status=$?
  if ((status != 0)); then
    if "$destroy_started"; then
      printf '\nDestroy started. Inspect GKE and Terraform state before attempting recovery.\n' >&2
    else
      printf '\nDestroy did not start. MLflow may be scaled to zero and PostgreSQL may be closed to clients.\n' >&2
      printf 'Verify recovery, reopen PostgreSQL if needed, then resume MLflow with scripts/mlflow-up.sh. See docs/runbooks/mlflow.md.\n' >&2
    fi
  fi
  cleanup_lifecycle
}
trap teardown_exit EXIT

# Set Argo's desired replica count so self-heal cannot undo the shutdown.
app=$(k -n argocd get application mlflow --ignore-not-found -o json)
if [[ -n "$app" ]]; then
  jq -e --arg ns "$NAMESPACE" '
    .spec.source.path == "gitops/apps/mlflow" and .spec.destination.namespace == $ns
  ' <<<"$app" >/dev/null || die "Unexpected MLflow Application spec."
  k -n argocd patch application mlflow --type=merge \
    -p '{"spec":{"source":{"kustomize":{"replicas":[{"name":"mlflow","count":0}]}}}}'
fi

assert_mlflow_stopped() {
  local deployment pods current_app
  if [[ -n "$app" ]]; then
    current_app=$(k -n argocd get application mlflow -o json) ||
      die "Could not verify the MLflow Application."
    jq -e '
      def stopped: any(.kustomize.replicas[]?; .name == "mlflow" and .count == 0);
      (.spec.source | stopped) and
      (.status.sync.comparedTo.source | stopped) and
      .status.sync.status == "Synced" and .operation == null and
      (.status.operationState.phase != "Running" and .status.operationState.phase != "Terminating")
    ' <<<"$current_app" >/dev/null || return 1
  fi
  deployment=$(k -n "$NAMESPACE" get deployment mlflow --ignore-not-found -o json) ||
    die "Could not check the MLflow Deployment."
  pods=$(k -n "$NAMESPACE" get pods -l app=mlflow -o json) ||
    die "Could not check the MLflow Pods."
  [[ -z "$deployment" ]] || jq -e '.spec.replicas == 0' <<<"$deployment" >/dev/null || return 1
  jq -e '.items | length == 0' <<<"$pods" >/dev/null
}

for attempt in {1..60}; do
  if assert_mlflow_stopped; then
    break
  fi
  [[ -n "$app" ]] || die "An MLflow workload exists without the managed Application."
  [[ "$attempt" != 60 ]] || die "MLflow did not stop. Inspect Argo CD before retrying."
  sleep 2
done
freeze_writes
assert_mlflow_stopped || die "MLflow resumed before backup."
archive=$(backup_database)
verify_archive "$archive"
checksum=$(shasum -a 256 <"$archive")
assert_frozen
printf 'Verified backup: %s (%s bytes)\n' "$archive" "$(wc -c <"$archive" | tr -d '[:space:]')"

printf '\nRecord the database disk handle for residual checks:\n'
for volume in $(k -n "$NAMESPACE" get pvc -l "cnpg.io/cluster=$PG_CLUSTER" \
  -o 'jsonpath={range .items[*]}{.spec.volumeName}{" "}{end}'); do
  k get pv "$volume" -o 'custom-columns=PV:.metadata.name,HANDLE:.spec.csi.volumeHandle,RECLAIM:.spec.persistentVolumeReclaimPolicy'
done

tf plan -destroy -input=false -lock-timeout=30s -var=allow_public_node_egress=true -var=enable_serving_pool=false -out="$WORK_DIR/destroy.tfplan"
tf show -json "$WORK_DIR/destroy.tfplan" | jq -e --arg project "$PROJECT" --arg zone "$ZONE" --arg cluster "$CLUSTER" '
  [.resource_changes[]? | select(.mode == "managed" and .change.actions != ["no-op"])] as $deletes
  | any($deletes[]; .address == "google_container_cluster.lab" and
      .change.before.project == $project and .change.before.location == $zone and .change.before.name == $cluster)
  and all($deletes[]; .change.actions == ["delete"] and (.address == "google_container_cluster.lab" or
    .address == "google_container_node_pool.cpu" or .address == "google_compute_firewall.cnpg_webhook" or
    .address == "google_compute_network.lab" or .address == "google_compute_subnetwork.lab"))
' >/dev/null || die "Unexpected destructive plan."
confirm "DESTROY $PROJECT/$ZONE/$CLUSTER"
[[ -f "$archive" && ! -L "$archive" && $(shasum -a 256 <"$archive") == "$checksum" ]] ||
  die "The validated backup changed or disappeared."
prepare_postgres
[[ $(database_identity) == "$identity" ]] || die "Target database changed since the backup."
assert_frozen
assert_mlflow_stopped || die "MLflow resumed after backup."
# Apply exactly the reviewed destroy plan. Foundation is a separate root and state.
destroy_started=true
tf apply -input=false -lock-timeout=30s "$WORK_DIR/destroy.tfplan"
gcloud container clusters list --project="$PROJECT" --format=json |
  jq -e --arg name "$CLUSTER" --arg location "$ZONE" 'all(.[]; .name != $name or .location != $location)' >/dev/null ||
  die "Could not confirm cluster deletion from GKE inventory."

printf '\nCluster deleted. Compare these inventories with the recorded disk handle and preflight.\n'
gcloud compute disks list --project="$PROJECT" --filter="zone:($ZONE)" --format='table(name,zone,sizeGb,status,users)'
gcloud compute addresses list --project="$PROJECT" --format='table(name,region,address,status)'
gcloud compute networks list --project="$PROJECT" --format='table(name,subnetMode)'
gcloud compute forwarding-rules list --project="$PROJECT" --format='table(name,region,IPAddress,target)'
