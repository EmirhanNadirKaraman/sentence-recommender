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
