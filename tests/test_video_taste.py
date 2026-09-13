"""What you think of a channel, inside the video walk.

A tie-break and never a weight. A walk over one channel is a different
curriculum rather than a preferred one, so taste may settle two videos that
teach comparably and must never lift a worse one over a better.

"Comparably" is banded, because exact equality would never fire: across 1,971
videos there are five tied groups and 421 of the 429 videos in them teach
nothing, which the walk stops before reaching. The rates are packed instead —
1,459 of the 1,550 that teach anything sit within 0.01 sentences a minute of
the next.
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from roadmap.videos import VideoWalk
from vocab.entry import Unit
from watchability import SET_ASIDE, SUBSCRIBED


@dataclass(frozen=True)
class _Sentence:
    units: frozenset


def s(*keys: str) -> _Sentence:
    return _Sentence(frozenset(Unit("lemma", k) for k in keys))


def u(key: str) -> Unit:
    return Unit("lemma", key)


class TieBreakTest(unittest.TestCase):
    """Two videos teaching the same amount, at the same length."""

    KNOWN = frozenset({u("ich")})

    def order(self, taste: dict[str, float] | None = None) -> list[str]:
        grouped = {"a": [s("ich", "alpha"), s("ich", "beta")],
                   "b": [s("ich", "gamma"), s("ich", "delta")]}
        walk = VideoWalk(grouped, self.KNOWN, {"a": 10.0, "b": 10.0},
                         floor=1, taste=taste)
        return [step.video for step in walk.build()]

    def test_without_an_opinion_the_name_decides(self) -> None:
        """Reproducible, which is what the name is in the key for.

        The key is maximised, so a tie falls to the *last* name rather than
        the first. That is long-standing behaviour and is pinned here because
        the taste tests below are only meaningful against a known baseline —
        picking `b` proves nothing when `b` already wins.
        """
        self.assertEqual(self.order(), ["b", "a"])

    def test_subscribing_wins_a_tie(self) -> None:
        """`a` loses on name, so only the opinion can put it first."""
        self.assertEqual(self.order({"a": SUBSCRIBED})[0], "a")

    def test_setting_aside_loses_a_tie(self) -> None:
        """`b` wins on name, so only the opinion can push it behind `a`."""
        self.assertEqual(self.order({"b": SET_ASIDE})[0], "a")

    def test_a_set_aside_video_is_still_in_the_plan(self) -> None:
        """Down, never out — the walk must still teach what it teaches."""
        self.assertEqual(sorted(self.order({"b": SET_ASIDE})), ["a", "b"])


class NeverAWeightTest(unittest.TestCase):
    """The property the doc asks for, and the reason this is not a multiplier."""

    def test_taste_cannot_lift_a_worse_video_over_a_better_one(self) -> None:
        """`b` teaches four times as much. Subscribing to `a` must not matter.

        A weight of 2.0 on the rate would put `a` first and quietly rewrite
        the curriculum; banding the rate before comparing is what stops it.
        """
        grouped = {
            "a": [s("ich", "alpha")],
            "b": [s("ich", "beta"), s("ich", "gamma"),
                  s("ich", "delta"), s("ich", "epsilon")],
        }
        walk = VideoWalk(grouped, frozenset({u("ich")}),
                         {"a": 10.0, "b": 10.0}, floor=1,
                         taste={"a": SUBSCRIBED, "b": SET_ASIDE})
        self.assertEqual([step.video for step in walk.build()][0], "b")

    def test_an_unmentioned_video_is_neutral(self) -> None:
        """An empty map must leave the order exactly as it was."""
        grouped = {"a": [s("ich", "alpha")], "b": [s("ich", "beta")]}
        plain, empty = (
            [step.video for step in
             VideoWalk(grouped, frozenset({u("ich")}),
                       {"a": 10.0, "b": 10.0}, floor=1, taste=given).build()]
            for given in (None, {}))
        self.assertEqual(plain, empty)
        self.assertEqual(plain, ["b", "a"])


if __name__ == "__main__":
    unittest.main()
