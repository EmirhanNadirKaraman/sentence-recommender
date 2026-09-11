"""The catalogue this project reads.

Six tables copied out of language-app's `german_vocabulary`, which this
project has read since the beginning and does not own. Reading someone
else's schema meant never being able to index it: the vocabulary lookup is
a sequential scan of 129,841 rows because the index it wants belongs in a
database under their migrations, not ours.

So this is the same data, in our own database, indexed for our own queries.
Four deliberate differences from the source:

*No sequences.* Every id arrives from `sync-catalogue` already assigned.
Hence `autoincrement=False` on each integer key — SQLAlchemy renders an
integer primary key as `SERIAL` otherwise, which is the sequence again by
another name.
Carrying the `nextval()` defaults would mean a `setval()` after every sync
or the first local insert collides with a copied row. If this project ever
writes its own rows, that is a later migration with a reason attached.

*Fewer foreign keys.* `sentence -> video` and `video -> channel` are kept,
because both sides are here. `video.category -> video_category` and
`channel.language -> language_table` are dropped and the columns kept as
plain text — nothing here reads those lookup tables, and copying two more
tables to satisfy a constraint nobody checks is not a trade worth making.

*Different indexes.* Not a copy of theirs; a set matched to the four
queries this project actually issues. See `_index` below, which names the
caller for each one.

*No trigram index.* `fuzzy_word_search_index_gin` supports fuzzy search in
their app. Nothing here uses `ILIKE`, `%` or `similarity()`, so it would be
dead weight — and it would make `pg_trgm` a setup step for every fresh
clone of this database.

Revision ID: dd0d9cf4b307
Revises:
Create Date: 2026-09-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "dd0d9cf4b307"
down_revision = None
branch_labels = None
depends_on = None

# Every index, with the query that wants it. Expression indexes cannot go
# through `op.create_index`, and writing them all as SQL keeps the list
# readable as one thing rather than two half-lists in different notations.
INDEXES: tuple[tuple[str, str, str], ...] = (
    # corpus/source.py SubtitleSource.lines — the corpus load. Joins video
    # to filter by language, then sorts by exactly these three columns, so
    # the index supplies the ordering and the sort disappears.
    ("ix_sentence_video_time", "sentence",
     "(video_id, start_time, sentence_id)"),

    # The same query's other half. The source indexes this as
    # (video_id, language), which cannot serve a filter on language — the
    # leading column is the one not being constrained. Reversed here.
    ("ix_video_language", "video", "(language, video_id)"),

    # The foreign key's own column, so deleting a channel does not scan.
    ("ix_video_channel", "video", "(channel_id)"),

    # ingest, which lists the channels worth scraping.
    ("ix_channel_language_active", "channel", "(language, active)"),

    # db/word_repo.lemmas_for_surfaces, whose two branches want one index
    # each. `lower(lemma)` is the one that cannot exist in the source
    # database and is the reason this database exists at all.
    ("ix_word_language_lower_lemma", "word_table", "(language, lower(lemma))"),
    ("ix_word_language_word_norm", "word_table", "(language, word_norm)"),

    # db/word_repo.function_words — grouped and aggregated over four
    # columns, all of them carried here so the scan never touches the heap.
    ("ix_word_language_tag", "word_table",
     "(language, tag) INCLUDE (lemma, frequency, word)"),

    # db/word_repo.PatternRepository.canonicals, which reads one column
    # for one language and gets both from the index.
    ("ix_phrase_language_canonical", "phrase_table", "(language, canonical)"),

    # Eighty-nine rows; the index is a rounding error and saves writing a
    # special case the day the table grows.
    ("ix_grammar_language", "grammar_rule", "(language)"),
)


def upgrade() -> None:
    op.create_table(
        "channel",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("youtube_channel_id", sa.Text(), nullable=False),
        sa.Column("channel_name", sa.Text(), nullable=False,
                  server_default=sa.text("''")),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id", name="channel_pkey"),
        sa.UniqueConstraint("youtube_channel_id",
                            name="channel_youtube_channel_id_key"),
    )

    op.create_table(
        "video",
        # Text, and holding digits, because that is what the source made it:
        # a text column with an integer sequence behind it. Copied as-is —
        # `sentence.video_id` joins to it and the values must match.
        sa.Column("video_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=False),
        sa.Column("duration", postgresql.DOUBLE_PRECISION(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("dialect", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False,
                  server_default=sa.text("'other'")),
        sa.Column("channel_id", sa.Integer(), nullable=True),
        sa.Column("transcript_source", sa.Text(), nullable=False,
                  server_default=sa.text("'auto'")),
        sa.PrimaryKeyConstraint("video_id", name="video_pkey"),
        sa.ForeignKeyConstraint(["channel_id"], ["channel.id"],
                                name="fk_video_channel"),
    )

    op.create_table(
        "sentence",
        sa.Column("sentence_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("video_id", sa.Text(), nullable=False),
        sa.Column("start_time", postgresql.DOUBLE_PRECISION(), nullable=False),
        sa.Column("duration", postgresql.DOUBLE_PRECISION(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tokens", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("token_ids", postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.PrimaryKeyConstraint("sentence_id", name="sentence_pkey"),
        sa.ForeignKeyConstraint(["video_id"], ["video.video_id"],
                                name="fk_sentence_video", ondelete="CASCADE"),
    )

    op.create_table(
        "word_table",
        sa.Column("word_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("word", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("pos", sa.Text(), nullable=False),
        sa.Column("tag", sa.Text(), nullable=False),
        sa.Column("lemma", sa.Text(), nullable=False),
        sa.Column("frequency", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("word_norm", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("word_id", name="word_table_pkey"),
        sa.UniqueConstraint("word", "language", "pos",
                            name="word_table_word_language_pos_key"),
    )

    op.create_table(
        "phrase_table",
        sa.Column("phrase_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("canonical", sa.Text(), nullable=False),
        sa.Column("surface_form", sa.Text(), nullable=False),
        sa.Column("phrase_type", sa.Text(), nullable=False,
                  server_default=sa.text("'verb_pattern'")),
        sa.Column("language", sa.Text(), nullable=False,
                  server_default=sa.text("'de'")),
        sa.PrimaryKeyConstraint("phrase_id", name="phrase_table_pkey"),
        sa.UniqueConstraint("canonical", "language",
                            name="phrase_table_canonical_language_key"),
    )

    op.create_table(
        "grammar_rule",
        sa.Column("rule_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("rule_id", name="grammar_rule_pkey"),
        sa.UniqueConstraint("rule", "language",
                            name="grammar_rule_rule_language_key"),
    )

    for name, table, columns in INDEXES:
        op.execute(f"CREATE INDEX {name} ON {table} {columns}")


def downgrade() -> None:
    # Children first — the foreign keys go with the tables, and Postgres
    # will not drop a table something still references.
    for table in ("sentence", "video", "channel",
                  "word_table", "phrase_table", "grammar_rule"):
        op.drop_table(table)
