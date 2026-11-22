#!/usr/bin/env bash

check_mlflow_release() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]] || die "Supply a full GitHub commit SHA."
  [[ "$2" =~ ^[a-z0-9][a-z0-9._:/-]*/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$ ]] ||
    die "Supply a registry image pinned by SHA-256 digest."
}

check_mlflow_source() {
  local manifest raw="https://raw.githubusercontent.com/wasdo129/gcp-platform-mlops-lab/$1"
  for manifest in gitops/apps/mlflow/{deployment,service,service-account,kustomization}.yaml \
    gitops/applications/mlflow.yaml; do
    curl -fsSL --max-time 20 "$raw/$manifest" -o "$WORK_DIR/mlflow-source.yaml"
    cmp -s "$WORK_DIR/mlflow-source.yaml" "$REPO/$manifest" ||
      die "Local MLflow manifest differs from the published revision: $manifest"
  done
}

rollout_mlflow() {
  local revision=$1 image=$2 uid id
  prepare_postgres
  uid=$(k -n "$NAMESPACE" get cluster.postgresql.cnpg.io "$PG_CLUSTER" -o jsonpath='{.metadata.uid}')
  id=$(database_identity)
  [[ -n "$uid" && -n "$id" ]] || die "Database identity is missing."
  k -n "$NAMESPACE" get configmap database-initialized -o json |
    jq -e --arg uid "$uid" --arg id "$id" '.data.clusterUID == $uid and .data.databaseID == $id' >/dev/null ||
    die "MLflow requires the initialized database for this CNPG cluster."
  [[ $(sql postgres "SELECT datconnlimit FROM pg_database WHERE datname = 'mlflow'") == -1 ]] ||
    die "Database is closed to clients. See docs/runbooks/lifecycle.md before resuming MLflow."

  sed -e "s/@GIT_REVISION@/$revision/g" -e "s|@MLFLOW_IMAGE@|$image|g" \
    "$REPO/gitops/applications/mlflow.yaml" | k apply -f -
  # Revert the desired scale override from a cancelled teardown.
  k -n argocd patch application mlflow --type=merge \
    -p '{"spec":{"source":{"kustomize":{"replicas":[{"name":"mlflow","count":1}]}}}}'
  if ! k -n argocd wait --for=jsonpath='{.status.sync.revision}'="$revision" \
    --for=jsonpath='{.status.sync.status}'=Synced \
    --for=jsonpath='{.status.health.status}'=Healthy application/mlflow --timeout=8m ||
    ! k -n "$NAMESPACE" rollout status deployment/mlflow --timeout=360s ||
    ! k -n "$NAMESPACE" get deployment mlflow -o json |
    jq -e --arg image "$image" '.status.observedGeneration == .metadata.generation and
      .spec.replicas == 1 and .status.readyReplicas == 1 and .status.updatedReplicas == 1 and
      any(.spec.template.spec.containers[]; .name == "mlflow" and .image == $image)' >/dev/null; then
    k -n argocd get application mlflow || true
    k -n "$NAMESPACE" get pods -l app=mlflow || true
    die "MLflow rollout incomplete. GKE and PostgreSQL remain in place. Inspect Argo CD and pod events, then retry scripts/mlflow-up.sh."
  fi
  printf 'MLflow rollout ready. Run the SDK smoke test to verify PostgreSQL and GCS.\n'
}
