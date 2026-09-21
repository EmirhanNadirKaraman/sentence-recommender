"""Wanting more of a channel, or less.

Two states and an absence, and the absence is the point: neutral is not a
third opinion, it is the lack of one. Setting aside demotes and never hides —
a channel you would rather not watch can still hold the one video that
teaches the word you need. Removing is a separate decision, kept in its
own list and undone from the settings page.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vocab.channel_taste import DOWN, UP, ChannelBlacklist, ChannelTaste
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


class BlacklistStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.store = ChannelBlacklist(Path(self._dir.name) / "state.sqlite3")

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_nothing_removed_to_begin_with(self) -> None:
        self.assertEqual(self.store.all(), {})

    def test_removing_and_restoring(self) -> None:
        self.store.add("UC1")
        self.store.add("UC2")
        self.assertEqual(list(self.store.all()), ["UC1", "UC2"])
        self.store.remove("UC1")
        self.assertEqual(list(self.store.all()), ["UC2"])

    def test_removing_twice_keeps_the_first_date(self) -> None:
        self.store.add("UC1")
        when = self.store.all()["UC1"]
        self.store.add("UC1")
        self.assertEqual(self.store.all()["UC1"], when)

    def test_a_missing_channel_is_ignored(self) -> None:
        self.store.add("")
        self.store.remove("")
        self.assertEqual(self.store.all(), {})

    def test_the_version_moves_on_every_change_and_only_then(self) -> None:
        start = self.store.version()
        self.store.add("UC1")
        self.store.add("UC1")          # already there: no change
        self.store.remove("UC1")
        self.store.remove("UC1")       # already gone: no change
        self.assertEqual(self.store.version(), start + 2)


class RemovalTest(unittest.TestCase):
    """A removed channel's sentences are dropped where every sentence
    passes on its way to a page -- the same gate a hidden sentence meets."""

    def setUp(self) -> None:
        from alignment.timing import Timing
        from config import Settings
        from context import Application
        from corpus.sentence import Sentence
        self._dir = tempfile.TemporaryDirectory()
        self.app = Application(Settings(
            state_path=Path(self._dir.name) / "state.sqlite3"))
        self.said = [
            Sentence("Aus dem einen Kanal.", timing=Timing("v1", 0.0, 1.0)),
            Sentence("Aus dem anderen.", timing=Timing("v2", 0.0, 1.0)),
            Sentence("Ohne Video."),
        ]

    def tearDown(self) -> None:
        self._dir.cleanup()

    def _ban(self, *videos: str) -> None:
        """Stand in for the catalogue's channel-to-video map."""
        self.app.blacklist.add("UC1")
        self.app._banned = (self.app.blacklist.version(), frozenset(videos))

    def test_nothing_removed_changes_nothing(self) -> None:
        self.assertEqual(self.app.apply_overrides(self.said), self.said)

    def test_the_channels_videos_are_dropped_and_the_rest_kept(self) -> None:
        self._ban("v1")
        self.assertEqual([s.text for s in self.app.apply_overrides(self.said)],
                         ["Aus dem anderen.", "Ohne Video."])

    def test_restoring_brings_them_back_without_a_restart(self) -> None:
        self._ban("v1")
        self.app.blacklist.remove("UC1")
        # The version moved, so the cached set is not trusted; with no
        # channel left there is nothing to look up and nothing is banned.
        self.assertEqual(self.app.apply_overrides(self.said), self.said)


class DoubtTest(unittest.TestCase):
    """A pair the judge says is not the word leaves the sentence at the
    same gate, with the lemma the pattern names."""

    def setUp(self) -> None:
        from config import Settings
        from context import Application
        from corpus.sentence import Sentence
        from vocab.entry import Unit
        self._dir = tempfile.TemporaryDirectory()
        self.app = Application(Settings(
            state_path=Path(self._dir.name) / "state.sqlite3"))
        self.heard = Unit.pattern("jdm. (Dat) gehören")
        self.lemma = Unit.lemma("gehören")
        self.have = Unit.pattern("etw./jdn. (Akk) haben")
        self.said = Sentence("Hast du gehört?",
                             units=frozenset({self.heard, self.lemma, self.have}),
                             surfaces=((self.heard, "gehört"), (self.have, "Hast")))

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_the_doubted_pattern_and_its_lemma_leave_the_sentence(self) -> None:
        self.app.answers.save(self.said.text, self.app.settings.judge_model, 1,
                              {"plain:u1": (0.05, None), "plain:u2": (0.9, None)},
                              units={"u1": self.heard, "u2": self.have})
        (out,) = self.app.apply_overrides([self.said])
        self.assertEqual(out.units, frozenset({self.have}))
        self.assertEqual(out.surfaces, ((self.have, "Hast"),))

    def test_a_hand_correction_outranks_the_judge(self) -> None:
        self.app.answers.save(self.said.text, self.app.settings.judge_model, 1,
                              {"plain:u1": (0.05, None)}, units={"u1": self.heard})
        self.app.overrides.set_units(self.said.text, {self.heard: "gehört"})
        (out,) = self.app.apply_overrides([self.said])
        self.assertEqual(out.units, frozenset({self.heard}))

    def test_nothing_doubted_changes_nothing(self) -> None:
        self.assertEqual(self.app.apply_overrides([self.said]), [self.said])


class MachineMadeTest(unittest.TestCase):
    """A channel marked machine-made sinks in the feed as a set-aside one
    does, and its sentences count half wherever anything ranks."""

    def setUp(self) -> None:
        from config import Settings
        from context import Application
        self._dir = tempfile.TemporaryDirectory()
        self.app = Application(Settings(
            state_path=Path(self._dir.name) / "state.sqlite3"))

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_it_is_a_taste_the_store_accepts_and_the_feed_weighs_down(self) -> None:
        from vocab.channel_taste import MACHINE
        from watchability import SET_ASIDE, taste_weight
        self.app.taste.set("UC1", MACHINE)
        self.assertEqual(self.app.taste.of("UC1"), MACHINE)
        self.assertEqual(taste_weight(MACHINE), SET_ASIDE)
        self.app.taste.set("UC1", None)
        self.assertIsNone(self.app.taste.of("UC1"))

    def test_its_sentences_are_a_verdict_on_every_page_that_ranks(self) -> None:
        from context import MACHINE_COST
        # Stand in for the catalogue query, as the removal test does.
        self.app._machine = (self.app.taste.version(), frozenset({"Gesagt von einer Maschine."}))
        self.app.overrides.mark("Gesagt von einer Maschine.", 0.8)
        self.app.overrides.mark("Gesagt von einem Menschen.", 0.8)
        said = self.app.verdicts()
        self.assertAlmostEqual(said["Gesagt von einer Maschine."], 0.8 * MACHINE_COST)
        self.assertAlmostEqual(said["Gesagt von einem Menschen."], 0.8)
        self.assertNotIn("Nie erwähnt.", said)

