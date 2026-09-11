"""`sync-catalogue` — fill this project's database from another one.

The catalogue began in `german_vocabulary`, which belongs to another project.
This copies it into the database `alembic` manages here, so the queries can
be indexed for the way this program actually reads them.

The source is an argument, not a setting. That is the honest shape: this is
the command that *made* our database, run once, and not a standing link
between two of them. Naming the source in `.env` would suggest a sync you
run on a schedule, and the guard below is there precisely because you must
not.

It is a replacement, not a merge: each table is emptied and refilled. That
was safe while this database was a mirror. It is not safe now — ingestion
writes here, so a video scraped locally exists nowhere upstream, and a
refill would erase it along with its sentences and its words.

So the sync checks first, and refuses when it finds videos here that upstream
has never heard of. `--replace` says to do it anyway; nothing else will.

The transfer is binary `COPY`, both directions. 302,000 sentences carrying
`text[]` and `integer[]` columns go straight from one server to the other
without being escaped, parsed, or turned into Python objects on the way —
which matters here, because building Python objects is the thing this
project keeps discovering is slower than the database.
"""
from __future__ import annotations

import tempfile
from time import perf_counter

import psycopg2

from config import DatabaseConfig
from db import Database, WritableDatabase
from db.progress import CopyProgress

# The surrogate keys the database assigns, and whose sequences therefore have
# to be moved past whatever this copy brings in. `video.video_id` is not one:
# the scraper supplies it. Kept in step with migration 9863bcf8177b.
KEYS: dict[str, str] = {
    "channel": "id",
    "sentence": "sentence_id",
    "word_table": "word_id",
    "phrase_table": "phrase_id",
    "grammar_rule": "rule_id",
    "phrase_blueprint": "blueprint_id",
    "sentence_to_phrase": "id",
    "lemma_override": "id",
}

# Parents first, so a foreign key is never pointed at a row that has not
# arrived yet. The truncate walks this list backwards for the same reason.
TABLES: tuple[str, ...] = (
    "channel", "video", "sentence",
    "word_table", "phrase_table", "grammar_rule",
    # The scraper's own tables (migration 85f526a480c5). Nothing here reads
    # them, but they are part of the catalogue and copying them keeps this
    # database a true copy rather than a partial one.
    "phrase_blueprint", "sentence_to_grammar_rule", "word_to_sentence",
    "sentence_to_phrase", "lemma_override", "video_blacklist",
)


