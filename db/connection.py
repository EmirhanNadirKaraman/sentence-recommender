"""Read-only Postgres access to the shared language-app database."""
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
