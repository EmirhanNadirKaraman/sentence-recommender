"""Appending to a build only under the rules that made it.

`catch_up` is the reason importing a video is quick: it analyses the videos a
build does not have yet and appends them, instead of re-analysing the whole
corpus. Every import command calls it, and so does the server.

What it did not do was check whether the build it is appending to was made by
the same analyser. `keep`, `well_formed` and the phrase matcher between them
decide what a unit *is*, so appending under changed rules leaves a corpus
whose two halves disagree -- with nothing stored to say where one ends. The
fingerprint that would have caught it was already being written on every
build; it simply was not read here.
"""
from __future__ import annotations

import unittest

from corpus.updater import Caught, CorpusUpdater


class _PastGuard(Exception):
    """Marks that the guard let the call through.

    Raised by the fake at the first step after the check, so "it was allowed
    to proceed" is asserted directly rather than inferred from whatever the
    real work happens to fail on next.
    """


class _Store:
    """Just enough corpus store to answer the guard."""

    def __init__(self, stale: dict[str, str]) -> None:
        self._stale = stale
        self.appended: list = []

    def stale(self) -> dict[str, str]:
        return dict(self._stale)

    def video_ids(self, build: str) -> set[str]:
        raise _PastGuard

    def load(self, *a, **k) -> list:
        return []

    def append(self, sentences, build) -> None:
        self.appended.append((build, sentences))


class _App:
    def __init__(self, store) -> None:
        self.corpus_store = store
        self.settings = None


class GuardTest(unittest.TestCase):
    def test_a_changed_analyser_refuses_the_append(self) -> None:
        store = _Store({"subtitle": "old-fingerprint"})
        caught = CorpusUpdater(_App(store)).catch_up("subtitle")
        self.assertEqual(caught.refused, "old-fingerprint")
        self.assertFalse(caught.anything)
        self.assertEqual(store.appended, [])

    def test_it_refuses_before_doing_any_work(self) -> None:
        """The guard is a decision taken up front, not something discovered
        halfway through: it never reaches the video source at all."""
        store = _Store({"subtitle": "old-fingerprint"})
        CorpusUpdater(_App(store)).catch_up("subtitle")   # no _PastGuard

    def test_a_build_with_matching_rules_is_allowed_through(self) -> None:
        store = _Store({})
        with self.assertRaises(_PastGuard):
            CorpusUpdater(_App(store)).catch_up("subtitle")

    def test_another_builds_staleness_is_not_this_ones(self) -> None:
        """`stale()` reports every build; only the one being appended to
        decides whether this append is safe."""
        store = _Store({"transcript": "old-fingerprint"})
        with self.assertRaises(_PastGuard):
            CorpusUpdater(_App(store)).catch_up("subtitle")


class ReportTest(unittest.TestCase):
    def test_a_refusal_says_what_to_do_about_it(self) -> None:
        line = Caught(0, 0, 0, refused="abc123").report()
        self.assertIn("different rules", line)
        self.assertIn("build-corpus", line)

    def test_an_ordinary_run_reports_both_counts(self) -> None:
        line = Caught(3, 120, 40).report()
        self.assertIn("120", line)
        self.assertIn("40", line)
        self.assertNotIn("different rules", line)


if __name__ == "__main__":
    unittest.main()
