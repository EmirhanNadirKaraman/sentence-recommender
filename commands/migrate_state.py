"""`migrate-state` — move a reader's SQLite state into their Postgres schema.

Once per installation that predates the move: `data/state.sqlite3`, and any
`data/readers/<name>/state.sqlite3`, into `reader_<name>`; and the reader
registry, `data/readers/readers.json` with its `session.key`, into
`accounts`. Nothing is deleted. Each SQLite file is renamed to
`*.migrated` once its rows are all accounted for, and the registry file
with it, so the program cannot go on reading one by mistake.

Table by table, every column by name, with `COPY`: half a gigabyte is
423,905 judge's answers and 400,572 translations, and a row-by-row insert
of those is the better part of an hour. Then each table is checked: the
counts, and every row's contents hashed in key order on both sides, so a
value that changed on the way -- a float narrowed, a text trimmed -- shows
as a mismatch rather than as a page that looks slightly different weeks
later.

The version counters (`known_version` and the rest) are set to what SQLite
held after the copy: the triggers fire on every row copied in, and a stored
score stamped against the old count has to find the same count here.
"""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import time
from pathlib import Path

from state import open_state

# Tables that are one counter row, set after the copy rather than copied.
COUNTERS = ("known_version", "channel_taste_version", "channel_blacklist_version",
            "video_removed_version", "study_clock")

# Ids SQLite assigned that Postgres now assigns, by table.
IDENTITIES = {"attempt": "id", "cards": "card_id", "encounter": "id"}

# A progress line per this many rows on the big tables.
REPORT = 50_000


def reader_stores():
    """Every store that keeps a table in a reader's schema -- made here so
    the schema has every table before anything is copied into it."""
    from corpus.answers import AnswerStore
    from corpus.fixes import FixStore
    from corpus.overrides import SentenceOverrides
    from corpus.vectors import VectorStore
    from deck.gloss import GlossStore
    from deck.pieces import PieceStore
    from ingest.attempts import AttemptLog
    from ingest.searches import SearchLog
    from roadmap.cover import VideoCoverStore
    from roadmap.store import RoadmapStore
    from roadmap.videos import VideoRoadmapStore
    from scores import ScoreStore
    from srs.store import CardStore
    from vocab.attempts import Attempts
    from vocab.channel_taste import ChannelBlacklist, ChannelTaste, VideoRemovals
    from vocab.checked_store import CheckedStore
    from vocab.encounters import Encounters
    from vocab.known_store import KnownStore
    from vocab.own_sentences import OwnSentences
    from vocab.snooze_store import SnoozeStore
    from vocab.word_lists import WordListStore
    return (AnswerStore, FixStore, SentenceOverrides, VectorStore, GlossStore,
            PieceStore, AttemptLog, SearchLog, VideoCoverStore, RoadmapStore,
            VideoRoadmapStore, ScoreStore, CardStore, Attempts, ChannelBlacklist,
            ChannelTaste, VideoRemovals, CheckedStore, Encounters, KnownStore,
            OwnSentences, SnoozeStore, WordListStore)


