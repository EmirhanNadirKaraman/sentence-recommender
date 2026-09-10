"""Postgres access to the shared language-app database.

Reads go through `Database`, whose sessions are opened READ ONLY so a stray
write cannot touch a schema this project does not own. `WritableDatabase` is
the single deliberate exception, used only by video ingestion — see its
docstring for why it is a separate class rather than a flag on the other one.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

import psycopg2

from config import DatabaseConfig


class Database:
    """A single read-only connection, used as a context manager.

    The session is opened `READ ONLY` so a stray INSERT fails loudly rather
    than mutating a schema this project does not own.
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


class WritableDatabase:
    """The one connection allowed to write to the shared catalogue.

    Everything else in this project reads. Adding a video is the exception:
    the sentences have to live in language-app's tables, because that is where
    this project reads them from and a second copy would drift.

    A separate class rather than a flag on `Database`, so the exception is
    visible at every call site. Nothing commits on your behalf — the whole
    video lands or none of it does, so a failure halfway through leaves no
    half-scraped video in the catalogue.
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
