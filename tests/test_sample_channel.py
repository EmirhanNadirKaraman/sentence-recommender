"""Sampling a channel without importing it.

The command exists because deciding by importing is expensive and, worse,
self-defeating: every video it touches gets an attempt recorded against it,
and enough of those settle a video for good, so a throttled run can write off
a channel it never actually read.

Both tests here are of arithmetic that has been wrong in production. `spread`
is the fix for sampling the head of a listing, which misjudged Kurzgesagt by
a factor of four in one direction and MrWissen2go's back catalogue in the
other. The pool split is the fix for calling an already-refused video an
opportunity.
"""
from __future__ import annotations

import unittest

from commands.sample_channel import spread


class SpreadTest(unittest.TestCase):
    def test_it_takes_both_ends(self) -> None:
        """A listing is newest-first, so the oldest upload is only ever seen
        if the sample reaches the end. Sampling the head is the bug."""
        picked = spread([str(i) for i in range(100)], 5)
        self.assertEqual(picked[0], "0")
        self.assertEqual(picked[-1], "99")

    def test_it_spaces_them_evenly(self) -> None:
        self.assertEqual(spread([str(i) for i in range(11)], 3),
                         ["0", "5", "10"])

    def test_asking_for_more_than_there_is_gives_everything(self) -> None:
        self.assertEqual(spread(["a", "b"], 9), ["a", "b"])

    def test_asking_for_one_gives_one(self) -> None:
        self.assertEqual(spread(["a", "b", "c"], 1), ["a"])

    def test_it_never_repeats_a_video(self) -> None:
        """A repeat would quietly shrink the sample and inflate confidence."""
        picked = spread([str(i) for i in range(50)], 12)
        self.assertEqual(len(picked), len(set(picked)))

    def test_an_empty_channel_is_not_an_error(self) -> None:
        self.assertEqual(spread([], 5), [])


if __name__ == "__main__":
    unittest.main()
