"""`es gibt` is its own unit.

The matcher's dictionary holds one blueprint per verb lemma, so every
`gibt` in the corpus was credited with `jdm. (Dat) etw. (Akk) geben` — and
five sentences in six were `es gibt`, *there is*, which a learner who knows
*give someone something* cannot read (experiment 04, 2026-09-20). The
parse tells the two apart: `es` hangs under `gibt` as `ep`, the expletive,
and the matcher now routes that to a canonical of its own.

A canonical is a unit only when `phrase_table` lists it — `UnitAnalyzer`
keeps a pattern the matcher emits only if it is registered there — and the
table is this project's to write since 9863bcf8177b. So the row is added
here rather than by hand, and a fresh database gets it with the schema.
`collocation`, as `das Jahr` and `all, alle` are typed: it is a fixed
expression, not a verb frame with slots. `ON CONFLICT DO NOTHING`, because
a sync from upstream may one day carry it.

Not a key in `data/final_result.txt`: the fuzzy index would file it under
`es` and hand the construction to every pronoun in the corpus. The study
list carries the goal line by hand, beside `geben`, with the same note.

Revision ID: b31e7c0d9a42
Revises: 4d7b9a2c1e33
Create Date: 2026-09-20
"""
from __future__ import annotations

from alembic import op

revision = "b31e7c0d9a42"
down_revision = "4d7b9a2c1e33"
branch_labels = None
depends_on = None

CANONICAL = "es gibt"


def upgrade() -> None:
    op.execute(
        "INSERT INTO phrase_table (canonical, surface_form, phrase_type, language)"
        f" VALUES ('{CANONICAL}', '{CANONICAL}', 'collocation', 'de')"
        " ON CONFLICT (canonical, language) DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        f"DELETE FROM phrase_table WHERE canonical = '{CANONICAL}' AND language = 'de'"
    )
