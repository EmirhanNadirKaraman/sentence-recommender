"""Saying something while a long copy runs.

A `COPY` of three hundred thousand rows is a single call that returns when it
is finished and says nothing on the way. That is tolerable for five seconds
and not for five minutes, and the table that takes five minutes is exactly
the one where you want to know it is moving rather than hung.

The row count comes from `pg_stat_progress_copy`, which Postgres maintains
itself for any running COPY. That matters: it is the server's own count of
tuples actually processed, not a guess derived from bytes or elapsed time.
Nothing is inferred and nothing is projected — if this prints 120,000 rows,
the server has written 120,000 rows.

Polled from a second connection, because the one doing the copy is blocked
inside it. The poller only ever reads a statistics view.
"""
from __future__ import annotations

import threading
from time import perf_counter

import psycopg2

# Postgres 14 added the view. Below that there is no exact count to be had,
# so the reporter stays silent rather than inventing one.
NEEDS = 140000


class CopyProgress:
    """Reports a running COPY's row count until told to stop.

    Throttled two ways, because either alone gets it wrong. A row interval
    on its own is unreadable when the rows are fast — 300,000 rows at 50,000
    a second is twenty lines in three seconds. A time interval on its own
    says nothing about whether the work is moving. So a line needs both:
    `every` rows to have passed *and* `gap` seconds since the last one.

    Nothing at all is printed for the first `quiet_for` seconds, so a table
    that copies quickly stays a single line of output.
    """

    def __init__(self, config, pid: int, label: str, total: int = 0,
                 every: int = 10_000, quiet_for: float = 2.0,
                 gap: float = 1.0, interval: float = 0.25) -> None:
        self._config = config
        self._pid = pid
        self._label = label
        self._total = total
        self._every = every
        self._quiet_for = quiet_for
        self._gap = gap
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._printed = False

    def __enter__(self) -> "CopyProgress":
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    @property
    def spoke(self) -> bool:
        """Whether anything was printed — the caller may want a newline."""
        return self._printed

    def _watch(self) -> None:
        started = perf_counter()
        reported, spoke_at = 0, 0.0
        try:
            conn = psycopg2.connect(**self._config.dsn_kwargs())
        except psycopg2.Error:
            return                      # progress is never worth failing over
        try:
            conn.set_session(autocommit=True)
            if conn.server_version < NEEDS:
                return
            while not self._stop.wait(self._interval):
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT tuples_processed FROM pg_stat_progress_copy"
                        " WHERE pid = %s", (self._pid,))
                    row = cur.fetchone()
                if row is None:
                    continue            # not started yet, or already finished
                done, now = row[0], perf_counter()
                if (done - reported < self._every
                        or now - started < self._quiet_for
                        or now - spoke_at < self._gap):
                    continue
                reported, spoke_at = done, now
                self._printed = True
                print(f"      {self._label} {done:>12,}{self._of(done)}"
                      f"  {perf_counter() - started:>6.1f}s", flush=True)
        except psycopg2.Error:
            return
        finally:
            conn.close()

    def _of(self, done: int) -> str:
        """The denominator, when the caller knew one to give."""
        if not self._total:
            return " rows"
        return f" / {self._total:,} rows  {100 * done / self._total:>3.0f}%"
