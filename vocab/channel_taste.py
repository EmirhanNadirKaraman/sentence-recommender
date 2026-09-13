"""Whose videos you want more of, and whose you want less.

Kept here rather than on `channel` in the catalogue, which `sync-catalogue`
refills wholesale from the shared database: a column added there would be
truthful until the next sync and then silently gone. This is a preference,
not a fact about the channel, so it lives beside the other things you have
decided — what you know, what you have snoozed, which sentences you hid.

Two states and an absence. Subscribing lifts a channel's videos in the feed;
setting one aside pushes them down. Down, never out: a channel you would
rather not watch can still hold the one video that teaches the word you need,
and the blacklist already exists for material that should not appear at all.
Weights live in `watchability`, beside the other numbers that decide an order.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from state import open_state

UP = "up"
DOWN = "down"
TASTES = frozenset({UP, DOWN})

SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_taste (
    channel_id TEXT PRIMARY KEY,
    taste      TEXT NOT NULL,
    decided    TEXT NOT NULL
);

-- Bumped on every change, so a page can ask whether the order it is holding
-- still reflects what you have said without reading the table itself.
CREATE TABLE IF NOT EXISTS channel_taste_version (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);
INSERT OR IGNORE INTO channel_taste_version (id, version) VALUES (1, 0);

CREATE TRIGGER IF NOT EXISTS channel_taste_set
AFTER INSERT ON channel_taste
BEGIN UPDATE channel_taste_version SET version = version + 1 WHERE id = 1; END;

CREATE TRIGGER IF NOT EXISTS channel_taste_changed
AFTER UPDATE ON channel_taste
BEGIN UPDATE channel_taste_version SET version = version + 1 WHERE id = 1; END;

CREATE TRIGGER IF NOT EXISTS channel_taste_cleared
AFTER DELETE ON channel_taste
BEGIN UPDATE channel_taste_version SET version = version + 1 WHERE id = 1; END;
"""


class ChannelTaste:
    """What you have said about each channel, and nothing more."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)

    def version(self) -> int:
        with open_state(self._path) as conn:
            row = conn.execute(
                "SELECT version FROM channel_taste_version WHERE id = 1"
            ).fetchone()
        return row[0] if row else 0

    def all(self) -> dict[str, str]:
        """Channel id -> taste, for the channels you have said anything about.

        The whole table, because it is one row per channel you have decided
        on and the ranking needs every one of them at once. 520 channels is
        the ceiling and most will never be in here.
        """
        with open_state(self._path) as conn:
            return {row[0]: row[1] for row in
                    conn.execute("SELECT channel_id, taste FROM channel_taste")}

    def of(self, channel_id: str | None) -> str | None:
        if not channel_id:
            return None
        return self.all().get(channel_id)

    def set(self, channel_id: str, taste: str | None) -> None:
        """Say something about a channel, or take it back.

        `None` deletes the row rather than storing a third state: neutral is
        the absence of an opinion, and writing one down would make "never
        asked" and "asked and shrugged" two things the ranking has to tell
        apart for no gain.
        """
        if not channel_id:
            return
        if taste is not None and taste not in TASTES:
            raise ValueError(f"unknown taste {taste!r}")
        with open_state(self._path) as conn:
            if taste is None:
                conn.execute("DELETE FROM channel_taste WHERE channel_id = ?",
                             (channel_id,))
            else:
                conn.execute(
                    "INSERT INTO channel_taste (channel_id, taste, decided)"
                    " VALUES (?, ?, ?) ON CONFLICT(channel_id) DO UPDATE SET"
                    " taste = excluded.taste, decided = excluded.decided",
                    (channel_id, taste, datetime.now().isoformat(" ", "seconds")))
