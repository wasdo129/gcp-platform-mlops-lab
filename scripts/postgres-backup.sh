#!/usr/bin/env bash
set -euo pipefail

backup_database() (
  # This function also runs inside a command substitution during teardown.
  set -e
  umask 077
  mkdir -p "$BACKUP_DIR"
  [[ -d "$BACKUP_DIR" && ! -L "$BACKUP_DIR" ]] || die "Unexpected backup directory."
  chmod 700 "$BACKUP_DIR"
  destination="$BACKUP_DIR/$(date -u +%F_%H%M%S).dump"
  partial=$(mktemp "$BACKUP_DIR/.dump.XXXXXXXX.partial")
  trap 'rm -f -- "$partial"' EXIT
  [[ ! -e "$destination" && ! -L "$destination" ]] || die "Backup already exists."
  pg pg_dump -w -U postgres -d mlflow -Fc >"$partial" || die "pg_dump failed."
  verify_archive "$partial" || die "Backup verification failed."
  # Atomic publication without overwriting another valid archive.
  ln -- "$partial" "$destination" || die "Could not publish the verified archive."
  printf '%s\n' "$destination"

)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  # shellcheck source=scripts/lab-common.sh
  source "$(dirname "$0")/lab-common.sh"
  [[ $# == 0 ]] || die "Usage: $0"
  begin_lifecycle
  prepare_postgres
  backup_database
fi
