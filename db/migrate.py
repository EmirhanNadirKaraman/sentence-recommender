"""Bringing a language's schema up to date.

German's tables are `public`'s and are migrated the way they always were,
by hand: `alembic upgrade head`. A second language's live in a schema of
their own (see `languages`), and nobody should have to know that to add a
reader who learns it -- so adding one runs that language's migrations here,
which on a schema already at the head does nothing at all.
"""
from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from languages import language

ROOT = Path(__file__).resolve().parents[1]


def prepare(code: str) -> bool:
    """Make sure language `code` has its tables; True if any were made.

    German is left alone: its schema is the one `alembic upgrade head`
    already looks after, and migrating it is a decision for whoever runs
    the server, not a side effect of adding a reader.
    """
    lang = language(code)
    if not lang.schema:
        return False
    from alembic import command                         # noqa: PLC0415
    from alembic.config import Config                   # noqa: PLC0415
    from alembic.runtime.migration import MigrationContext  # noqa: PLC0415
    from alembic.script import ScriptDirectory          # noqa: PLC0415
    from sqlalchemy import create_engine, pool          # noqa: PLC0415
    from config import DatabaseConfig                   # noqa: PLC0415

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    # What `-x language=en` puts there on the command line; `env.py` reads it.
    config.cmd_opts = Namespace(x=[f"language={code}"])
    head = ScriptDirectory.from_config(config).get_current_head()
    engine = create_engine(DatabaseConfig.owned(lang.schema).url(),
                           poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
    except Exception:                       # noqa: BLE001 — no schema yet
        current = None
    finally:
        engine.dispose()
    if current == head:
        return False
    command.upgrade(config, "head")
    return True
