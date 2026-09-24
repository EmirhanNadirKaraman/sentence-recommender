"""Whose videos you want more of, and whose you want less.

Kept here rather than on `channel` in the catalogue, which `sync-catalogue`
refills wholesale from the shared database: a column added there would be
truthful until the next sync and then silently gone. This is a preference,
not a fact about the channel, so it lives beside the other things you have
decided — what you know, what you have snoozed, which sentences you hid.

Three states and an absence. Subscribing lifts a channel's videos in the
feed; setting one aside pushes them down. Down, never out: a channel you
would rather not watch can still hold the one video that teaches the word
you need. Weights live in `watchability`, beside the other numbers that
decide an order.

The third and fourth are not preferences but facts about the material, and
`human` exists only so that the third can be answered "no" and stay answered.
Judging five hundred channels is a sitting, not a reflex, and without somewhere
to record "listened, it is a person" the Channels page cannot tell a channel
nobody has checked from one that passed. It weighs nothing -- neutral is what
an unjudged channel already gets -- and that is the point: it changes the
page's memory, never the order.

`machine` is the one that does something:
the channel's voice or text is machine-made. It pushes the videos down as
setting aside does, and — unlike setting aside — its sentences too, on every
card, deck and plan (`Application.verdicts`): a sentence nobody said is a
worse example of German than one somebody did, whatever the judge makes of
its grammar. Reversed in Settings, where every such channel is listed.

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
MACHINE = "machine"
HUMAN = "human"
TASTES = frozenset({UP, DOWN, MACHINE, HUMAN})
# The two that answer "is this machine-made?" rather than "do I want more of
# this?". Kept apart because a page that asks one question should offer one
# pair of answers, and because `up` and `down` survive a verdict on the voice.
VERDICTS = (MACHINE, HUMAN)

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

CREATE TABLE IF NOT EXISTS video_removed (
    video_id TEXT PRIMARY KEY,
    decided  TEXT NOT NULL
);
-- Versioned like the others, and for the same reason: `banned_videos` caches
-- what the removals come to and has to know when that answer is stale.
CREATE TABLE IF NOT EXISTS video_removed_version (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);
INSERT OR IGNORE INTO video_removed_version (id, version) VALUES (1, 0);

CREATE TRIGGER IF NOT EXISTS video_removed_added
AFTER INSERT ON video_removed
BEGIN UPDATE video_removed_version SET version = version + 1 WHERE id = 1; END;

CREATE TRIGGER IF NOT EXISTS video_removed_restored
AFTER DELETE ON video_removed
BEGIN UPDATE video_removed_version SET version = version + 1 WHERE id = 1; END;

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


class VideoRemovals:
    """The single videos you have taken off your pages, and when.

    A channel is the usual unit -- one decision covers everything it will
    ever post -- but a channel you want is not a channel without a dud in
    it, and until now the only way to be rid of one video was to lose the
    other ninety-nine with it.

    Here and not in the catalogue's own `video_blacklist`, which is a
    different list despite the name: that one is the scraper's, it says what
    never to fetch, and all 357 of its rows name videos the catalogue does
    not hold. This is a preference, so it sits beside the other things you
    have decided, and a re-scrape cannot quietly undo it.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)

    def version(self) -> int:
        with open_state(self._path) as conn:
            row = conn.execute(
                "SELECT version FROM video_removed_version WHERE id = 1"
            ).fetchone()
        return row[0] if row else 0

    def all(self) -> dict[str, str]:
        """Video id -> when it was removed, oldest first."""
        with open_state(self._path) as conn:
            return {row[0]: row[1] for row in conn.execute(
                "SELECT video_id, decided FROM video_removed"
                " ORDER BY decided, video_id")}

    def add(self, video_id: str) -> None:
        """Remove one video. Removing one already removed changes nothing --
        not even the date, so the list keeps saying when you decided."""
        if not video_id:
            return
        with open_state(self._path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO video_removed (video_id, decided)"
                " VALUES (?, ?)",
                (video_id, datetime.now().isoformat(" ", "seconds")))

    def remove(self, video_id: str) -> None:
        """Bring one back."""
        if not video_id:
            return
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM video_removed WHERE video_id = ?",
                         (video_id,))


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
