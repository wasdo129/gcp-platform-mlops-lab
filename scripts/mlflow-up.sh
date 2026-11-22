#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/lab-common.sh
source "$(dirname "$0")/lab-common.sh"
# shellcheck source=scripts/mlflow-common.sh
source "$REPO/scripts/mlflow-common.sh"

[[ $# == 2 ]] || die "Usage: $0 GIT_COMMIT_SHA REGISTRY/IMAGE@sha256:DIGEST"
require_commands curl
check_mlflow_release "$1" "$2"
check_target
begin_lifecycle
check_mlflow_source "$1"
rollout_mlflow "$1" "$2"
