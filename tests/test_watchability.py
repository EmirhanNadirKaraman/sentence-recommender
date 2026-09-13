"""How well a video plays with your hands full.

Three bands multiplied, and the fourth was missing. Comprehension is measured
only over the lines that survived filtering, so a video most of whose talking
was dropped was judged on the part that happened to parse — and a Peppa Pig
episode whose track is largely English, keeping 46 of its 390 lines, came out
the easiest video in the corpus and the first thing the feed offered.

`ENOUGH_LINES` was meant to catch that and catches only half of it: it counts
the lines that survived, not the share that did. Forty-six clears a
forty-line bar. These pin both halves.
"""
from __future__ import annotations

import unittest

from watchability import ENOUGH_LINES, IDEAL_MINUTES, length_band, watchability


def score(comprehension=1.0, minutes=IDEAL_MINUTES, lines=ENOUGH_LINES,
          dialogue=None):
    return watchability(comprehension, minutes, lines, dialogue)


class CoverageTest(unittest.TestCase):
    def test_a_video_judged_on_a_tenth_of_itself_is_damped(self) -> None:
        """The case that sent Peppa to the top of the feed."""
        self.assertLess(score(lines=46, dialogue=390), score(lines=46) / 3)

    def test_a_video_that_kept_most_of_its_talking_is_not(self) -> None:
        """The ordinary case: coverage runs 56% at the lower quartile."""
        self.assertEqual(score(lines=400, dialogue=600), score(lines=400))

    def test_the_bar_is_half(self) -> None:
        self.assertEqual(score(lines=50, dialogue=100), score(lines=50))
        self.assertLess(score(lines=49, dialogue=100), score(lines=49))

    def test_omitting_it_damps_nothing(self) -> None:
        """Every caller did, before the fraction was available to them."""
        self.assertEqual(score(lines=46, dialogue=None), score(lines=46))

    def test_a_zero_total_is_not_a_division(self) -> None:
        self.assertEqual(score(lines=46, dialogue=0), score(lines=46))

    def test_it_only_ever_damps(self) -> None:
        """Coverage above the bar must not reward a video past its own score."""
        self.assertEqual(score(lines=90, dialogue=91), score(lines=90))


class BandsTest(unittest.TestCase):
    """The three that were already there, so the fourth cannot mask them."""

    def test_a_short_transcript_is_still_damped(self) -> None:
        self.assertLess(score(lines=5, dialogue=5), score(lines=ENOUGH_LINES))

    def test_half_understood_is_far_worse_than_half_as_good(self) -> None:
        self.assertLess(score(comprehension=0.5), score(comprehension=1.0) / 2)

    def test_length_still_counts(self) -> None:
        self.assertLess(score(minutes=90), score(minutes=IDEAL_MINUTES))

    def test_an_unrecorded_length_gets_the_benefit_of_the_doubt(self) -> None:
        self.assertEqual(length_band(None), 0.7)


if __name__ == "__main__":
    unittest.main()
