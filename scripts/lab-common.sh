#!/usr/bin/env bash

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PROJECT=project-557b18ac-4cdc-4a40-b3e
REGION=europe-west3
ZONE=europe-west3-a
CLUSTER=llmops-lab
CONTEXT="gke_${PROJECT}_${ZONE}_${CLUSTER}"
CLUSTER_ID="projects/$PROJECT/locations/$ZONE/clusters/$CLUSTER"
NAMESPACE=ml-platform
PG_CLUSTER=mlflow-postgres
LAB_DIR=${LLMOPS_RUNTIME_DIR:-"$HOME/.llmops-lab"}
BACKUP_DIR=${LLMOPS_BACKUP_DIR:-"$HOME/llmops-backups/postgresql"}
export KUBECONFIG="$LAB_DIR/lab.kubeconfig"
# Keep CLI environment overrides from injecting Terraform init/plan arguments.
unset TF_CLI_ARGS TF_CLI_ARGS_init TF_CLI_ARGS_plan TF_CLI_ARGS_apply TF_CLI_ARGS_show
export TF_WORKSPACE=default
export TF_DATA_DIR="$REPO/infra/terraform/gke-lab/.terraform"

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

require_commands() {
  local name
  for name in "$@"; do
    command -v "$name" >/dev/null || die "Missing executable: $name"
  done
}

check_project() {
  [[ $(gcloud config get-value project) == "$PROJECT" ]] ||
    die "Select gcloud project $PROJECT before running this script."
}

confirm() {
  local expected=$1 reply
  printf 'Type %s to continue: ' "$expected" >/dev/tty
  IFS= read -r reply </dev/tty
  [[ "$reply" == "$expected" ]] || die "Cancelled."
}

k() {
  kubectl --context "$CONTEXT" "$@"
}

check_target() {
  local endpoint server
  require_commands gcloud kubectl jq gke-gcloud-auth-plugin
  check_project
  [[ $(kubectl config current-context) == "$CONTEXT" ]] || die "Unexpected lab kubeconfig context."
  endpoint=$(gcloud container clusters describe "$CLUSTER" --project="$PROJECT" --zone="$ZONE" \
    --format='value(controlPlaneEndpointsConfig.dnsEndpointConfig.endpoint)')
  server=$(k config view --minify -o json | jq -er '.clusters[0].cluster.server')
  [[ -n "$endpoint" && "$server" == "https://$endpoint" ]] ||
    die "Kubeconfig endpoint does not match the GKE DNS endpoint."
}

prepare_postgres() {
  check_target
  k get namespace "$NAMESPACE" >/dev/null
  PRIMARY=$(k -n "$NAMESPACE" get cluster.postgresql.cnpg.io "$PG_CLUSTER" -o json |
    jq -er --arg name "$PG_CLUSTER" '
      select(.spec.bootstrap.initdb.database == "mlflow" and .spec.bootstrap.initdb.owner == "mlflow")
      | .status.currentPrimary | select(type == "string" and startswith($name + "-"))')
  k -n "$NAMESPACE" wait --for=condition=Ready "pod/$PRIMARY" --timeout=30s >&2
  [[ $(sql postgres 'SELECT pg_is_in_recovery()') == f ]] || die "CNPG pod is not writable primary."
}

pg() {
  # CNPG's postgres container supports local peer authentication over the Unix socket.
  k -n "$NAMESPACE" exec -i "$PRIMARY" -c postgres -- "$@"
}

sql() {
  pg psql -X -w -U postgres -d "$1" -At -v ON_ERROR_STOP=1 -c "$2"
}

database_identity() {
  sql postgres "SELECT system_identifier || ':' || oid
                FROM pg_control_system(), pg_database WHERE datname = 'mlflow'"
}

freeze_writes() {
  printf 'Closing mlflow to non-superuser connections and draining existing clients.\n' >&2
  sql postgres 'ALTER DATABASE mlflow CONNECTION LIMIT 0' >/dev/null
  [[ $(sql postgres "SELECT COALESCE(bool_and(pg_terminate_backend(pid, 5000)), true)
                      FROM pg_stat_activity WHERE datname = 'mlflow' AND backend_type = 'client backend'") == t ]] ||
    die "A database client could not be terminated. Database remains closed."
  assert_frozen
}

assert_frozen() {
  [[ $(sql postgres "SELECT datconnlimit = 0 AND NOT EXISTS
                           (SELECT FROM pg_stat_activity WHERE datname = 'mlflow' AND backend_type = 'client backend')
                        AND NOT EXISTS (SELECT FROM pg_prepared_xacts WHERE database = 'mlflow')
                      FROM pg_database WHERE datname = 'mlflow'") == t ]] ||
    die "Database write gate verification failed."
}

verify_archive() {
  [[ -f "$1" && -s "$1" && ! -L "$1" ]] || die "Expected a regular non-empty dump: $1"
  pg pg_restore --format=custom --list <"$1" >/dev/null || die "Invalid dump table of contents: $1"
  # Read every archived data stream and check decompression as well as the TOC.
  pg pg_restore --format=custom --file=/dev/null <"$1"
}

check_terraform() {
  require_commands terraform jq
  [[ $(terraform version -json | jq -er .terraform_version) == 1.17.2 ]] ||
    die "Terraform 1.17.2 is required."
}

tf() {
  terraform -chdir="$REPO/infra/terraform/gke-lab" "$@"
}

init_lab_backend() {
  tf init -input=false -reconfigure -lockfile=readonly \
    -backend-config="bucket=$PROJECT-llmops-tfstate" -backend-config="prefix=llmops/gke-lab"
}

begin_lifecycle() {
  umask 077
  mkdir -p "$LAB_DIR"
  [[ -d "$LAB_DIR" && ! -L "$LAB_DIR" ]] || die "Unexpected directory: $LAB_DIR"
  chmod 700 "$LAB_DIR"
  mkdir "$LAB_DIR/lifecycle.lock" || die "Another lab operation may be active."
  WORK_DIR=''
  trap 'if [[ -n "$WORK_DIR" ]]; then rm -rf -- "$WORK_DIR"; fi; rmdir "$LAB_DIR/lifecycle.lock"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  WORK_DIR=$(mktemp -d "$LAB_DIR/operation.XXXXXXXX")
}
