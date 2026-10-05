"""A schema of its own in the test database, for every test that stores things.

A reader's state lives in Postgres (see `state`), so the stores' tests need
one. They get it in `sentence_recommender_test` -- never the database that
holds the corpus and anyone's progress -- one fresh schema per test, dropped
when the test is done.

The test database is made once, by hand, because making a database needs the
server's superuser:

    createdb -h localhost -U postgres -O local_db_user sentence_recommender_test

`TEST_DB_NAME` names another. A test that needs it and cannot reach it fails
saying so, rather than skipping: a suite that quietly skips its stores is a
suite that has stopped testing them.
"""
from __future__ import annotations

import os
import unittest
import uuid
from dataclasses import replace

import psycopg2

import state
from config import DatabaseConfig, load_dotenv

TEST_DB = os.environ.get("TEST_DB_NAME", "sentence_recommender_test")
PREFIX = "test_"

_reachable: bool | None = None


def _server() -> DatabaseConfig:
    load_dotenv()
    if TEST_DB == os.environ.get("DB_NAME", "sentence_recommender"):
        raise RuntimeError("TEST_DB_NAME names the real database; the tests "
                           "drop schemas and must never run there")
    return DatabaseConfig.named(TEST_DB)


def _check() -> None:
    global _reachable
    if _reachable is None:
        try:
            psycopg2.connect(**_server().dsn_kwargs()).close()
            _reachable = True
        except psycopg2.OperationalError as error:
            _reachable = False
            raise RuntimeError(
                f"the test database {TEST_DB!r} is not reachable ({error}).\n"
                "Make it once: createdb -h localhost -U postgres "
                f"-O local_db_user {TEST_DB}") from error
    if not _reachable:
        raise RuntimeError(f"the test database {TEST_DB!r} is not reachable")


def fresh(label: str = "s") -> DatabaseConfig:
    """A connection to a schema nobody has used, in the test database."""
    _check()
    return replace(_server(), schema=f"{PREFIX}{label}_{uuid.uuid4().hex[:12]}")


def drop(config: DatabaseConfig) -> None:
    """Drop a schema `fresh` made -- and refuse anything else."""
    if config.name != TEST_DB or not config.schema.startswith(PREFIX):
        raise RuntimeError(f"refusing to drop {config.name}.{config.schema}")
    state.forget(config)
    # An application made over this schema counted its vectors in; a dropped
    # schema left in that list would fail the next test that ranks examples.
    import sys                                               # noqa: PLC0415
    examples = sys.modules.get("roadmap.examples")
    if examples is not None:
        examples.forget_vectors(config)
    conn = psycopg2.connect(**_server().dsn_kwargs())
    try:
        conn.autocommit = True
        conn.cursor().execute(f'DROP SCHEMA IF EXISTS "{config.schema}" CASCADE')
    finally:
        conn.close()


def schema(test: unittest.TestCase, label: str = "s") -> DatabaseConfig:
    """A fresh schema for `test`, dropped when it finishes."""
    config = fresh(label)
    test.addCleanup(drop, config)
    return config
