"""Where a reader's state lives: a schema of their own in the project's Postgres.

Everything a reader has decided and everything derived for them -- the words
they marked known, their cards, their plans, the judge's answers and the
model's glosses they have paid for -- lives in one schema per reader, in the
same database as the catalogue and the corpus: `reader` for the
installation's own, as `data/state.sqlite3` was, and `reader_<name>` for
each reader added since. It
was a SQLite file per reader until there was a server for two people to
share: then one database meant one thing to back up, and a writer from the
web page, one from an MCP client and one from the command line stopped
waiting on a file lock.

Every connection names exactly one schema in its search path and nothing
behind it (see `config.DatabaseConfig.schema`), so a store reads and writes
its reader's tables without saying whose they are, and a table missing from
that schema is an error rather than somebody else's rows.

`open_state` is the shape the SQLite code had -- a connection that answers
`execute` and commits when the block ends -- so the stores read as they did.
The connections come from a small pool per schema: the web server answers on
a thread per request, and opening a socket per query, which is what opening
a SQLite file per query became, costs a round trip each time.
"""
from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager

import psycopg2

# Connections kept per schema. More than the web server's busiest moment
# needs -- a page load and the rescore worker at once -- and far under what
# the server allows (100 by default) with two readers.
POOL_SIZE = 8


class _Pool:
    """Connections to one schema, handed out one per `open_state` block."""

    def __init__(self, config) -> None:
        self._config = config
        self._idle: list = []
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(POOL_SIZE)

    def take(self):
        self._slots.acquire()
        with self._lock:
            conn = self._idle.pop() if self._idle else None
        if conn is None or conn.closed:
            try:
                conn = psycopg2.connect(**self._config.dsn_kwargs())
            except Exception:
                self._slots.release()
                raise
        return conn

    def give(self, conn, broken: bool = False) -> None:
        if broken or conn.closed:
            try:
                conn.close()
            except Exception:                     # noqa: BLE001 — already gone
                pass
        else:
            with self._lock:
                self._idle.append(conn)
        self._slots.release()

    def close(self) -> None:
        with self._lock:
            idle, self._idle = self._idle, []
        for conn in idle:
            conn.close()


_POOLS: dict = {}
_POOLS_LOCK = threading.Lock()
# (schema config, digest of the DDL) already run in this process.
_ENSURED: set = set()
_ENSURE_LOCK = threading.Lock()


def _pool(config) -> _Pool:
    with _POOLS_LOCK:
        pool = _POOLS.get(config)
        if pool is None:
            pool = _POOLS[config] = _Pool(config)
        return pool


class Connection:
    """A psycopg2 connection that answers `execute` with a cursor, as
    sqlite3's did, so `conn.execute(sql, params).fetchall()` still reads."""

    def __init__(self, raw) -> None:
        self.raw = raw

    def execute(self, sql: str, params=None):
        cur = self.raw.cursor()
        # None rather than an empty tuple: given parameters, psycopg2 reads
        # every `%` in the statement as one, `LIKE 'x%'` included.
        cur.execute(sql, params or None)
        return cur

    def executemany(self, sql: str, rows):
        """Many rows, a page of statements per round trip.

        psycopg2's own `executemany` is a round trip per row, which was free
        against a file and is not against a server: a plan's 107,576 example
        rows would be as many trips.
        """
        from psycopg2.extras import execute_batch            # noqa: PLC0415
        cur = self.raw.cursor()
        execute_batch(cur, sql, rows, page_size=1000)
        return cur

    def cursor(self):
        return self.raw.cursor()

    def commit(self) -> None:
        """Commit now, mid-block, as some stores did with SQLite's."""
        self.raw.commit()


@contextmanager
def open_state(config):
    """A connection to `config`'s schema, committed when the block ends and
    rolled back if it raises."""
    pool = _pool(config)
    raw = pool.take()
    broken = False
    try:
        yield Connection(raw)
        raw.commit()
    except BaseException:
        try:
            raw.rollback()
        except Exception:                         # noqa: BLE001 — the socket died
            broken = True
        raise
    finally:
        pool.give(raw, broken=broken)


def ensure(config, ddl: str) -> None:
    """Run a store's `CREATE ... IF NOT EXISTS`, once per process.

    The schema is made first if it is not there -- a reader's is made the
    first time anything of theirs is stored. An advisory lock keyed on the
    schema serialises the DDL, because two processes creating the same table
    at the same moment can both pass `IF NOT EXISTS` and one then fails.
    """
    key = (config, hashlib.sha256(ddl.encode("utf-8")).hexdigest())
    with _ENSURE_LOCK:
        if key in _ENSURED:
            return
    schema = config.schema
    if not schema:
        raise ValueError("a reader's state needs a schema of its own")
    with open_state(config) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (schema,))
        conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        conn.execute(ddl)
    with _ENSURE_LOCK:
        _ENSURED.add(key)


def forget(config) -> None:
    """Close `config`'s connections and forget what was made there -- for a
    schema that is about to be dropped, which is what the tests do."""
    with _POOLS_LOCK:
        pool = _POOLS.pop(config, None)
    if pool is not None:
        pool.close()
    with _ENSURE_LOCK:
        for key in [k for k in _ENSURED if k[0] == config]:
            _ENSURED.discard(key)


def version_trigger(table: str, counter: str, events: str) -> str:
    """DDL for a counter bumped by the database whenever `table` changes.

    SQLite's triggers were three lines each; Postgres wants a function. The
    function keeps the search path it was made under, so it bumps this
    schema's counter whatever path the writing session has.
    """
    name = f"bump_{counter}"
    return f"""
CREATE OR REPLACE FUNCTION {name}() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    UPDATE {counter} SET version = version + 1 WHERE id = 1;
    RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER {table}_changed AFTER {events} ON {table}
FOR EACH ROW EXECUTE FUNCTION {name}();
"""
