"""Generating `DATABASE.md` from the live databases.

The document says "regenerate rather than hand-edit", which was a promise the
repository could not keep: the generator lived in a scratch directory and the
version in git went stale the moment the schema moved. This is that generator,
kept where it can be run again.

It reports both stores, because the split between them is the thing worth
understanding. Postgres holds the German — the catalogue as scraped, and the
corpus analysed out of it. SQLite holds only what the reader has done about
it: the roadmaps walked, the cards scheduled, the judgements nothing can
regenerate.

For Postgres it prints keys, foreign keys and indexes as well as columns.
That would have been noise when the schema belonged to another project and
nothing here could change it. It is the point of the document now.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

# The catalogue tables, in the order the copy fills them — parents first.
# Matches `commands.sync_catalogue.TABLES`.
CATALOGUE = ("channel", "video", "sentence", "word_table", "phrase_table",
             "grammar_rule", "phrase_blueprint", "sentence_to_grammar_rule",
             "word_to_sentence", "sentence_to_phrase", "lemma_override",
             "video_blacklist")

# What this project analysed out of the catalogue, and the bookkeeping that
# says which rules produced it. Moved here from SQLite; see migrations
# 29e0c9733097 and 6f2a1c84bb70.
CORPUS = ("corpus_sentence", "corpus_unit", "build_meta")

# Written by language-app's scraper, read by nothing here. Worth marking, so
# nobody optimises a table this project never queries.
WRITE_ONLY = frozenset({"phrase_blueprint", "sentence_to_grammar_rule",
                        "word_to_sentence", "sentence_to_phrase",
                        "lemma_override", "video_blacklist"})

# These survive nothing else: no rebuild puts them back.
IRREPLACEABLE = ("known_units", "checked_units", "snoozed_units",
                 "hidden_sentences", "corrected_sentences", "video_attempts")


def _sqlite_section(path: Path, w) -> None:
    conn = sqlite3.connect(str(path))
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        w(f"\n## `{path.relative_to(Path.cwd())}` — what the reader does"
          f" ({len(tables)} tables)\n")
        w("What the reader has done, and nothing else — the corpus itself"
          " moved to")
        w("Postgres. Roadmaps and scores are derived and rebuildable. The"
          " judgements are")
        w("not: " + ", ".join(f"`{t}`" for t in IRREPLACEABLE) + " hold"
          " decisions")
        w("nothing can regenerate. The file is gitignored either way.\n")
        for table in tables:
            rows = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            cols = list(conn.execute(f'PRAGMA table_info("{table}")'))
            keys = [c[1] for c in sorted((c for c in cols if c[5]),
                                         key=lambda c: c[5])]
            w(f"\n### `{table}` — {rows:,} rows\n")
            w("| column | type | null |")
            w("|---|---|---|")
            for _, name, kind, notnull, _default, _pk in cols:
                w(f"| `{name}` | {kind or 'ANY'} | {'no' if notnull else 'yes'} |")
            w("")
            w(f"- primary key: "
              + (", ".join(f"`{k}`" for k in keys) if keys
                 else "**none declared**"))
            for (index,) in [(r[1],) for r in
                             conn.execute(f'PRAGMA index_list("{table}")')
                             if not r[1].startswith("sqlite_")]:
                on = [r[2] for r in conn.execute(f'PRAGMA index_info("{index}")')]
                w(f"- index `{index}` on ({', '.join(on)})")
    finally:
        conn.close()


def _postgres_section(db, name: str, w) -> None:
    present = {r[0] for r in db.rows(
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema = 'public'")}
    revision = db.rows("SELECT version_num FROM alembic_version") \
        if "alembic_version" in present else []
    w(f"\n## Postgres `{name}` — the catalogue ({len(CATALOGUE)} tables)\n")
    w("This project's own database, under `alembic`"
      + (f" at revision `{revision[0][0]}`" if revision else "") + ". Every")
    w("read and every write goes here; `DB_NAME` names it.\n")
    w("It began as a copy of language-app's `german_vocabulary`, made by")
    w("`sync-catalogue --from german_vocabulary`. That was a migration, not a")
    w("link: ingestion writes here now, so re-copying would destroy work, and")
    w("the command refuses when it would.\n")
    w("Tables marked *write-only* are filled by language-app's scraper during")
    w("ingestion and read by nothing in this project.\n")

    _tables(db, CATALOGUE, present, w)

    w(f"\n## Postgres `{name}` — the analysed corpus"
      f" ({len(CORPUS)} tables + 1 view)\n")
    w("What the matcher made of the catalogue: one row per sentence worth")
    w("reading, and one per learning unit in it. `build` names both the source")
    w("and how it was assembled, so two ways of cutting the same subtitles can")
    w("coexist; `build_meta` records which rules produced each.\n")
    w("These were SQLite until the i+1 subtraction — 3.48M set operations per")
    w("load — was measured at 2.18s in SQL against 10.04s in Python.\n")
    _tables(db, CORPUS, present, w)

    for view, definition in db.rows(
            "SELECT matviewname, definition FROM pg_matviews"
            " WHERE schemaname = 'public' ORDER BY matviewname"):
        rows = db.rows(f'SELECT count(*) FROM "{view}"')[0][0]
        w(f"\n### `{view}` — {rows:,} rows *(materialized view)*\n")
        w("Refreshed CONCURRENTLY when a build is written. 59ms to read,")
        w("against 197ms to group the unit rows live.\n")
        w("```sql")
        w(definition.strip())
        w("```")


def _tables(db, names, present, w) -> None:
    for table in names:
        if table not in present:
            w(f"\n### `{table}` — **missing**\n")
            continue
        rows = db.rows(f'SELECT count(*) FROM "{table}"')[0][0]
        mark = " *(write-only)*" if table in WRITE_ONLY else ""
        w(f"\n### `{table}` — {rows:,} rows{mark}\n")
        w("| column | type | null | default |")
        w("|---|---|---|---|")
        for col, kind, nullable, default in db.rows(
                "SELECT column_name, data_type, is_nullable, column_default"
                " FROM information_schema.columns WHERE table_name = %s"
                " AND table_schema = 'public' ORDER BY ordinal_position",
                (table,)):
            shown = f"`{default.split('::')[0]}`" if default else ""
            w(f"| `{col}` | {kind} | {nullable.lower()} | {shown} |")
        w("")
        for kind, definition in db.rows(
                "SELECT contype, pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conrelid = %s::regclass"
                " ORDER BY contype, conname", (table,)):
            label = {"p": "primary key", "u": "unique", "f": "foreign key",
                     "c": "check"}.get(kind, kind)
            w(f"- {label}: `{definition}`")
        for index, definition in db.rows(
                "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = %s"
                " AND schemaname = 'public' ORDER BY indexname", (table,)):
            if "UNIQUE INDEX" in definition:
                continue                 # already shown as a constraint
            # The name comes from its own column. Parsing it back out of the
            # definition picks up the table instead, since `CREATE INDEX x ON
            # public.t USING ...` puts the table last before USING.
            _, _, using = definition.partition(" USING ")
            w(f"- index `{index}` — `{using}`")


def write(app, out: Path | None = None) -> Path:
    """Regenerate the document, and say where it went."""
    from db import Database                        # noqa: PLC0415 — cycle

    out = out or Path("DATABASE.md")
    lines: list[str] = []
    w = lines.append
    w("# Database structure\n")
    w("Generated by `python main.py schema-doc` — regenerate rather than")
    w("hand-edit.\n")
    w(f"_As of {date.today().isoformat()}._\n")
    w("Two stores, and the split is deliberate. Postgres holds the catalogue")
    w("— what German exists. SQLite holds what has been made of it, and what")
    w("the reader has decided.")

    _sqlite_section(app.settings.state_path, w)
    with Database(app.settings.own) as db:
        _postgres_section(db, app.settings.own.name, w)

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
