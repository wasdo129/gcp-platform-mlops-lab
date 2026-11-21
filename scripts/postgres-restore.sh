#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/lab-common.sh
source "$(dirname "$0")/lab-common.sh"

[[ $# == 1 ]] || die "Usage: $0 /path/to/backup.dump"
prepare_postgres
verify_archive "$1"
confirm "RESTORE $CLUSTER/$NAMESPACE/mlflow"
freeze_writes

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
  )") == t ]] || die "Target database contains user objects. Database remains closed."

printf 'Restoring trusted archive %s\n' "$1" >&2
pg pg_restore --format=custom -w -U postgres -d mlflow --role=mlflow --single-transaction \
  --exit-on-error --no-owner --no-acl <"$1"
[[ $(sql mlflow 'SELECT current_database()') == mlflow ]] || die "Database connectivity verification failed."
printf 'Restore committed. Verify application data before reopening the database.\n' >&2
