#!/usr/bin/env bash
set -eu
umask 077

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    printf 'Usage: %s PROJECT_ID [REGION]\nDefault region: europe-west3\n' "${0##*/}"
    exit 0
fi

if (( $# < 1 || $# > 2 )); then
    printf 'Usage: %s PROJECT_ID [REGION]\n' "${0##*/}" >&2
    exit 1
fi

for dependency in gcloud python3; do
    if ! command -v "$dependency" >/dev/null 2>&1; then
        printf 'Required command unavailable: %s\n' "$dependency" >&2
        exit 1
    fi
done

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
exec python3 "$script_dir/gcp-audit-report.py" "$1" "${2:-europe-west3}"