class SyncCatalogueCommand:
    """Copies the catalogue tables from the borrowed database into ours."""

    def run(self, app, source_db: str, tables: tuple[str, ...] = (),
            dry_run: bool = False, replace: bool = False) -> None:
        settings = app.settings
        chosen = self._chosen(tables)
        origin = DatabaseConfig.named(source_db)

        self._not_itself(origin, settings.own)
        self._must_exist(settings)
        with Database(origin) as source, \
                WritableDatabase(settings.own) as target:
            columns = {}
            counts = {}
            for table in chosen:
                columns[table] = self._columns(source, target, table)
                counts[table] = source.rows(
                    f'SELECT count(*) FROM "{table}"')[0][0]

            print(f"{origin.name} -> {settings.own.name}")
            for table in chosen:
                print(f"  {table:<14} {counts[table]:>9,} rows"
                      f"  ({len(columns[table])} columns)")
            local = self._only_here(source, target)
            if local:
                shown = ", ".join(local[:5])
                more = f" and {len(local) - 5} more" if len(local) > 5 else ""
                print(f"\n  {len(local)} video(s) are here and not upstream:"
                      f" {shown}{more}")
            if dry_run:
                print("\nnothing written (--dry-run)")
                return
            if local and not replace:
                raise SystemExit(
                    f"\nrefusing: {len(local)} video(s) exist only here, and a"
                    f" sync would delete them\n  along with their sentences and"
                    f" words. They were scraped into this database, which is\n"
                    f"  the one ingestion writes to now.\n\n"
                    f"  Re-scrape them afterwards, or pass --replace to"
                    f" discard them.")

            # One statement, so the order inside it is Postgres's problem
            # rather than ours. No CASCADE: if a table outside the chosen
            # set points at one inside it, that should stop the sync, not
            # quietly empty something nobody asked about.
            quoted = ", ".join(f'"{t}"' for t in reversed(chosen))
            print(f"\nemptying {len(chosen)} tables…", flush=True)
            with target.cursor() as cur:
                cur.execute(f"TRUNCATE {quoted}")

            total = 0
            for table in chosen:
                started = perf_counter()
                moved = self._copy(source, target, table, columns[table],
                                   settings.own, counts[table])
                total += moved
                print(f"  {table:<14} {moved:>9,} rows"
                      f"  {perf_counter() - started:>6.1f}s", flush=True)

        # Outside the transaction, because VACUUM cannot run inside one.
        print(f"\nanalysing {len(chosen)} tables…", flush=True)
        self._settle(settings, chosen)
        print(f"copied {total:,} rows into {settings.own.name}")

    @staticmethod
    def _only_here(source: Database, target) -> list[str]:
        """Videos this database has and upstream does not.

        The video is the unit a person adds, and everything ingestion writes
        hangs off one — so a video upstream has never seen is the signal that
        a refill would destroy work. Cheap at this size: two id lists.
        """
        upstream = set(source.column("SELECT video_id FROM video"))
        with target.cursor() as cur:
            cur.execute("SELECT video_id FROM video")
            ours = {video for (video,) in cur.fetchall()}
        return sorted(ours - upstream)

    @staticmethod
    def _chosen(tables: tuple[str, ...]) -> tuple[str, ...]:
        if not tables:
            return TABLES
        unknown = sorted(set(tables) - set(TABLES))
        if unknown:
            raise SystemExit(f"not part of the catalogue: {', '.join(unknown)}"
                             f" (known: {', '.join(TABLES)})")
        # Back into dependency order, whatever order they were typed in.
        return tuple(t for t in TABLES if t in set(tables))

    @staticmethod
    def _not_itself(origin, here) -> None:
        """Refuse when the source and the target are the same database.

        Worth a check of its own, because the failure is not an error — it
        is a hang. The target truncates all twelve tables, taking an
        ACCESS EXCLUSIVE lock on each; the source then tries to read one of
        them and waits for a lock that is held by a transaction waiting on
        the source. Postgres sees no deadlock, because the second party is
        blocked in the client rather than on a lock, so it waits forever
        with every table exclusively locked.

        One `--from` typo away.
        """
        if (origin.name, origin.host, origin.port) == (here.name, here.host,
                                                       here.port):
            raise SystemExit(
                f"--from names {origin.name}, which is this project's own "
                f"database.\n  A sync would truncate the tables it is about "
                f"to read from. Name the database\n  to copy out of instead.")

    @staticmethod
    def _must_exist(settings) -> None:
        """Say plainly that the database is missing, before doing any work.

        Checked up front rather than caught around the copy, so a connection
        that drops halfway through a sync is not reported as "run alembic".
        """
        try:
            psycopg2.connect(**settings.own.dsn_kwargs()).close()
        except psycopg2.OperationalError as exc:
            if "does not exist" not in str(exc):
                raise
            raise SystemExit(
                f"no database named {settings.own.name}. Create it once:\n"
                f'  psql -U postgres -c "CREATE DATABASE {settings.own.name}'
                f' OWNER {settings.own.user};"\n'
                f"then `alembic upgrade head` to build the tables."
            ) from exc

    @staticmethod
    def _rekey(target, tables: tuple[str, ...]) -> None:
        """Move each sequence past the ids that were just copied in."""
        with target.cursor() as cur:
            for table in tables:
                column = KEYS.get(table)
                if column is None:
                    continue
                cur.execute(
                    f"SELECT setval(pg_get_serial_sequence(%s, %s),"
                    f'        coalesce(max("{column}"), 0) + 1, false)'
                    f' FROM "{table}"', (table, column))

    @staticmethod
    def _settle(settings, tables: tuple[str, ...]) -> None:
        """`VACUUM ANALYZE` each table, which is not optional after a COPY.

        Two things are missing from a freshly filled table, and both of them
        mislead rather than merely slow:

        The planner has no statistics, so it estimates from defaults. Every
        `EXPLAIN ANALYZE` taken before this runs is measuring a plan chosen
        without knowing the data — which is the one thing that would make an
        index comparison here say the wrong thing.

        The visibility map is unset, and an index-only scan needs it. Without
        it `ix_word_language_tag`, whose whole point is the `INCLUDE` list,
        goes back to the heap for every row and quietly behaves like an
        ordinary index scan.

        Its own connection in autocommit, because VACUUM cannot run inside a
        transaction block and `WritableDatabase` is one by design.
        """
        conn = psycopg2.connect(**settings.own.dsn_kwargs())
        try:
            conn.set_session(autocommit=True)
            with conn.cursor() as cur:
                for table in tables:
                    cur.execute(f'VACUUM ANALYZE "{table}"')
        finally:
            conn.close()

    @staticmethod
    def _columns(source: Database, target, table: str) -> list[str]:
        """The columns to copy: ours, in our order, checked against theirs.

        Driven by the target rather than the source because binary `COPY`
        matches by position, and the two schemas do not agree on it —
        `channel.id` is last in theirs and first in ours. Naming the columns
        explicitly on both sides makes the order ours and the mismatch
        harmless.
        """
        with target.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_schema = 'public' AND table_name = %s"
                " ORDER BY ordinal_position", (table,))
            ours = [name for (name,) in cur.fetchall()]
        if not ours:
            raise SystemExit(
                f"no table `{table}` here — run `alembic upgrade head` first")
        theirs = set(source.column(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = 'public' AND table_name = %s", (table,)))
        missing = [c for c in ours if c not in theirs]
        if missing:
            raise SystemExit(
                f"`{table}` upstream has no {', '.join(missing)} — their "
                f"schema has moved and the migration needs to follow it")
        return ours

    @staticmethod
    def _copy(source: Database, target, table: str, columns: list[str],
              watcher, total: int) -> int:
        """Binary COPY out and straight back in, through a spooled file.

        The file is the simplest thing that works: `copy_expert` wants a
        readable file on the way in and a writable one on the way out, and a
        pipe between them would need a thread whose exceptions have to be
        carried back across. Nothing here is large enough to be worth that.

        Both halves are watched, because both are a single blocking call and
        either can be the slow one — reading 302,000 rows out of a cold table
        or writing them into an indexed one.
        """
        named = ", ".join(f'"{c}"' for c in columns)
        with tempfile.TemporaryFile() as spool:
            pid = source.rows("SELECT pg_backend_pid()")[0][0]
            with source.cursor() as cur, CopyProgress(
                    watcher, pid, f"reading {table}", total):
                cur.copy_expert(
                    f"COPY (SELECT {named} FROM \"{table}\")"
                    f" TO STDOUT (FORMAT binary)", spool)
            spool.seek(0)
            with target.cursor() as cur:
                cur.execute("SELECT pg_backend_pid()")
                pid = cur.fetchone()[0]
                with CopyProgress(watcher, pid, f"writing {table}", total):
                    cur.copy_expert(
                        f'COPY "{table}" ({named}) FROM STDIN (FORMAT binary)',
                        spool)
                # psycopg2 reports -1 for some COPY forms; ask outright
                # rather than printing a negative row count.
                if cur.rowcount >= 0:
                    return cur.rowcount
                cur.execute(f'SELECT count(*) FROM "{table}"')
                return cur.fetchone()[0]
