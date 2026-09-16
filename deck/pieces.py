"""Every spoken line, stored once and named by what it says.

A card's audio was one file per card, named for its position and its word.
That made three separate problems, all the same problem:

    A plan that reorders renames every clip. Five rebuilds in one day cost
    five full runs of the voice, about a hundred minutes each, and left 153
    orphans behind whose stems no longer belonged to any card.

    A card whose translation arrives later still has its file, and a file
    that exists is skipped -- so the clip went on speaking German alone while
    the card showed English.

    And the mix is fixed at synthesis. Wanting German only, or one example
    instead of three, meant recording everything again.

Naming a clip after its *text* rather than its position removes all three. A
sentence that moves from card 60 to card 214 keeps its audio. A translation
arriving adds one line and re-records nothing else. And a different
arrangement is a different list of the same pieces, which costs a concat.

The key is the text, the voice, and whether it was read slowly, because those
are exactly what change the sound. Paths are kept in the database beside the
key, so whatever wants to arrange them -- the card merger here, an episode,
or something not written yet -- can ask for a line without knowing where it
landed on disk.
"""
from __future__ import annotations

import hashlib
import wave
from datetime import datetime
from pathlib import Path

from state import open_state

# Two characters of the hash as a directory. 40,000 files in one folder is
# slow to list and slower to stat on every filesystem this runs on; 256 of
# 160 is neither.
SHARD = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS audio_piece (
    id       TEXT PRIMARY KEY,
    text     TEXT NOT NULL,
    voice    TEXT NOT NULL,
    slow     INTEGER NOT NULL,
    role     TEXT NOT NULL,
    path     TEXT NOT NULL,
    seconds  REAL NOT NULL,
    made_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_piece_role ON audio_piece (role);
"""


def key_for(text: str, voice: str, slow: bool) -> str:
    """What identifies a piece: what is said, by whom, at what speed.

    Not the card and not the position -- those are what it is *used for*, and
    the same line is often used by several.
    """
    stamp = f"{voice}|{int(bool(slow))}|{text}".encode("utf-8")
    return hashlib.sha1(stamp).hexdigest()[:20]


def path_for(root: Path, key: str) -> Path:
    return root / key[:SHARD] / f"{key}.wav"


def write_wav(path: Path, pcm: bytes, rate: int) -> float:
    """One piece to disk. Returns how long it plays, in seconds."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return len(pcm) / 2 / rate


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as handle:
        return handle.readframes(handle.getnframes())


class PieceStore:
    """Where each spoken line lives."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)

    def have(self) -> dict[str, str]:
        """Every piece already recorded, as key -> path."""
        with open_state(self._path) as conn:
            return dict(conn.execute("SELECT id, path FROM audio_piece"))

    def add_many(self, rows: list[tuple[str, str, str, bool, str, str, float]]
                 ) -> None:
        """`(key, text, voice, slow, role, path, seconds)` for each piece."""
        now = datetime.now().isoformat(timespec="seconds")
        with open_state(self._path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO audio_piece"
                " (id, text, voice, slow, role, path, seconds, made_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                [(key, text, voice, int(slow), role, path, seconds, now)
                 for key, text, voice, slow, role, path, seconds in rows])

    def by_role(self) -> dict[str, int]:
        with open_state(self._path) as conn:
            return dict(conn.execute(
                "SELECT role, COUNT(*) FROM audio_piece GROUP BY role"))

    def count(self) -> int:
        with open_state(self._path) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM audio_piece").fetchone()[0]
