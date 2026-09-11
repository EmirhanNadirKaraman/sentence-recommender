"""The tables the scraper also fills.

The first migration copied the six tables this project reads. That was the
right set while ours was a mirror and ingestion wrote upstream. Pointing
ingestion here made it the wrong set: `pipeline.populate` writes more than it
reads, and a missing table is not a slow query, it is a crash halfway through
a scrape.

Four of these it writes — `sentence_to_grammar_rule` and `word_to_sentence`
directly, `phrase_blueprint` and `sentence_to_phrase` through
`insert_phrases`. One it reads (`lemma_override`), and one belongs to the
channel scan (`video_blacklist`).

None of them is read by this project. They are here so that borrowing
language-app's scraper keeps working, which is the whole basis of ingestion:
a second implementation of subtitle parsing would drift from the first.

`lemma_override` is unrelated to `data/lemma_overrides.txt`, which is this
project's own hand-checked file. Same idea, different place, and the file is
the one that feeds the analyser.

Revision ID: 85f526a480c5
Revises: 9863bcf8177b
Create Date: 2026-09-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "85f526a480c5"
down_revision = "9863bcf8177b"
branch_labels = None
depends_on = None

# Same reasoning as migration 9863bcf8177b: the scraper omits these and reads
# them back, and `BY DEFAULT` so the sync may still supply explicit ids.
KEYS: tuple[tuple[str, str], ...] = (
    ("phrase_blueprint", "blueprint_id"),
    ("sentence_to_phrase", "id"),
    ("lemma_override", "id"),
)


def upgrade() -> None:
    op.create_table(
        "phrase_blueprint",
        sa.Column("blueprint_id", sa.Integer(), autoincrement=False,
                  nullable=False),
        sa.Column("lookup_key", sa.Text(), nullable=False),
        sa.Column("blueprint", sa.Text(), nullable=False),
        sa.Column("lookup_key_norm", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("blueprint_id", name="phrase_blueprint_pkey"),
        # `insert_phrases` inserts blueprints and reads them back by this key,
        # so it is a constraint the scraper depends on, not just an index.
        sa.UniqueConstraint("lookup_key", name="phrase_blueprint_lookup_key_key"),
    )

    op.create_table(
        "sentence_to_grammar_rule",
        sa.Column("sentence_id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("sentence_id", "rule_id",
                                name="sentence_to_grammar_rule_pkey"),
        sa.ForeignKeyConstraint(["sentence_id"], ["sentence.sentence_id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["grammar_rule.rule_id"],
                                ondelete="CASCADE"),
    )

    op.create_table(
        "word_to_sentence",
        sa.Column("word_id", sa.Integer(), nullable=False),
        sa.Column("sentence_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("word_id", "sentence_id",
                                name="word_to_sentence_pkey"),
        sa.ForeignKeyConstraint(["word_id"], ["word_table.word_id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sentence_id"], ["sentence.sentence_id"],
                                ondelete="CASCADE"),
    )

    op.create_table(
        "sentence_to_phrase",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("sentence_id", sa.Integer(), nullable=False),
        sa.Column("blueprint_id", sa.Integer(), nullable=True),
        sa.Column("surface_form", sa.Text(), nullable=False),
        sa.Column("logic", sa.Text(), nullable=False),
        sa.Column("match_type", sa.Text(), nullable=False),
        sa.Column("indices", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.PrimaryKeyConstraint("id", name="sentence_to_phrase_pkey"),
        sa.ForeignKeyConstraint(["sentence_id"], ["sentence.sentence_id"],
                                ondelete="CASCADE"),
        # SET NULL rather than CASCADE: losing the blueprint should not lose
        # the record that the phrase was found. Upstream's choice, kept.
        sa.ForeignKeyConstraint(["blueprint_id"],
                                ["phrase_blueprint.blueprint_id"],
                                ondelete="SET NULL"),
    )

    op.create_table(
        "lemma_override",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("observed_lemma", sa.Text(), nullable=False),
        sa.Column("corrected_lemma", sa.Text(), nullable=False),
        sa.Column("surface_form", sa.Text(), nullable=True),
        sa.Column("pos", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False,
                  server_default=sa.text("'manual'")),
        sa.Column("status", sa.Text(), nullable=False,
                  server_default=sa.text("'active'")),
        sa.Column("confidence", sa.REAL(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="lemma_override_pkey"),
        sa.UniqueConstraint("language", "observed_lemma",
                            name="uq_lemma_override_lang_observed"),
        sa.CheckConstraint(
            "source = ANY (ARRAY['manual', 'llm', 'admin',"
            " 'user_flag_reviewed'])", name="lemma_override_source_check"),
        sa.CheckConstraint("status = ANY (ARRAY['active', 'inactive'])",
                           name="lemma_override_status_check"),
    )

    op.create_table(
        "video_blacklist",
        sa.Column("video_id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("video_id", name="video_blacklist_pkey"),
    )

    # Both bridges are read the other way round too — everything for one
    # sentence — and the primary key leads with the wrong column for that.
    op.execute("CREATE INDEX wts_sentence_id_index"
               " ON word_to_sentence (sentence_id)")
    op.execute("CREATE INDEX stp_sentence_id_idx"
               " ON sentence_to_phrase (sentence_id)")
    op.execute("CREATE INDEX ix_lemma_override_lang_status"
               " ON lemma_override (language, status)")

    for table, column in KEYS:
        op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}"'
                   f" ADD GENERATED BY DEFAULT AS IDENTITY")


def downgrade() -> None:
    for table in ("sentence_to_phrase", "word_to_sentence",
                  "sentence_to_grammar_rule", "phrase_blueprint",
                  "lemma_override", "video_blacklist"):
        op.drop_table(table)
