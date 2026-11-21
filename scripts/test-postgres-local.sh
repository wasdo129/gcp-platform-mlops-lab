#!/usr/bin/env bash
set -euo pipefail
umask 077
repo=$(cd "$(dirname "$0")/.." && pwd)

for tool in initdb pg_ctl pg_dump pg_restore psql jq expect; do
  command -v "$tool" >/dev/null || {
    printf 'Missing executable: %s\n' "$tool" >&2
    exit 1
  }
done
[[ $(pg_ctl --version) == 'pg_ctl (PostgreSQL) 17.'* ]] || {
  printf 'Use PostgreSQL 17.\n' >&2
  exit 1
}

# Keep the socket path short on macOS. Never connect to an existing PostgreSQL server.
fixture=$(mktemp -d /tmp/llmops-pg.XXXXXXXX)
cleanup() {
  if [[ -f "$fixture/data/postmaster.pid" ]]; then pg_ctl -D "$fixture/data" -m immediate -w stop >/dev/null; fi
  rm -rf -- "$fixture"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
unset PGSERVICE PGSERVICEFILE PGHOSTADDR
export PGHOST="$fixture"
export PGPORT=5432
export LLMOPS_BACKUP_DIR="$fixture/backups"
mkdir "$fixture/bin"
initdb -D "$fixture/data" --username=postgres --auth=trust --no-locale >/dev/null
pg_ctl -D "$fixture/data" -l "$fixture/server.log" \
  -o "-c listen_addresses='' -c unix_socket_directories=$fixture -p $PGPORT" -w start >/dev/null

# Stub the GKE identity and Kubernetes exec transport. All database commands are real.
cat >"$fixture/bin/gcloud" <<'SHIM'
#!/usr/bin/env bash
case "$1 $2" in
  'config get-value') printf '%s\n' project-557b18ac-4cdc-4a40-b3e ;;
  'container clusters') printf '%s\n' local-fixture.gke.invalid ;;
  *) exit 99 ;;
esac
SHIM
cat >"$fixture/bin/kubectl" <<'SHIM'
#!/usr/bin/env bash
set -eu
if [[ ${1-} == --context ]]; then shift 2; fi
if [[ ${1-} == -n ]]; then shift 2; fi
case "$1 $2" in
  'config current-context') printf '%s\n' gke_project-557b18ac-4cdc-4a40-b3e_europe-west3-a_llmops-lab ;;
  'config view') printf '%s\n' '{"clusters":[{"cluster":{"server":"https://local-fixture.gke.invalid"}}]}' ;;
  'get namespace' | 'wait --for=condition=Ready') exit 0 ;;
  'get cluster.postgresql.cnpg.io')
    printf '%s\n' '{"spec":{"bootstrap":{"initdb":{"database":"mlflow","owner":"mlflow"}}},"status":{"currentPrimary":"mlflow-postgres-1"}}'
    ;;
  'exec -i')
    shift 6
    if [[ $1 == pg_dump && ${LLMOPS_TEST_FAIL_DUMP-} == 1 ]]; then printf 'incomplete'; exit 42; fi
    exec "$@"
    ;;
  *) exit 99 ;;
esac
SHIM
printf '#!/usr/bin/env bash\nexit 99\n' >"$fixture/bin/gke-gcloud-auth-plugin"
chmod 700 "$fixture/bin/"*
export PATH="$fixture/bin:$PATH"

psql -X -U postgres -d postgres -v ON_ERROR_STOP=1 -q <<'SQL'
CREATE ROLE mlflow LOGIN;
CREATE DATABASE mlflow OWNER mlflow;
SQL
psql -X -U mlflow -d mlflow -v ON_ERROR_STOP=1 -q <<'SQL'
CREATE TABLE public.lab_recovery_check (id integer PRIMARY KEY, payload text NOT NULL);
INSERT INTO public.lab_recovery_check VALUES (1, 'survived-recreation');
SQL
archive=$("$repo/scripts/postgres-backup.sh")
[[ -s "$archive" ]]
sleep 1
if LLMOPS_TEST_FAIL_DUMP=1 "$repo/scripts/postgres-backup.sh"; then
  printf 'A failed pg_dump unexpectedly succeeded.\n' >&2
  exit 1
fi
shopt -s nullglob
archives=("$LLMOPS_BACKUP_DIR"/*.dump)
partials=("$LLMOPS_BACKUP_DIR"/*.partial)
[[ ${#archives[@]} == 1 && ${archives[0]} == "$archive" && ${#partials[@]} == 0 ]]

psql -X -U postgres -d postgres -v ON_ERROR_STOP=1 -q <<'SQL'
DROP DATABASE mlflow;
CREATE DATABASE mlflow OWNER mlflow;
ALTER DATABASE mlflow CONNECTION LIMIT 0;
SQL
printf 'invalid' >"$fixture/invalid.dump"
if "$repo/scripts/postgres-restore.sh" "$fixture/invalid.dump" >"$fixture/corrupt.log" 2>&1; then
  printf 'Corrupt archive unexpectedly succeeded.\n' >&2
  exit 1
fi
grep -q 'pg_restore: error:' "$fixture/corrupt.log"

restore() {
  expect -f - "$repo/scripts/postgres-restore.sh" "$archive" <<'TCL'
set timeout 30
spawn {*}$argv
expect {
  -exact "Type RESTORE llmops-lab/ml-platform/mlflow to continue: " {
    send -- "RESTORE llmops-lab/ml-platform/mlflow\r"
  }
  eof { exit 98 }
  timeout { exit 97 }
}
expect {
  eof { exit [lindex [wait] 3] }
  timeout { exit 97 }
}
TCL
}

restore
if psql -X -U mlflow -d mlflow -c 'SELECT 1' >"$fixture/login.log" 2>&1; then
  printf 'The restore did not hold the write gate.\n' >&2
  exit 1
fi
grep -q 'too many connections for database' "$fixture/login.log"
if restore >"$fixture/repeat.log" 2>&1; then
  printf 'Restore into a populated database unexpectedly succeeded.\n' >&2
  exit 1
fi
grep -q 'Target database contains user objects' "$fixture/repeat.log"

psql -X -U postgres -d postgres -v ON_ERROR_STOP=1 -q -c 'ALTER DATABASE mlflow CONNECTION LIMIT -1'
result=$(psql -X -U mlflow -d mlflow -v ON_ERROR_STOP=1 -qAt -c \
  'SELECT payload FROM public.lab_recovery_check WHERE id = 1')
[[ "$result" == survived-recreation ]]
printf 'PostgreSQL archive and restore test passed.\n'
