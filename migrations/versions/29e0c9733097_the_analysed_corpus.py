"""The analysed corpus.

`sentence_units` answers the only question the roadmap ever asks: which
learning units does this sentence contain. Subtract what the reader knows and
the remainder is the unknown count — nothing means readable, one means i+1.
That subtraction runs 3.48M times per corpus load, once per unit row, in
Python, against a set. It is the largest movable block of a ~10s load.

It could not move here before, because there was no "here": the corpus lived
in SQLite and the catalogue belonged to another project. Both halves of that
changed, so the table follows the question into the database that can answer
it in C.

`sentences` comes too, and not as scope creep — `sentence_units` alone would
be useless. Its foreign key points at `sentences`, and every query filters on
`build` and `teachable` and reads `text` back, so leaving it behind would put
the join back in Python, which is the cost being removed.

**On the names.** In SQLite these are `sentences` and `sentence_units`. Here
they would sit beside `sentence`, the catalogue's raw caption rows, differing
by a single letter while meaning very different things — 302,007 subtitle
lines as scraped, against 254,005 sentences reassembled and analysed from
them. A quarter of the second group spans several of the first. So they are
`corpus_sentence` and `corpus_unit`, and the SQLite names stay where they are.

What does *not* come: `unit_count`, a precomputed GROUP BY that took `/quiz`
from 30s to 0.12s in SQLite. With the source table here and indexed, that is
one aggregate query. Porting it would mean a second derived thing to keep in
step with the corpus, which this repo has already decided against once — see
`build_size` in the plan, dropped when measurement put the query it was to
replace at 0.06s. Measure the aggregate before porting anything.

Revision ID: 29e0c9733097
Revises: 85f526a480c5
Create Date: 2026-09-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "29e0c9733097"
down_revision = "85f526a480c5"
branch_labels = None
depends_on = None

INDEXES: tuple[tuple[str, str, str], ...] = (
    # `load()` filters on build and teachable on every call without exception,
    # so this leads. `id` rides along to make the common shape index-only.
    ("ix_corpus_sentence_build", "corpus_sentence", "(build, teachable, id)"),

    # The transcript panel: one video's lines, in playback order.
    ("ix_corpus_sentence_video", "corpus_sentence",
     "(build, video_id, start_time)"),

    # The correction page finds a sentence by its exact text. `text` can be
    # long, so hash rather than btree — only equality is ever asked.
    ("ix_corpus_sentence_text", "corpus_sentence", "hash (text)"),

    # The reverse lookup: which sentences say this unit. The primary key
    # leads with sentence_id and cannot serve it.
    ("ix_corpus_unit_key", "corpus_unit", "(kind, key, sentence_id)"),
)


def upgrade() -> None:
    op.create_table(
        "corpus_sentence",
        # Carried over from SQLite rather than regenerated: `sentence_units`
        # and the stored roadmaps reference these ids.
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("build", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("translation", sa.Text(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        # Which raw caption rows were reassembled into this one. A quarter of
        # them name more than one, which is why the catalogue's own
        # `word_to_sentence` bridge cannot describe these sentences.
        sa.Column("source_ids", sa.Text(), nullable=False,
                  server_default=sa.text("''")),
        sa.Column("video_id", sa.Text(), nullable=True),
        sa.Column("start_time", postgresql.DOUBLE_PRECISION(), nullable=True),
        sa.Column("end_time", postgresql.DOUBLE_PRECISION(), nullable=True),
        # An INTEGER 0/1 in SQLite, which has no boolean. It does here.
        sa.Column("teachable", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id", name="corpus_sentence_pkey"),
    )

    op.create_table(
        "corpus_unit",
        sa.Column("sentence_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("surface", sa.Text(), nullable=True),
        # The key SQLite went without for a long time. It also settles a
        # question the unknown count depends on: a sentence cannot hold the
        # same unit twice, so counting them needs no DISTINCT.
        sa.PrimaryKeyConstraint("sentence_id", "kind", "key",
                                name="corpus_unit_pkey"),
        sa.ForeignKeyConstraint(["sentence_id"], ["corpus_sentence.id"],
                                ondelete="CASCADE"),
    )

    for name, table, columns in INDEXES:
        # `hash (text)` names its own access method; the rest take the default.
        using = "USING " if columns.startswith("hash") else ""
        op.execute(f"CREATE INDEX {name} ON {table} {using}{columns}")


def downgrade() -> None:
    op.drop_table("corpus_unit")
    op.drop_table("corpus_sentence")
