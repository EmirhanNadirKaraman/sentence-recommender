"""Which goals have been looked for, and how often without result.

`gather` walks the stranded words in priority order and stops as soon as it
has enough candidates, so the handful at the top are searched every round
and the rest are never searched at all. Ten rounds against 61 stranded
words searched the same six terms each time — two of which, `BGB` and
`kucken`, nothing was ever going to find.

So a word that has been looked for and not found steps aside and lets the
next one have a turn. It is not written off: when every stranded word has
had its turn the slate is wiped and the whole list comes round again, which
is what makes this a rota rather than a blacklist. A word can stop being
unfindable — that is the entire premise of hunting — so nothing here may
refuse it forever.

The same shape as `AttemptLog`, and for the same reason: a round that does
not remember what the last one tried repeats it.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from state import open_state
from vocab.entry import Unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS goal_search (
    kind    TEXT NOT NULL,
    key     TEXT NOT NULL,
    tries   INTEGER NOT NULL DEFAULT 0,
    last    TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
"""

# How many fruitless turns a word gets before it steps aside. Low, because
# stepping aside costs it nothing — the rota brings it back once the others
# have been tried — and because the point is to spread the searching out.
GIVE_UP = 2


class SearchLog:
    """A rota over the goals worth looking for."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)

    def record(self, units) -> None:
        """Say these were looked for, whatever came of it."""
        now = datetime.now().isoformat(timespec="seconds")
        rows = [(u.kind, u.key, now) for u in units]
        if not rows:
            return
        with open_state(self._path) as conn:
            conn.executemany(
                "INSERT INTO goal_search (kind, key, tries, last)"
                " VALUES (?, ?, 1, ?)"
                " ON CONFLICT(kind, key) DO UPDATE SET"
                " tries = tries + 1, last = excluded.last", rows)

    def tried(self) -> dict[Unit, int]:
        with open_state(self._path) as conn:
            return {Unit(kind, key): n for kind, key, n in conn.execute(
                "SELECT kind, key, tries FROM goal_search")}

    def forget(self, units=None) -> None:
        """Start the rota again — for these, or for everything."""
        with open_state(self._path) as conn:
            if units is None:
                conn.execute("DELETE FROM goal_search")
            else:
                conn.executemany(
                    "DELETE FROM goal_search WHERE kind = ? AND key = ?",
                    [(u.kind, u.key) for u in units])

    def rota(self, stuck, give_up: int = GIVE_UP):
        """`stuck`, with the already-tried moved aside — and a note.

        Returns (to search now, how many were set aside). When everything
        has had its turn the slate is wiped and the full list comes back, so
        a word is delayed and never dropped.
        """
        tried = self.tried()
        fresh = [row for row in stuck if tried.get(row[0], 0) < give_up]
        if fresh:
            return fresh, len(stuck) - len(fresh)
        self.forget()
        return list(stuck), 0
