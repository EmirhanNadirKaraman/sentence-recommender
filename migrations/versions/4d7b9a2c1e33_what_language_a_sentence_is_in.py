"""What language a sentence is in.

The transcripts are bilingual. Easy German publishes the German with an
English rendering beside it, and the import took lines without asking which
side of the page they came from — so 5,228 of the 315,216 sentences in the
corpus are English, 4,694 of them from `transcript` and 534 from `subtitle`.
Two of them are teaching steps 5 and 20 of the beginner roadmap:

    or I'm dissatisfied with something, I say so, too.

Nothing in the pipeline looked at what language a sentence was in, and
nothing cheap can. A word-list test finds four of these and misses the two
above, because their English contains `so` and `also`, which are German words
too. The two languages share enough short words that presence tests are
useless on one sentence.

**A column rather than a filter, and that is the decision this migration
encodes.** Dropping them at import would be simpler and would leave holes: a
subtitle build deliberately keeps sentences that are not worth studying from,
because they were still *said*, and the transcript panel is assembled from
all of them. An English line spoken in a German video is one of those. So the
sentence stays and the algorithms skip it.

Nullable on purpose. NULL means nobody has looked, which is not the same as
German — every row starts that way and `detect-language` fills them in. So a
reader that excludes non-German excludes only what has actually been judged,
and a corpus imported before this migration goes on behaving exactly as it
did.

No index. The queries that matter already filter by `build` and take most of
the table; adding `language` to the WHERE costs a check per row that Postgres
does while it is reading them anyway, and `(build, teachable, id)` is still
the index doing the work.

Revision ID: 4d7b9a2c1e33
Revises: 6f2a1c84bb70
Create Date: 2026-09-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "4d7b9a2c1e33"
down_revision = "6f2a1c84bb70"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("corpus_sentence",
                  sa.Column("language", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("corpus_sentence", "language")