class MigrateStateCommand:
    def run(self, app, source: Path | None = None, dry_run: bool = False) -> None:
        from config import Settings                         # noqa: PLC0415
        from readers import READERS, Registry                # noqa: PLC0415

        registry = Registry()
        if source is not None:
            self._one(source, app.settings.state, dry_run)
            return
        # The readers the registry file names, or -- moved already -- the
        # ones the database has. Their state goes first and the registry
        # last, so a failure part-way leaves the old installation whole.
        named = self._named(READERS) or list(registry.readers().values())
        moved = []
        for reader in named:
            file = reader.home / "state.sqlite3"
            if file.exists():
                self._one(file, Settings.for_reader(reader).state, dry_run)
                moved.append(file)
        if not moved:
            print("no reader has a SQLite state file left to move")
        self._accounts(registry, READERS, dry_run)
        if dry_run:
            return
        for file in moved:
            file.rename(file.with_name(file.name + ".migrated"))
            print(f"renamed {file} to {file.name}.migrated")

    # --- the registry -------------------------------------------------------

    @staticmethod
    def _named(root: Path) -> list:
        """The readers the registry file names, as `Reader`s."""
        from readers import ROOT, Reader                     # noqa: PLC0415
        file = root / "readers.json"
        if not file.exists():
            return []
        named = []
        for name, fields in json.loads(file.read_text(encoding="utf-8")
                                       ).get("readers", {}).items():
            home = Path(fields["home"]) if fields.get("home") else root / name
            named.append(Reader(name=name,
                                home=home if home.is_absolute() else ROOT / home,
                                language=fields.get("language", "de"),
                                native=fields.get("native", "en"),
                                password=fields.get("password", "")))
        return named

    @staticmethod
    def _accounts(registry, root: Path, dry_run: bool) -> None:
        """Move the registry file's readers into `accounts`."""
        file = root / "readers.json"
        if not file.exists():
            return
        raw = json.loads(file.read_text(encoding="utf-8"))
        readers = raw.get("readers", {})
        if registry.names():
            raise SystemExit(f"{file} is still here, but the database already "
                             f"has readers ({', '.join(registry.names())}) — "
                             "not merging the two")
        print(f"accounts: {len(readers)} readers from {file}")
        if dry_run:
            return
        from datetime import datetime                        # noqa: PLC0415
        key = root / "session.key"
        with registry._conn() as conn:
            for name, fields in readers.items():
                conn.execute(
                    "INSERT INTO reader (name, language, native, home, password,"
                    " added) VALUES (%s, %s, %s, %s, %s, %s)",
                    (name, fields.get("language", "de"), fields.get("native", "en"),
                     fields.get("home"), fields.get("password", ""),
                     datetime.now().isoformat(timespec="seconds")))
            # The signing key comes too, so a device signed in before the
            # move is still signed in after it.
            if key.exists():
                conn.execute(
                    "INSERT INTO secret (name, value) VALUES ('session', %s)"
                    " ON CONFLICT (name) DO UPDATE SET value = excluded.value",
                    (key.read_text(encoding="ascii").strip(),))
        for name in sorted(readers):
            print(f"  {name}")
        file.rename(file.with_name(file.name + ".migrated"))
        if key.exists():
            key.rename(key.with_name(key.name + ".migrated"))

    # --- one state file -----------------------------------------------------

    def _one(self, file: Path, target, dry_run: bool) -> None:
        """One state file into one schema, in one transaction.

        Copied, counted, hashed and compared before anything commits: a
        mismatch rolls the whole schema's rows back, and the SQLite file is
        left where it was.
        """
        print(f"{file} -> schema {target.schema}", flush=True)
        lite = sqlite3.connect(f"file:{file}?mode=ro", uri=True)
        try:
            tables = [name for (name,) in lite.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
                " AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            for store in reader_stores():
                store(target)
            have = self._postgres_columns(target)
            missing = [t for t in tables if t not in have]
            if missing:
                raise SystemExit(f"  no Postgres table for {missing}")
            columns = {}
            for table in tables:
                columns[table] = [row[1] for row in
                                  lite.execute(f'PRAGMA table_info("{table}")')]
                extra = set(columns[table]) - set(have[table])
                if extra:
                    raise SystemExit(f"  {table}: no column for {sorted(extra)}")
            if dry_run:
                for table in tables:
                    count = lite.execute(
                        f'SELECT count(*) FROM "{table}"').fetchone()[0]
                    print(f"  {table:<28} {count:>9,} rows")
                return
            started = time.time()
            # Counters last: copying a table in fires the trigger that bumps
            # its counter, and the count has to end at what SQLite held.
            ordered = ([t for t in tables if t not in COUNTERS]
                       + [t for t in tables if t in COUNTERS])
            with open_state(target) as conn:
                self._refuse_if_written(conn, target, tables)
                for table in ordered:
                    count = lite.execute(
                        f'SELECT count(*) FROM "{table}"').fetchone()[0]
                    if table in COUNTERS:
                        self._counter(lite, conn, table, columns[table])
                    else:
                        self._copy(lite, conn, target, table, columns[table],
                                   count)
                    print(f"  {table:<28} {count:>9,} rows  "
                          f"({time.time() - started:.0f}s)", flush=True)
                self._sequences(conn, tables)
                print("  checking every row…", flush=True)
                bad = self._verify(lite, conn, tables, columns)
                if bad:
                    raise SystemExit(
                        "  mismatched: " + ", ".join(bad) + " — nothing "
                        "committed, and the SQLite file is where it was")
        finally:
            lite.close()
        print(f"  every table matches ({time.time() - started:.0f}s)",
              flush=True)

    @staticmethod
    def _postgres_columns(target) -> dict[str, list[str]]:
        with open_state(target) as conn:
            rows = conn.execute(
                "SELECT table_name, column_name FROM information_schema.columns"
                " WHERE table_schema = %s ORDER BY ordinal_position",
                (target.schema,)).fetchall()
        out: dict[str, list[str]] = {}
        for table, column in rows:
            out.setdefault(table, []).append(column)
        return out

    @staticmethod
    def _refuse_if_written(conn, target, tables: list[str]) -> None:
        for table in tables:
            if table in COUNTERS:
                continue
            if conn.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone():
                raise SystemExit(
                    f"  {target.schema}.{table} already has rows — this "
                    "reader was moved before; not copying over it")

    @staticmethod
    def _counter(lite, conn, table: str, columns: list[str]) -> None:
        row = lite.execute(f'SELECT {", ".join(columns)} FROM "{table}"').fetchone()
        if row is None:
            return
        values = dict(zip(columns, row))
        settable = [c for c in columns if c != "id"]
        conn.execute(
            f'UPDATE "{table}" SET '
            + ", ".join(f"{c} = %s" for c in settable) + " WHERE id = 1",
            [values[c] for c in settable])

    @staticmethod
    def _copy(lite, conn, target, table: str, columns: list[str],
              count: int) -> None:
        """Every row of `table`, through COPY, in batches of `REPORT`."""
        from db.progress import CopyProgress                 # noqa: PLC0415

        quoted = ", ".join(f'"{c}"' for c in columns)
        rows = lite.execute(f'SELECT {quoted} FROM "{table}"')
        pid = conn.raw.get_backend_pid()
        done = 0
        while True:
            batch = rows.fetchmany(REPORT)
            if not batch:
                break
            text = io.StringIO("".join(
                "\t".join(_copy_value(v) for v in row) + "\n" for row in batch))
            with CopyProgress(target, pid, table, total=count):
                conn.raw.cursor().copy_expert(
                    f'COPY "{table}" ({quoted}) FROM STDIN', text)
            done += len(batch)
            if count > REPORT:
                print(f"    {table}: {done:,} of {count:,}", flush=True)

    @staticmethod
    def _sequences(conn, tables: list[str]) -> None:
        """Identity columns go on from the highest id copied in."""
        for table, column in IDENTITIES.items():
            if table not in tables:
                continue
            conn.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'),"
                f" coalesce(max({column}), 1), max({column}) IS NOT NULL)"
                f" FROM {table}")

    @staticmethod
    def _verify(lite, conn, tables: list[str],
                columns: dict[str, list[str]]) -> list[str]:
        """Tables whose rows differ in count or in content."""
        bad = []
        for table in tables:
            quoted = ", ".join(f'"{c}"' for c in columns[table])
            # SQLite puts NULL first in an ascending sort and Postgres puts
            # it last; asked for first on both sides, the orders agree.
            mine = _digest(lite.execute(
                f'SELECT {quoted} FROM "{table}" ORDER BY {quoted}'))
            nulls = ", ".join(f'"{c}" NULLS FIRST' for c in columns[table])
            theirs = _digest(conn.execute(
                f'SELECT {quoted} FROM "{table}" ORDER BY {nulls}'))
            if mine != theirs:
                bad.append(f"{table} ({mine[0]:,} rows here, {theirs[0]:,} there)")
        return bad


# What a backslash, a tab, a newline and a carriage return become in
# Postgres's own COPY format, where those four are the syntax.
_ESCAPES = str.maketrans({"\\": "\\\\", "\t": "\\t", "\n": "\\n",
                          "\r": "\\r"})


def _copy_value(value) -> str:
    """One value in COPY's text format: `\\N` for NULL, bytes as hex."""
    if value is None:
        return "\\N"
    if isinstance(value, (bytes, memoryview)):
        return "\\\\x" + bytes(value).hex()
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        if "\x00" in value:
            raise SystemExit(f"a NUL character Postgres cannot store: {value!r:.80}")
        return value.translate(_ESCAPES)
    return str(value)


def _digest(rows) -> tuple[int, str]:
    """How many rows, and one hash over every value in them, in order.

    Bytes and memoryviews hash as their bytes, so a vector read back from
    Postgres compares with the blob SQLite held.
    """
    digest = hashlib.sha256()
    count = 0
    for row in rows:
        count += 1
        for value in row:
            if isinstance(value, memoryview):
                value = bytes(value)
            digest.update(repr(value).encode("utf-8"))
            digest.update(b"\x1f")
        digest.update(b"\x1e")
    return count, digest.hexdigest()
