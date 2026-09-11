"""Alembic's entry point, wired to this project's own settings.

The connection is not in `alembic.ini`. It is built from the same
`DatabaseConfig` everything else uses, so there is one place where the
credentials live and no second copy to drift — and so a password never sits
in a file that gets committed.

`target_metadata` stays None on purpose. There is no SQLAlchemy model layer
here; the rest of the project speaks psycopg2 and raw SQL. Migrations are
written by hand, which is what you want when the schema is six tables copied
from somewhere else rather than something generated from classes.
"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import Settings          # noqa: E402 — after the path is set

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Straight to `create_engine`, not through `set_main_option`. Alembic hands
# that value to ConfigParser unescaped, so a password containing a percent
# sign is read as an interpolation and the run dies with a KeyError naming
# whatever followed it. The ini never sees the credentials this way.
DATABASE_URL = Settings().own.url()
target_metadata = None


def run_migrations_offline() -> None:
    context.configure(url=DATABASE_URL, target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
