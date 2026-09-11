"""When a video stops being worth asking about.

Two failures are in tension here. Settling an ambiguous refusal at once
wrote off forty good videos, because `unfetchable` cannot tell a deleted
video from a throttled request. But never settling it is its own bug: a
second pass over a channel spent its first thirty-four videos re-asking
questions the first pass had already failed to answer, and a third would
have done the same.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ingest.attempts import SETTLED, AttemptLog


class SettlingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.log = AttemptLog(Path(self._dir.name) / "state.sqlite3")

    def test_a_definite_verdict_settles_at_once(self) -> None:
        self.log.record("gone", "no-subtitles", "nothing hand-written")
        self.assertIn("gone", self.log.settled())

    def test_an_ambiguous_one_does_not(self) -> None:
        """It cannot tell a deleted video from a throttled request."""
        self.log.record("maybe", "unfetchable", "could not be inspected")
        self.assertNotIn("maybe", self.log.settled())

    def test_but_it_settles_after_repeated_failure(self) -> None:
        for _ in range(AttemptLog.GIVE_UP):
            self.log.record("maybe", "unfetchable", "again")
        self.assertIn("maybe", self.log.settled())

    def test_one_short_of_the_limit_is_still_open(self) -> None:
        for _ in range(AttemptLog.GIVE_UP - 1):
            self.log.record("maybe", "unfetchable", "again")
        self.assertNotIn("maybe", self.log.settled())

    def test_a_video_that_worked_is_never_settled(self) -> None:
        """However many times it is seen — it is in the catalogue, and
        `already_have` is what keeps it from being fetched twice."""
        for _ in range(AttemptLog.GIVE_UP + 2):
            self.log.record("good", "added")
        self.assertNotIn("good", self.log.settled())

    def test_a_later_success_is_what_the_log_remembers(self) -> None:
        self.log.record("late", "unfetchable", "throttled")
        self.log.record("late", "added")
        self.assertNotIn("late", self.log.settled())

    def test_counts_survive_a_new_log_over_the_same_file(self) -> None:
        path = Path(self._dir.name) / "state.sqlite3"
        for _ in range(AttemptLog.GIVE_UP):
            AttemptLog(path).record("maybe", "unfetchable")
        self.assertIn("maybe", AttemptLog(path).settled())

    def test_unfetchable_is_still_not_in_the_settled_outcomes(self) -> None:
        """The repeat rule is what settles it, not the outcome itself."""
        self.assertNotIn("unfetchable", SETTLED)
