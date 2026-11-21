#!/usr/bin/env bash
set -euo pipefail

restore_database() (
  [[ -f "$1" && -s "$1" && ! -L "$1" ]] || die "Expected a regular non-empty dump: $1"
  local staged="$WORK_DIR/restore.dump" identity
  cp -- "$1" "$staged"
  identity=$(database_identity)
  [[ -n "$identity" ]] || die "Database identity is missing."
  verify_archive "$staged"
  confirm "RESTORE $CLUSTER/$NAMESPACE/mlflow"
  prepare_postgres
  [[ $(database_identity) == "$identity" ]] || die "Target database changed during confirmation."

  assert_empty_database
  freeze_writes
  assert_empty_database

  printf 'Restoring trusted archive %s\n' "$1" >&2
  pg pg_restore --format=custom -w -U postgres -d mlflow --role=mlflow --single-transaction \
    --exit-on-error --no-owner --no-acl <"$staged"
  [[ $(sql mlflow 'SELECT current_database()') == mlflow ]] || die "Database connectivity verification failed."
  printf 'Restore committed. Verify application data before reopening the database.\n' >&2
)

assert_empty_database() {
  # Refuse an in-place overwrite. A clean CNPG bootstrap has only system objects and public.
  [[ $(sql mlflow "
  SELECT NOT EXISTS (
    SELECT FROM pg_namespace
    WHERE nspname !~ '^pg_' AND nspname NOT IN ('information_schema', 'public')
    UNION ALL
    SELECT FROM pg_depend
    WHERE refclassid = 'pg_namespace'::regclass AND refobjid = 'public'::regnamespace
    UNION ALL
    SELECT FROM pg_extension WHERE extname <> 'plpgsql'
    UNION ALL
    SELECT FROM pg_largeobject_metadata
  )") == t ]] || die "Target database contains user objects."
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  # shellcheck source=scripts/lab-common.sh
  source "$(dirname "$0")/lab-common.sh"
  [[ $# == 1 ]] || die "Usage: $0 /path/to/backup.dump"
  begin_lifecycle
  prepare_postgres
  restore_database "$1"
fi
