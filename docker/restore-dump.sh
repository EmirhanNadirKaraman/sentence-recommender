#!/bin/bash
# Restore a pg_dump into the fresh database, once.
#
# The official Postgres image runs everything in /docker-entrypoint-initdb.d
# on first boot only — when the data directory is empty. So this runs on
# `docker compose up` the first time and never again; `docker compose down -v`
# is what asks for it a second time.
#
# Deliberately not a download. The dump is 162 MB of someone's corpus and a
# link that fetches it belongs wherever it is shared, not in a public repo.
set -euo pipefail

shopt -s nullglob
dumps=(/dump/*.dump)

if [ ${#dumps[@]} -eq 0 ]; then
  echo "restore-dump: nothing in ./dump — the database is empty."
  echo "restore-dump: build the schema with 'alembic upgrade head', or put a"
  echo "restore-dump: .dump file in ./dump and 'docker compose down -v' to retry."
  exit 0
fi

dump="${dumps[0]}"
echo "restore-dump: restoring ${dump} into ${POSTGRES_DB}"

# --no-owner because the dump names whichever role made it, which is almost
# never the role restoring it. Without it the restore reports an error for
# every object it cannot assign.
pg_restore --no-owner --role="${POSTGRES_USER}" \
           --username="${POSTGRES_USER}" --dbname="${POSTGRES_DB}" \
           --exit-on-error "${dump}"

echo "restore-dump: done"
