"""`migrate-state`: a SQLite state file into a reader's Postgres schema.

Every value has to arrive as it left -- NULL as NULL rather than as an empty
string, tabs, newlines and backslashes inside text, bytes -- and the version
counters and id sequences have to go on from where SQLite left them. And the
file has to be settled first: a write still sitting in its write-ahead log is
a write the archive would lose.
"""
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from commands.migrate_state import MigrateStateCommand, _settle
from state import open_state
from tests import pg

# id, kind, key, written, german, note, english, correct, place, made_at
ATTEMPTS = [
    (3, "lemma", "geben", "gab", None, "a\ttab", "a line\nbreak \\ back", 1,
     "card", "2026-10-01"),
    (7, "lemma", "halten", "", "Er hält.", None, "", None, "page", "2026-10-02"),
]
VECTOR = bytes([0, 1, 92, 9, 10, 255])


def _state_file(directory: Path) -> Path:
    """A small state file as SQLite kept it, in WAL mode."""
    file = directory / "state.sqlite3"
    lite = sqlite3.connect(file)
    lite.executescript("""
        PRAGMA journal_mode = WAL;
        CREATE TABLE known_units (kind TEXT NOT NULL, key TEXT NOT NULL,
            marked TEXT NOT NULL, PRIMARY KEY (kind, key));
        CREATE TABLE known_version (id INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL);
        CREATE TABLE attempt (id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
            key TEXT NOT NULL, written TEXT NOT NULL, german TEXT, note TEXT,
            english TEXT, correct INTEGER, place TEXT NOT NULL,
            made_at TEXT NOT NULL);
        CREATE TABLE sentence_vector (text TEXT PRIMARY KEY, vector BLOB NOT NULL,
            dims INTEGER NOT NULL, model TEXT NOT NULL, made_at TEXT NOT NULL);
    """)
    lite.executemany("INSERT INTO known_units VALUES (?, ?, ?)",
                     [("lemma", "geben", "2026-09-01"),
                      ("pattern", "es gibt", "2026-09-02")])
    lite.execute("INSERT INTO known_version VALUES (1, 41)")
    lite.executemany("INSERT INTO attempt VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     ATTEMPTS)
    lite.execute("INSERT INTO sentence_vector VALUES (?, ?, ?, ?, ?)",
                 ("Er gab.", VECTOR, 3, "m", "2026-09-03"))
    lite.commit()
    lite.close()
    return file


def _write_and_die(file: Path) -> None:
    """One more row, left in the write-ahead log: a process that exits
    without closing its connection, as a killed `serve` does."""
    subprocess.run([sys.executable, "-c",
                    "import os, sqlite3, sys\n"
                    "c = sqlite3.connect(sys.argv[1])\n"
                    "c.execute('PRAGMA wal_autocheckpoint = 0')\n"
                    "c.execute(\"INSERT INTO known_units VALUES"
                    " ('lemma', 'spät', '2026-10-05')\")\n"
                    "c.commit()\n"
                    "os._exit(0)\n", str(file)], check=True)


class SettleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.file = _state_file(self.dir)

    def test_a_write_left_in_the_log_ends_up_in_the_file(self) -> None:
        _write_and_die(self.file)
        wal = self.dir / "state.sqlite3-wal"
        self.assertGreater(wal.stat().st_size, 0)
        _settle(self.file)
        self.assertFalse(wal.exists())
        self.assertFalse((self.dir / "state.sqlite3-shm").exists())
        # The file alone, without anything beside it, has the late row.
        alone = self.dir / "alone" / "copy.sqlite3"
        alone.parent.mkdir()
        shutil.copy(self.file, alone)
        keys = {k for (k,) in sqlite3.connect(alone).execute(
            "SELECT key FROM known_units")}
        self.assertIn("spät", keys)

    def test_a_file_something_still_has_open_is_refused(self) -> None:
        other = sqlite3.connect(self.file)
        other.execute("SELECT count(*) FROM known_units").fetchone()
        try:
            with self.assertRaises(SystemExit):
                _settle(self.file)
        finally:
            other.close()


class CopyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.file = _state_file(self.dir)
        _write_and_die(self.file)
        self.target = pg.schema(self)
        with redirect_stdout(StringIO()):
            MigrateStateCommand()._one(self.file, self.target, dry_run=False)

    def rows(self, sql: str) -> list:
        with open_state(self.target) as conn:
            return conn.execute(sql).fetchall()

    def test_every_value_arrives_as_it_left(self) -> None:
        self.assertEqual(self.rows(
            "SELECT id, kind, key, written, german, note, english, correct,"
            " place, made_at FROM attempt ORDER BY id"), ATTEMPTS)
        self.assertEqual(
            [(bytes(v), d) for v, d in self.rows(
                "SELECT vector, dims FROM sentence_vector")], [(VECTOR, 3)])

    def test_the_row_left_in_the_log_came_too(self) -> None:
        self.assertEqual(sorted(k for (k,) in self.rows(
            "SELECT key FROM known_units")), ["es gibt", "geben", "spät"])

    def test_the_counter_is_what_sqlite_held_not_what_the_copy_bumped(self) -> None:
        self.assertEqual(self.rows("SELECT version FROM known_version"), [(41,)])

    def test_new_ids_go_on_from_the_highest_copied(self) -> None:
        self.assertEqual(self.rows(
            "INSERT INTO attempt (kind, key, written, place, made_at)"
            " VALUES ('lemma', 'x', 'x', 'card', 'now') RETURNING id"), [(8,)])

    def test_a_schema_already_written_is_not_copied_over(self) -> None:
        with redirect_stdout(StringIO()), self.assertRaises(SystemExit):
            MigrateStateCommand()._one(self.file, self.target, dry_run=False)


if __name__ == "__main__":
    unittest.main()
