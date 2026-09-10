"""Words set aside without claiming to know them.

"Not yet" used to be a set on the viewer, which meant it was not a decision at
all: the branch that handled it wrote nothing, so a word set aside came back
the moment the process restarted. The comment beside it claimed the review
card was the durable record, but a card is minted for every roadmap step
whether you pass it or not, so it recorded nothing about the choice.

Counted in words rather than minutes. Every timestamp in this database is a
naive local one, the app is used in bursts, and a laptop that changes timezone
would silently move every deadline — so an hour is either still in this
session or already lost. A count of decisions is monotonic, needs no clock,
and is exactly what "bring it back after twenty other words" says.

Separate from `cards` on purpose. `due_date` answers "when should I be tested
on this"; this answers "do not offer this yet". They look interchangeable only
because the SRS has never been used and every card is still due immediately —
the first real review would push a card's date forward and silently take that
word out of the reading page.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from state import open_state
from vocab.entry import Unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS snoozed_units (
    kind      TEXT NOT NULL,
    key       TEXT NOT NULL,
    wake_tick INTEGER NOT NULL,
    times     INTEGER NOT NULL DEFAULT 1,
    snoozed   TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
CREATE INDEX IF NOT EXISTS ix_snoozed_wake ON snoozed_units(wake_tick);

-- Decisions taken, ever. Not a row count and not a clock: a word snoozed at
-- tick 40 with a delay of twenty is asleep until tick 60, whether those twenty
-- decisions take an evening or a fortnight.
CREATE TABLE IF NOT EXISTS study_clock (
    id   INTEGER PRIMARY KEY CHECK (id = 1),
    tick INTEGER NOT NULL
);
INSERT OR IGNORE INTO study_clock (id, tick) VALUES (1, 0);
"""

# How far back a word goes the first time, and the furthest it can ever go.
# The cap is the load-bearing half: doubling without one puts a word skipped
# eight times two and a half thousand decisions away, which is the "lost for
# good" outcome that snoozing exists to avoid.
DELAY = 20
CAP = 200


class SnoozeStore:
    """Which words are set aside, and until when."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)

    # --- the clock --------------------------------------------------------

    def tick(self) -> int:
        with open_state(self._path) as conn:
            return self._tick(conn)

    @staticmethod
    def _tick(conn) -> int:
        row = conn.execute("SELECT tick FROM study_clock WHERE id = 1").fetchone()
        return row[0] if row else 0

    def advance(self) -> int:
        """One decision taken. Called for a word learned as well as one set
        aside — both are "another word", which is what the delay counts."""
        with open_state(self._path) as conn:
            return self._advance(conn)

    @staticmethod
    def _advance(conn) -> int:
        conn.execute("UPDATE study_clock SET tick = tick + 1 WHERE id = 1")
        return SnoozeStore._tick(conn)

    # --- setting aside ----------------------------------------------------

    def snooze(self, unit: Unit, delay: int = DELAY, cap: int = CAP) -> int:
        """Set `unit` aside, and say how many words until it returns.

        Repeats push it further, doubling to `cap`: a word skipped three times
        is one being avoided, and offering it again every twenty words teaches
        you to ignore the page. Bumping the clock, reading it and writing the
        row happen in one transaction — requests arrive on threads, and two
        taps racing the counter would give one of them a delay measured from
        a tick that no longer exists.
        """
        with open_state(self._path) as conn:
            now = self._advance(conn)
            row = conn.execute(
                "SELECT times FROM snoozed_units WHERE kind = ? AND key = ?",
                (unit.kind, unit.key)).fetchone()
            times = (row[0] if row else 0) + 1
            wait = min(delay * 2 ** (times - 1), cap)
            conn.execute(
                "INSERT INTO snoozed_units (kind, key, wake_tick, times, snoozed)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(kind, key) DO UPDATE SET"
                " wake_tick = excluded.wake_tick, times = excluded.times,"
                " snoozed = excluded.snoozed",
                (unit.kind, unit.key, now + wait, times,
                 datetime.now().isoformat(timespec="seconds")),
            )
        return wait

    def wake(self, unit: Unit) -> None:
        """Take it off the shelf now — an undo, or the word being learned.

        Deletes the row rather than expiring it, so `times` resets too. A
        retraction should not leave the word remembering it was avoided.
        """
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM snoozed_units WHERE kind = ? AND key = ?",
                         (unit.kind, unit.key))

    # --- reading ----------------------------------------------------------

    def asleep(self) -> frozenset[Unit]:
        """Everything still set aside, as of right now.

        Read fresh on every request rather than cached on the viewer. It is one
        indexed query over a table of tens of rows, and keeping it in memory is
        the exact bug this replaced.
        """
        with open_state(self._path) as conn:
            return frozenset(
                Unit(kind, key) for kind, key in conn.execute(
                    "SELECT kind, key FROM snoozed_units"
                    " WHERE wake_tick > (SELECT tick FROM study_clock WHERE id = 1)")
            )

    def is_asleep(self, unit: Unit) -> bool:
        with open_state(self._path) as conn:
            row = conn.execute(
                "SELECT 1 FROM snoozed_units WHERE kind = ? AND key = ?"
                " AND wake_tick > (SELECT tick FROM study_clock WHERE id = 1)",
                (unit.kind, unit.key)).fetchone()
        return row is not None

    def pending(self) -> list[tuple[Unit, int]]:
        """What is set aside and how many words each has left, soonest first.

        For the list that lets a mis-swipe be undone after the moment has
        passed.
        """
        with open_state(self._path) as conn:
            now = self._tick(conn)
            rows = conn.execute(
                "SELECT kind, key, wake_tick FROM snoozed_units"
                " WHERE wake_tick > ? ORDER BY wake_tick", (now,)).fetchall()
        return [(Unit(kind, key), wake - now) for kind, key, wake in rows]

    def __len__(self) -> int:
        with open_state(self._path) as conn:
            return conn.execute(
                "SELECT count(*) FROM snoozed_units"
                " WHERE wake_tick > (SELECT tick FROM study_clock WHERE id = 1)"
            ).fetchone()[0]
