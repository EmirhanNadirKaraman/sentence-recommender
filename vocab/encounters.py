"""The words you have met watching — the passive half of knowing one.

A subtitle line counts as heard when the player actually played through it
(`app.js` decides that, on the pages that follow a video), and every word
of a heard line is one encounter: the word, the line, the video and when.
Every encounter is logged; the word's *heard level* climbs on a ladder.
The first hearing is rung one; the next counts only once `LADDER[1]` days
have passed since the hearing that was counted, the one after that once
`LADDER[2]` days have, and so on -- a word heard ten times in one evening
is at rung one, a word heard on five days spread over a month is at the
top. The days are SM-2's own, the intervals a card gets when every review
passes, so the passive schedule is the active one. The level never falls:
at the top the word is familiar, and stays so.

Nothing here is knowing. A familiar word is offered first where words are
offered, and a claim on probation that becomes familiar has its active
test called (`srs.scheduler.due_now`); passing that is what confirms it.
Decided 2026-09-22.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from srs.scheduler import CONFIRMATIONS, SM2Scheduler
from state import open_state
from vocab.entry import Unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS encounter (
    id       INTEGER PRIMARY KEY,
    kind     TEXT NOT NULL,
    key      TEXT NOT NULL,
    text     TEXT NOT NULL,
    video_id TEXT,
    at       REAL,
    heard_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_encounter_unit ON encounter (kind, key, heard_at);
CREATE TABLE IF NOT EXISTS heard (
    kind       TEXT NOT NULL,
    key        TEXT NOT NULL,
    level      INTEGER NOT NULL,
    counted_at TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
"""

# Five for both: the top of the ladder, where the word is familiar and the
# active test is called, is as many rungs as a claim needs passes.
ENOUGH = CONFIRMATIONS


def _ladder() -> tuple[float, ...]:
    """Days that must pass after the hearing that set the level before the
    next hearing raises it: the first counts at once, and then the waits
    are the intervals SM-2 gives a card that passes every review -- a day,
    then 2.5, 6.4 and 16.6 days apart, rungs at the earliest on days 0, 1,
    3.5, 10 and 26. Read off the scheduler so the two never drift."""
    scheduler = SM2Scheduler()
    card = scheduler.new_card(Unit.lemma(""), datetime(2000, 1, 1))
    waits = [0.0]
    while len(waits) < ENOUGH:
        waits.append(card.interval_days)
        card = scheduler.review(card, True, card.due_date)
    return tuple(waits)


LADDER = _ladder()


@dataclass(frozen=True)
class Rung:
    """Where a word stands on the ladder, and the hearing that put it there."""
    level: int = 0
    counted_at: datetime | None = None

    @property
    def familiar(self) -> bool:
        return self.level >= ENOUGH

    @property
    def next_from(self) -> datetime | None:
        """When a hearing would raise the level; None at the top, or before
        the first hearing, which counts at once."""
        if self.counted_at is None or self.familiar:
            return None
        return self.counted_at + timedelta(days=LADDER[self.level])


class Encounters:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)

    def add(self, heard: list[tuple[Unit, str, str | None, float | None]],
            now: datetime | None = None) -> None:
        """Many at once: one page sends a batch every few seconds. Every
        line is logged; each word climbs a rung if its time has come."""
        now = now or datetime.now()
        stamp = now.isoformat(timespec="seconds")
        with open_state(self._path) as conn:
            conn.executemany(
                "INSERT INTO encounter (kind, key, text, video_id, at, heard_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [(u.kind, u.key, text, video, at, stamp) for u, text, video, at in heard])
            for unit in {u for u, *_ in heard}:
                row = conn.execute("SELECT level, counted_at FROM heard WHERE kind = ? AND key = ?",
                                   (unit.kind, unit.key)).fetchone()
                level, counted = row or (0, None)
                if level >= ENOUGH:
                    continue
                if counted and now - datetime.fromisoformat(counted) < timedelta(days=LADDER[level]):
                    continue
                conn.execute(
                    "INSERT INTO heard (kind, key, level, counted_at) VALUES (?, ?, ?, ?)"
                    " ON CONFLICT(kind, key) DO UPDATE SET level = excluded.level,"
                    " counted_at = excluded.counted_at",
                    (unit.kind, unit.key, level + 1, stamp))

    def rung(self, unit: Unit) -> Rung:
        with open_state(self._path) as conn:
            row = conn.execute("SELECT level, counted_at FROM heard WHERE kind = ? AND key = ?",
                               (unit.kind, unit.key)).fetchone()
        return Rung(row[0], datetime.fromisoformat(row[1])) if row else Rung()

    def rungs(self) -> dict[Unit, Rung]:
        """Every word that has been heard -- what the panel and the
        scheduler read at once."""
        with open_state(self._path) as conn:
            rows = conn.execute("SELECT kind, key, level, counted_at FROM heard").fetchall()
        return {Unit(kind, key): Rung(level, datetime.fromisoformat(at))
                for kind, key, level, at in rows}

    def count(self, unit: Unit) -> int:
        with open_state(self._path) as conn:
            return conn.execute("SELECT count(*) FROM encounter WHERE kind = ? AND key = ?",
                                (unit.kind, unit.key)).fetchone()[0]

    def lines(self, unit: Unit, limit: int = 5) -> list[dict]:
        """The lines the word was last heard in, newest first, each once."""
        with open_state(self._path) as conn:
            rows = conn.execute(
                "SELECT text, video_id, at, max(heard_at) AS last, count(*) AS times"
                " FROM encounter WHERE kind = ? AND key = ?"
                " GROUP BY text ORDER BY last DESC LIMIT ?",
                (unit.kind, unit.key, limit)).fetchall()
        return [{"text": t, "video": v, "at": at, "last": last, "times": n}
                for t, v, at, last, n in rows]
