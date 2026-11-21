#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/lab-common.sh
source "$(dirname "$0")/lab-common.sh"

[[ $# == 0 ]] || die "Usage: $0"
require_commands gcloud shasum
check_project
check_terraform
begin_lifecycle
prepare_postgres
init_lab_backend
[[ $(tf output -raw cluster_id) == "$CLUSTER_ID" ]] || die "Terraform state targets a different cluster."

printf 'Stop client workloads and verify that other administrators have stopped writes.\n' >&2
confirm "QUIESCE $CLUSTER/$NAMESPACE/mlflow"
freeze_writes
archive=$("$REPO/scripts/postgres-backup.sh")
verify_archive "$archive"
checksum=$(shasum -a 256 <"$archive")
assert_frozen
printf 'Verified backup: %s (%s bytes)\n' "$archive" "$(wc -c <"$archive" | tr -d '[:space:]')"

printf '\nRecord the database disk handle for residual checks:\n'
for volume in $(k -n "$NAMESPACE" get pvc -l "cnpg.io/cluster=$PG_CLUSTER" \
  -o 'jsonpath={range .items[*]}{.spec.volumeName}{" "}{end}'); do
  k get pv "$volume" -o 'custom-columns=PV:.metadata.name,HANDLE:.spec.csi.volumeHandle,RECLAIM:.spec.persistentVolumeReclaimPolicy'
done

tf plan -destroy -input=false -lock-timeout=30s -var=allow_public_node_egress=true -out="$PLAN_DIR/destroy.tfplan"
tf show -json "$PLAN_DIR/destroy.tfplan" | jq -e --arg project "$PROJECT" --arg zone "$ZONE" --arg cluster "$CLUSTER" '
  [.resource_changes[]? | select(.change.actions == ["delete"])] as $deletes
  | any($deletes[]; .address == "google_container_cluster.lab" and
      .change.before.project == $project and .change.before.location == $zone and .change.before.name == $cluster)
  and all($deletes[]; .address == "google_container_cluster.lab" or
    .address == "google_container_node_pool.cpu" or .address == "google_compute_firewall.cnpg_webhook" or
    .address == "google_compute_network.lab" or .address == "google_compute_subnetwork.lab")
' >/dev/null || die "Unexpected destructive plan."
confirm "DESTROY $PROJECT/$ZONE/$CLUSTER"
[[ -f "$archive" && ! -L "$archive" && $(shasum -a 256 <"$archive") == "$checksum" ]] ||
  die "The validated backup changed or disappeared."
prepare_postgres
assert_frozen
# Apply exactly the reviewed destroy plan. Foundation is a separate root and state.
tf apply -input=false -lock-timeout=30s "$PLAN_DIR/destroy.tfplan"
remaining=$(gcloud container clusters list --project="$PROJECT" \
  --filter="name=$CLUSTER AND location=$ZONE" --format='value(name)')
[[ -z "$remaining" ]] || die "Cluster remains in GKE inventory."

printf '\nCluster deleted. Compare these inventories with the recorded disk handle and preflight.\n'
gcloud compute disks list --project="$PROJECT" --filter="zone:($ZONE)" --format='table(name,zone,sizeGb,status,users)'
gcloud compute addresses list --project="$PROJECT" --format='table(name,region,address,status)'
gcloud compute networks list --project="$PROJECT" --format='table(name,subnetMode)'
gcloud compute forwarding-rules list --project="$PROJECT" --format='table(name,region,IPAddress,target)'
