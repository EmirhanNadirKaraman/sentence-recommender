"""Wanting more of a channel, or less.

Two states and an absence, and the absence is the point: neutral is not a
third opinion, it is the lack of one. Setting aside demotes and never hides —
a channel you would rather not watch can still hold the one video that
teaches the word you need, and `video_blacklist` is what removes something,
a video at a time and deliberately.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vocab.channel_taste import DOWN, UP, ChannelTaste
from watchability import SET_ASIDE, SUBSCRIBED, taste_weight


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.store = ChannelTaste(Path(self._dir.name) / "state.sqlite3")

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_nothing_said_is_no_opinion(self) -> None:
        self.assertIsNone(self.store.of("UC1"))
        self.assertEqual(self.store.all(), {})

    def test_it_remembers_both_directions(self) -> None:
        self.store.set("UC1", UP)
        self.store.set("UC2", DOWN)
        self.assertEqual(self.store.all(), {"UC1": UP, "UC2": DOWN})

    def test_changing_your_mind_replaces_rather_than_adds(self) -> None:
        self.store.set("UC1", UP)
        self.store.set("UC1", DOWN)
        self.assertEqual(self.store.all(), {"UC1": DOWN})

    def test_clearing_removes_the_row(self) -> None:
        """Neutral is the absence of an opinion, not a stored third state."""
        self.store.set("UC1", UP)
        self.store.set("UC1", None)
        self.assertEqual(self.store.all(), {})

    def test_an_unknown_taste_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.store.set("UC1", "sideways")

    def test_a_missing_channel_is_ignored(self) -> None:
        self.store.set("", UP)
        self.assertEqual(self.store.all(), {})

    def test_the_version_moves_on_every_change(self) -> None:
        start = self.store.version()
        self.store.set("UC1", UP)
        self.store.set("UC1", DOWN)
        self.store.set("UC1", None)
        self.assertEqual(self.store.version(), start + 3)

    def test_it_survives_being_reopened(self) -> None:
        self.store.set("UC1", UP)
        again = ChannelTaste(Path(self._dir.name) / "state.sqlite3")
        self.assertEqual(again.of("UC1"), UP)


class WeightTest(unittest.TestCase):
    def test_no_opinion_changes_nothing(self) -> None:
        self.assertEqual(taste_weight(None), 1.0)

    def test_subscribing_lifts(self) -> None:
        self.assertGreater(taste_weight(UP), 1.0)
        self.assertEqual(taste_weight(UP), SUBSCRIBED)

    def test_setting_aside_demotes(self) -> None:
        self.assertLess(taste_weight(DOWN), 1.0)
        self.assertEqual(taste_weight(DOWN), SET_ASIDE)

    def test_setting_aside_never_hides(self) -> None:
        """The whole difference between this and the blacklist.

        A zero here would drop every video on the channel out of the feed
        however good it is, which is a different feature and already exists.
        """
        self.assertGreater(taste_weight(DOWN), 0.0)

    def test_an_unknown_value_is_treated_as_no_opinion(self) -> None:
        self.assertEqual(taste_weight("sideways"), 1.0)


class OrderTest(unittest.TestCase):
    """What the ranking does with the weights, on the numbers it really sees."""

    # The top of the feed as measured: a steep head and a long flat tail.
    ROWS = [("peppa", 0.0733), ("praeps", 0.0609), ("wahrheit", 0.0107),
            ("wm2026", 0.0080), ("horror", 0.0066)]

    def rank(self, taste: dict[str, str]) -> list[str]:
        return [v for v, _ in sorted(
            self.ROWS, key=lambda r: -r[1] * taste_weight(taste.get(r[0])))]

    def test_setting_the_top_aside_moves_it_down_not_out(self) -> None:
        order = self.rank({"peppa": DOWN})
        self.assertIn("peppa", order)
        self.assertNotEqual(order[0], "peppa")

    def test_subscribing_lifts_a_video_past_its_neighbours(self) -> None:
        self.assertEqual(self.rank({"wahrheit": UP})[0], "peppa")
        self.assertEqual(self.rank({"wm2026": UP, "peppa": DOWN})[0], "praeps")

    def test_no_opinions_leaves_the_order_alone(self) -> None:
        self.assertEqual(self.rank({}), [v for v, _ in self.ROWS])


if __name__ == "__main__":
    unittest.main()
