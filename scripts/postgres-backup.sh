#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/lab-common.sh
source "$(dirname "$0")/lab-common.sh"

[[ $# == 0 ]] || die "Usage: $0"
umask 077
mkdir -p "$BACKUP_DIR"
[[ -d "$BACKUP_DIR" && ! -L "$BACKUP_DIR" ]] || die "Unexpected backup directory."
chmod 700 "$BACKUP_DIR"
prepare_postgres
destination="$BACKUP_DIR/$(date -u +%F_%H%M%S).dump"
mkdir "$destination.lock" || die "Backup name is already in use."
partial="$destination.partial"
trap 'rmdir "$destination.lock"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
[[ ! -e "$destination" && ! -L "$destination" && ! -e "$partial" && ! -L "$partial" ]] || die "Backup already exists."
(
  set -o noclobber
  : >"$partial"
)
trap 'rm -f -- "$partial"; rmdir "$destination.lock"' EXIT
pg pg_dump -w -U postgres -d mlflow -Fc >"$partial"
verify_archive "$partial"
mv -- "$partial" "$destination"
printf '%s\n' "$destination"
