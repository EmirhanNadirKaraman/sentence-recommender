"""Settings that are easy to delete by accident and silent when they are.

`work_mem` in particular: drop it and nothing fails, no test goes red, and
the corpus load quietly goes back to spilling its hash join through a temp
file. The only symptom is a second on every cold page.
"""
from __future__ import annotations

import unittest

from config import DatabaseConfig, Settings


class WorkMemTest(unittest.TestCase):
    def test_every_connection_carries_it(self) -> None:
        """Set on the connection, so it reaches psql's `options` and every
        query this project makes — not just the one it was measured on."""
        kwargs = DatabaseConfig.named("whatever").dsn_kwargs()
        self.assertIn("options", kwargs)
        self.assertIn(f"work_mem={DatabaseConfig.WORK_MEM}", kwargs["options"])

    def test_it_is_a_real_postgres_memory_value(self) -> None:
        self.assertRegex(DatabaseConfig.WORK_MEM, r"^\d+(kB|MB|GB)$")

    def test_the_dsn_still_carries_the_credentials(self) -> None:
        """`options` is an addition, not a replacement — a typo here would
        take the password with it."""
        kwargs = DatabaseConfig.named("somedb").dsn_kwargs()
        self.assertEqual(kwargs["dbname"], "somedb")
        for key in ("user", "password", "host", "port"):
            self.assertIn(key, kwargs)


class AnalysisProcessesTest(unittest.TestCase):
    def test_it_does_not_exceed_the_performance_cores(self) -> None:
        """Eight workers measured slower than four on this machine — four
        performance cores and four efficiency ones, and the second four cost
        more in contention than they return. Pinned so a later edit has to
        mean it."""
        self.assertEqual(Settings().analysis_processes, 4)


if __name__ == "__main__":
    unittest.main()


class ServerSlotsTest(unittest.TestCase):
    """The long LLM jobs size their pool from the server, not from a guess.

    A llama.cpp server divides its context into one slot per parallel request
    when it starts, so the slot count is the ceiling *and* the target: past it
    a request only queues, and below it the slots sit idle having already been
    paid for. `gloss-deck` was pinned at two against a six-slot endpoint,
    which is four idle for the eighty-two minutes the job takes.

    Both commands have to leave the default unset for their own resolution to
    run at all — an argparse default of 2 silently wins over it.
    """

    def parser(self):
        from main import _parser
        return _parser()

    def test_gloss_deck_asks_the_server(self) -> None:
        args = self.parser().parse_args(["gloss-deck"])
        self.assertIsNone(args.workers,
                          "a CLI default overrides the slot lookup in run()")

    def test_translate_sentences_asks_too(self) -> None:
        args = self.parser().parse_args(["translate-sentences"])
        self.assertIsNone(args.workers)

    def test_an_explicit_count_still_wins(self) -> None:
        self.assertEqual(self.parser().parse_args(
            ["gloss-deck", "--workers", "3"]).workers, 3)

    def test_the_fallback_is_what_the_pool_was_written_against(self) -> None:
        """Two, when the server will not say — the count `deck.gloss.run`
        documents its KV-cache reasoning against."""
        from commands.gloss_deck import DEFAULT_WORKERS
        self.assertEqual(DEFAULT_WORKERS, 2)
