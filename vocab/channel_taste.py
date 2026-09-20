"""Whose videos you want more of, and whose you want less.

Kept here rather than on `channel` in the catalogue, which `sync-catalogue`
refills wholesale from the shared database: a column added there would be
truthful until the next sync and then silently gone. This is a preference,
not a fact about the channel, so it lives beside the other things you have
decided — what you know, what you have snoozed, which sentences you hid.

Two states and an absence. Subscribing lifts a channel's videos in the feed;
setting one aside pushes them down. Down, never out: a channel you would
rather not watch can still hold the one video that teaches the word you need.
Weights live in `watchability`, beside the other numbers that decide an order.

Out is a separate decision, and `ChannelBlacklist` holds it. A channel on it
is gone from every page -- its sentences are dropped wherever the corpus is
read, the same way a hidden sentence is, and its videos leave the feed and
the catalogue. Nothing is deleted: the captions stay in the catalogue and the
analysed sentences stay in the corpus, so taking a channel off the list
brings everything back at once, with nothing to re-scrape or re-analyse.
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

CREATE TABLE IF NOT EXISTS channel_blacklist (
    channel_id TEXT PRIMARY KEY,
    decided    TEXT NOT NULL
);
-- Bumped on every change, for the same reason as the taste's: the set of
-- videos it removes is derived from it, and a holder of that set can ask
-- whether it is still current without reading the table.
CREATE TABLE IF NOT EXISTS channel_blacklist_version (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);
INSERT OR IGNORE INTO channel_blacklist_version (id, version) VALUES (1, 0);

CREATE TRIGGER IF NOT EXISTS channel_blacklist_added
AFTER INSERT ON channel_blacklist
BEGIN UPDATE channel_blacklist_version SET version = version + 1 WHERE id = 1; END;

CREATE TRIGGER IF NOT EXISTS channel_blacklist_restored
AFTER DELETE ON channel_blacklist
BEGIN UPDATE channel_blacklist_version SET version = version + 1 WHERE id = 1; END;
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


class ChannelBlacklist:
    """The channels you have removed, and when."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)

    def version(self) -> int:
        with open_state(self._path) as conn:
            row = conn.execute(
                "SELECT version FROM channel_blacklist_version WHERE id = 1"
            ).fetchone()
        return row[0] if row else 0

    def all(self) -> dict[str, str]:
        """Channel id -> when it was removed, oldest first."""
        with open_state(self._path) as conn:
            return {row[0]: row[1] for row in conn.execute(
                "SELECT channel_id, decided FROM channel_blacklist"
                " ORDER BY decided, channel_id")}

    def add(self, channel_id: str) -> None:
        """Remove a channel. Removing one already removed changes nothing --
        not even the date, so the list keeps saying when you decided."""
        if not channel_id:
            return
        with open_state(self._path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO channel_blacklist (channel_id, decided)"
                " VALUES (?, ?)",
                (channel_id, datetime.now().isoformat(" ", "seconds")))

    def remove(self, channel_id: str) -> None:
        """Bring a channel back."""
        if not channel_id:
            return
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM channel_blacklist WHERE channel_id = ?",
                         (channel_id,))
