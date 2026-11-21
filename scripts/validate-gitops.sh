#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
rendered=$(mktemp -d)
trap 'rm -rf -- "$rendered"' EXIT

# An optional directory lets the checks use an existing chart cache.
charts=${LLMOPS_CHART_CACHE:-"$rendered"}
if [[ -z ${LLMOPS_CHART_CACHE-} ]]; then
  helm pull argo-cd --repo https://argoproj.github.io/argo-helm --version 10.17.2 --destination "$charts"
  helm pull cloudnative-pg --repo https://cloudnative-pg.github.io/charts --version 0.29.2 --destination "$charts"
fi
helm lint "$charts/argo-cd-10.17.2.tgz" -f gitops/bootstrap/values.yaml
helm lint "$charts/cloudnative-pg-0.29.2.tgz"
helm template argocd "$charts/argo-cd-10.17.2.tgz" -n argocd --include-crds -f gitops/bootstrap/values.yaml >"$rendered/argocd.yaml"
helm template cloudnative-pg "$charts/cloudnative-pg-0.29.2.tgz" -n cnpg-system --include-crds >"$rendered/cnpg.yaml"
python3 scripts/validate-gitops.py "$rendered/argocd.yaml" "$rendered/cnpg.yaml"
kubeconform -strict -summary -kubernetes-version 1.36.0 \
  gitops/apps/argocd/config.yaml gitops/apps/smoke/deployment.yaml
