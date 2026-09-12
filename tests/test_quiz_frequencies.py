"""Counting how often a word is said, when "all" is not the name of a build.

The quiz ranks what to ask about by how often the corpus says it, and drops
anything the corpus never says -- being wrong about a word that never appears
costs nothing. That filter is only sound if the count is real.

`unit_counts` matches build names exactly. The page's source switch says
`all`, meaning every build, and passing that through matched no build: every
unit came back said zero times, so the filter dropped all 877 of them and the
page reported that every assumed-known word had been checked. It had asked
about 24 of 748.
"""
from __future__ import annotations

import unittest
from collections import Counter

from commands.quiz import QuizCommand


class _Store:
    """Answers only for build names it actually holds, as Postgres does."""

    HELD = {"subtitle": 900, "transcript": 100}

    def builds(self, teachable_only: bool = False) -> dict[str, int]:
        return dict(self.HELD)

    def unit_counts(self, *builds: str) -> Counter:
        got: Counter = Counter()
        for build in builds:
            if build in self.HELD:
                got[("lemma", f"said-in-{build}")] += 7
        return got


class _App:
    def __init__(self) -> None:
        self.corpus_store = _Store()


class FrequenciesTest(unittest.TestCase):
    def test_all_means_every_build(self) -> None:
        """The regression. `all` reached the query as a build name and
        matched nothing."""
        counts = QuizCommand._frequencies(_App(), "all")
        self.assertEqual(len(counts), 2)
        self.assertTrue(all(n for n in counts.values()))

    def test_one_build_counts_only_that_build(self) -> None:
        counts = QuizCommand._frequencies(_App(), "subtitle")
        self.assertEqual([u.key for u in counts], ["said-in-subtitle"])

    def test_a_joined_source_counts_both(self) -> None:
        """The switch writes `subtitle+transcript` for a pair."""
        counts = QuizCommand._frequencies(_App(), "subtitle+transcript")
        self.assertEqual(len(counts), 2)

    def test_an_empty_source_is_every_build_too(self) -> None:
        self.assertEqual(len(QuizCommand._frequencies(_App(), "")), 2)

    def test_an_unknown_build_counts_nothing(self) -> None:
        """Still the honest answer: a build that is not there says nothing."""
        self.assertEqual(QuizCommand._frequencies(_App(), "nonesuch"),
                         Counter())


if __name__ == "__main__":
    unittest.main()
