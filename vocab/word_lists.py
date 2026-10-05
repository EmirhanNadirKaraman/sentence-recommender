"""Word lists the reader built, kept where judgements are kept.

A goal list has only ever been a file: `data/study_list.txt`, or whatever
`--goals-file` names. That is right for a syllabus copied out of a book and
wrong for a list someone assembles by searching the corpus and ticking
words — that is a judgement, and judgements live in `state.sqlite3` beside
`known_units` and `checked_units`, not in a file the reader has to manage.

The corpus itself left this file for Postgres, so nothing here is near the
sentences any more. That is fine: a list is a few thousand short strings,
and the search that builds one reads `corpus_unit_count`, which answers off
a materialized view in 59ms without loading a corpus at all.

Order is kept, because a goal list's order is the only ranking it carries
and `GoalList` reads it as one.
"""
from __future__ import annotations

from datetime import datetime

from state import ensure, open_state

SCHEMA = """
CREATE TABLE IF NOT EXISTS word_list (
    name     TEXT COLLATE "C" NOT NULL,
    position BIGINT NOT NULL,
    entry    TEXT COLLATE "C" NOT NULL,
    PRIMARY KEY (name, position)
);
CREATE TABLE IF NOT EXISTS word_list_meta (
    name    TEXT COLLATE "C" PRIMARY KEY,
    saved   TEXT COLLATE "C" NOT NULL,
    note    TEXT COLLATE "C" NOT NULL DEFAULT ''
);
"""


class WordListStore:
    """Named lists of goal entries, in the order they were chosen."""

    def __init__(self, config) -> None:
        self._db = config
        ensure(config, SCHEMA)

    def save(self, name: str, entries: list[str], note: str = "") -> int:
        """Replace a list. De-duplicated, keeping the first position.

        Replace rather than append, because the page hands over the whole
        list every time it is edited and a merge would make removing a word
        impossible.
        """
        seen: dict[str, None] = {}
        for entry in entries:
            cleaned = entry.strip()
            if cleaned:
                seen.setdefault(cleaned, None)
        with open_state(self._db) as conn:
            conn.execute("DELETE FROM word_list WHERE name = %s", (name,))
            conn.executemany(
                "INSERT INTO word_list (name, position, entry) VALUES (%s, %s, %s)",
                [(name, i, entry) for i, entry in enumerate(seen)])
            conn.execute(
                "INSERT INTO word_list_meta (name, saved, note)"
                " VALUES (%s, %s, %s) ON CONFLICT (name)"
                " DO UPDATE SET saved = excluded.saved, note = excluded.note",
                (name, datetime.now().isoformat(timespec="seconds"), note))
        return len(seen)

    def entries(self, name: str) -> tuple[str, ...]:
        with open_state(self._db) as conn:
            return tuple(row[0] for row in conn.execute(
                "SELECT entry FROM word_list WHERE name = %s ORDER BY position",
                (name,)))

    def names(self) -> list[tuple[str, int, str]]:
        """Every saved list: name, how many entries, when it was saved."""
        with open_state(self._db) as conn:
            return [(name, n, saved) for name, n, saved in conn.execute(
                "SELECT m.name, count(w.entry), m.saved"
                "  FROM word_list_meta m"
                "  LEFT JOIN word_list w ON w.name = m.name"
                " GROUP BY m.name, m.saved ORDER BY m.name")]

    def rename(self, old: str, new: str) -> int:
        """Give a list a different name, keeping its order.

        Worth having because a list's name is not decoration: a roadmap's
        label carries it, so a list called one thing cannot find plans built
        under another, and the page silently falls back to walking live.
        """
        entries = self.entries(old)
        if not entries:
            return 0
        with open_state(self._db) as conn:
            note = conn.execute(
                "SELECT note FROM word_list_meta WHERE name = %s",
                (old,)).fetchone()
        written = self.save(new, list(entries), note[0] if note else "")
        self.forget(old)
        return written

    def forget(self, name: str) -> None:
        with open_state(self._db) as conn:
            conn.execute("DELETE FROM word_list WHERE name = %s", (name,))
            conn.execute("DELETE FROM word_list_meta WHERE name = %s", (name,))

    def __contains__(self, name: str) -> bool:
        with open_state(self._db) as conn:
            return conn.execute(
                "SELECT 1 FROM word_list_meta WHERE name = %s",
                (name,)).fetchone() is not None
