#!/bin/sh
# The app container's first act: make sure the schema exists.
#
# `docker compose up` has two audiences and only one of them was served.
# Someone handed a dump gets the schema and the `alembic_version` row from the
# restore, so this is a no-op. Someone with an empty `dump/` gets a database
# with no tables in it at all — `restore-dump.sh` says so and exits 0, the
# health check goes green in five seconds because there is nothing to restore,
# and `serve` then reaches for `corpus_sentence` on its first line and dies of
# UndefinedTable. Under `restart: unless-stopped` that is a traceback on a
# loop, with the one useful message sitting in the *other* container's log.
#
# `upgrade head` on a database already at head does nothing, so this costs the
# dump path a second and buys the empty path a working schema. What `serve`
# says then is "nothing built yet", which is true and actionable.
set -e

echo "entrypoint: bringing the schema up to head…"
alembic upgrade head

exec "$@"
