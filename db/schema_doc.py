"""Generating `DATABASE.md` from the live databases.

The document says "regenerate rather than hand-edit", which was a promise the
repository could not keep: the generator lived in a scratch directory and the
version in git went stale the moment the schema moved. This is that generator,
kept where it can be run again.

It reports both stores, because the split between them is the thing worth
understanding. SQLite holds what the reader does — the corpus as analysed,
the roadmaps, the judgements nothing can regenerate. Postgres holds the
catalogue: the subtitles, the words, the phrases.

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
        w("Everything this program writes about a person: the analysed corpus,")
        w("the roadmaps it walks, the decisions made while reading. Gitignored")
        w("and rebuildable *except* the judgements — "
          + ", ".join(f"`{t}`" for t in IRREPLACEABLE) + " —")
        w("which nothing can regenerate.\n")
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

    for table in CATALOGUE:
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
