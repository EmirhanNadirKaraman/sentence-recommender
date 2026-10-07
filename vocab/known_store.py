"""Words and patterns marked as known while reading.

The vocabulary files are the starting point; this is what accumulates on top
of them. Kept apart from `known_words.txt` deliberately — that file is
hand-written and belongs to the reader, and a program that rewrites it would
make it untrustworthy.
"""
from __future__ import annotations


from state import ensure, open_state, version_trigger
from datetime import datetime

from vocab.entry import Unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS known_units (
    kind     TEXT COLLATE "C" NOT NULL,
    key      TEXT COLLATE "C" NOT NULL,
    marked   TEXT COLLATE "C" NOT NULL,
    PRIMARY KEY (kind, key)
);

-- A counter, bumped by the database itself whenever this table changes.
-- Anything derived from what you know — every video's comprehension score —
-- is stamped with it and recomputed when the stamps disagree.
--
-- A trigger rather than a call in `add`, because a caller can forget and a
-- trigger cannot: the row cannot change without the version moving, whoever
-- writes it and by whatever route.
CREATE TABLE IF NOT EXISTS known_version (
    id      BIGINT PRIMARY KEY CHECK (id = 1),
    version BIGINT NOT NULL
);
INSERT INTO known_version (id, version) VALUES (1, 0) ON CONFLICT DO NOTHING;
""" + version_trigger("known_units", "known_version", "INSERT OR DELETE")


class KnownStore:
    def __init__(self, config) -> None:
        self._db = config
        ensure(config, SCHEMA)

    def version(self) -> int:
        """How many times what you know has changed.

        Cheap enough to ask on every request, which is the point: it decides
        whether a stored score still describes you.
        """
        with open_state(self._db) as conn:
            row = conn.execute(
                "SELECT version FROM known_version WHERE id = 1").fetchone()
        return row[0] if row else 0

    def add(self, unit: Unit) -> bool:
        with open_state(self._db) as conn:
            row = conn.execute(
                "INSERT INTO known_units (kind, key, marked)"
                " VALUES (%s, %s, %s) ON CONFLICT DO NOTHING RETURNING kind",
                (unit.kind, unit.key, datetime.now().isoformat()),
            ).fetchone()
        return row is not None

    def remove(self, unit: Unit) -> None:
        with open_state(self._db) as conn:
            conn.execute("DELETE FROM known_units WHERE kind = %s AND key = %s",
                         (unit.kind, unit.key))

    def units(self) -> set[Unit]:
        with open_state(self._db) as conn:
            return {Unit(kind, key) for kind, key in
                    conn.execute("SELECT kind, key FROM known_units")}

    def __len__(self) -> int:
        with open_state(self._db) as conn:
            return conn.execute("SELECT count(*) FROM known_units").fetchone()[0]
