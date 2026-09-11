"""Postgres access.

Reads go through `Database`, whose sessions are opened READ ONLY.  That began
as a guard around someone else's schema; it is kept now that the schema is
ours because it is still true of almost every caller, and a session that
cannot write is one that cannot corrupt the catalogue by accident.

`WritableDatabase` is the deliberate exception — see its docstring.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

import psycopg2

from config import DatabaseConfig


class Database:
    """A single read-only connection, used as a context manager.

    The session is opened `READ ONLY` so a stray INSERT fails loudly rather
    than quietly changing the catalogue from a path that only meant to read.
    """

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._conn: Any = None

    def __enter__(self) -> "Database":
        if not self._config.name:
            raise RuntimeError(
                "no Postgres configured (DB_NAME is unset) — this machine can "
                "serve what is already cached, but not build or rescrape"
            )
        self._conn = psycopg2.connect(**self._config.dsn_kwargs())
        self._conn.set_session(readonly=True, autocommit=True)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def rows(self, sql: str, params: Sequence[Any] | None = None) -> list[tuple]:
        """Run a query and return every row.  Result sets here are small
        (the whole German corpus is ~40k rows), so streaming buys nothing."""
        if self._conn is None:
            raise RuntimeError("Database used outside its context manager")
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def column(self, sql: str, params: Sequence[Any] | None = None) -> list[Any]:
        """First column of every row."""
        return [row[0] for row in self.rows(sql, params)]

    def cursor(self):
        """A raw cursor, for `COPY ... TO STDOUT`.

        `rows()` cannot express a copy — psycopg2 wants the cursor itself for
        `copy_expert`. This does not widen what the connection may do: the
        session is still `READ ONLY`, so a cursor taken from here fails on a
        write exactly as `rows()` would.
        """
        if self._conn is None:
            raise RuntimeError("Database used outside its context manager")
        return self._conn.cursor()


class WritableDatabase:
    """The connection allowed to write to the catalogue.

    Two callers have it: ingestion, which adds a scraped video, and
    `sync-catalogue`, which refills the tables from upstream. Everything else
    in this project reads.

    A separate class rather than a flag on `Database`, so a write is visible
    at the call site rather than hidden in an argument. Nothing commits on
    your behalf — the whole video lands or none of it does, so a failure
    halfway through leaves no half-scraped video behind.
    """

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self.connection: Any = None

    def __enter__(self) -> "WritableDatabase":
        if not self._config.name:
            raise RuntimeError(
                "no Postgres configured (DB_NAME is unset) — this machine can "
                "serve what is already cached, but not build or rescrape"
            )
        self.connection = psycopg2.connect(**self._config.dsn_kwargs())
        return self

    def __exit__(self, exc_type, *rest: object) -> None:
        if self.connection is None:
            return
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()
        self.connection = None

    def cursor(self):
        if self.connection is None:
            raise RuntimeError("WritableDatabase used outside its context manager")
        return self.connection.cursor()
