#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ $# != 1 || ! "$1" =~ ^[a-z0-9][a-z0-9._:/-]*/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$ ]]; then
  printf 'Usage: %s REGISTRY/IMAGE@sha256:DIGEST\n' "$0" >&2
  exit 2
fi

kubectl kustomize gitops/jobs/iris-training |
  kubectl --kubeconfig=/dev/null set image --local -f - "training=$1" -o json |
  jq -e '.metadata.generateName = (.metadata.name + "-") | del(.metadata.name)'
