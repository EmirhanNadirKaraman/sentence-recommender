"""The greedy walk and the incremental index it runs on.

The index maintains unknown counts, the frontier and the lookahead by hand as
units are learned.  A cross-check against a recomputed-from-scratch version is
the point of these tests: an incremental structure that drifts would still
produce a plausible-looking roadmap.
"""
from __future__ import annotations

import unittest
from collections import Counter

from corpus.sentence import Sentence
from roadmap import CorpusIndex, KnownSet, RoadmapBuilder, UnitPriority
from vocab.entry import Unit


def sentence(text: str, *keys: str) -> Sentence:
    return Sentence(text=text).with_units(frozenset(Unit.lemma(k) for k in keys))


class CorpusIndexTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sentences = [
            sentence("a", "ich", "sein"),              # 0 unknown
            sentence("b", "ich", "sein", "haus"),      # 1 unknown  -> frontier
            sentence("c", "ich", "haus", "baum"),      # 2 unknown  -> lookahead
            sentence("d", "ich", "haus", "baum", "x"),  # 3 unknown
        ]
        self.known = KnownSet({Unit.lemma("ich"), Unit.lemma("sein")})
        self.index = CorpusIndex(self.sentences, self.known)

    def test_initial_state(self) -> None:
        self.assertEqual(self.index.readable, 1)
        self.assertEqual(list(self.index.candidates()), [Unit.lemma("haus")])
        self.assertEqual(self.index.unlocks(Unit.lemma("haus")), 1)
        self.assertEqual(self.index.unlocks(Unit.lemma("baum")), 1)

    def test_learning_moves_every_state(self) -> None:
        self.index.learn(Unit.lemma("haus"))
        self.assertEqual(self.index.readable, 2)          # "b" became readable
        self.assertEqual(self.index.unknown_count(2), 1)  # "c" joined frontier
        self.assertEqual(self.index.unknown_count(3), 2)  # "d" joined lookahead
        self.assertEqual(list(self.index.candidates()), [Unit.lemma("baum")])
        self.assertEqual(self.index.unlocks(Unit.lemma("baum")), 1)
        self.assertEqual(self.index.unlocks(Unit.lemma("x")), 1)

    def test_incremental_state_matches_a_fresh_rebuild(self) -> None:
        """Learning step by step must leave the index where a rebuild would."""
        for key in ("haus", "baum", "x"):
            self.index.learn(Unit.lemma(key))
            rebuilt = CorpusIndex(self.sentences, KnownSet(self.known.units))
            self.assertEqual(self.index.readable, rebuilt.readable)
            self.assertEqual(
                {u: sorted(p) for u, p in self.index.candidates().items()},
                {u: sorted(p) for u, p in rebuilt.candidates().items()},
            )
            for unit in {u for s in self.sentences for u in s.units}:
                self.assertEqual(
                    self.index.unlocks(unit), rebuilt.unlocks(unit),
                    msg=f"lookahead diverged for {unit} after learning {key}",
                )


class RoadmapBuilderTest(unittest.TestCase):
    def test_prefers_the_unit_that_unlocks_more(self) -> None:
        sentences = [
            sentence("one", "ich", "a"),
            sentence("two", "ich", "b"),
            sentence("three", "ich", "b", "c"),   # b also brings this to i+1
        ]
        known = KnownSet({Unit.lemma("ich")})
        index = CorpusIndex(sentences, known)
        priority = UnitPriority({}, Counter())
        plan = RoadmapBuilder(index, priority, priority_weight=0.0).build()
        self.assertEqual(plan[0].unit, Unit.lemma("b"))
        self.assertEqual(plan[0].gain, 2)          # readable now + one unlocked

    def test_priority_outranks_a_small_gain(self) -> None:
        sentences = [sentence("one", "ich", "rare"), sentence("two", "ich", "common")]
        known = KnownSet({Unit.lemma("ich")})
        index = CorpusIndex(sentences, known)
        priority = UnitPriority({"common": 0, "rare": 999}, Counter())
        plan = RoadmapBuilder(index, priority, priority_weight=3.0).build()
        self.assertEqual(plan[0].unit, Unit.lemma("common"))

    def test_stops_when_nothing_is_i_plus_one(self) -> None:
        sentences = [sentence("hard", "a", "b", "c")]
        index = CorpusIndex(sentences, KnownSet())
        plan = RoadmapBuilder(index, UnitPriority({}, Counter())).build()
        self.assertEqual(plan, [])

    def test_every_step_teaches_exactly_one_new_thing(self) -> None:
        sentences = [
            sentence("one", "ich", "a"),
            sentence("two", "ich", "a", "b"),
            sentence("three", "ich", "a", "b", "c"),
        ]
        known = KnownSet({Unit.lemma("ich")})
        index = CorpusIndex(sentences, known)
        seen = set(known.units)
        for step in RoadmapBuilder(index, UnitPriority({}, Counter())).build():
            self.assertEqual(step.sentence.units - seen, {step.unit})
            seen.add(step.unit)


class UnitPriorityTest(unittest.TestCase):
    def test_both_kinds_land_on_the_same_scale(self) -> None:
        """A pattern scored at zero would hand every word a flat handicap."""
        priority = UnitPriority({"und": 0, "selten": 999}, Counter({"P": 40, "Q": 1}))
        self.assertAlmostEqual(priority.of(Unit.lemma("und")), 1.0)
        self.assertAlmostEqual(priority.of(Unit.pattern("P")), 1.0)
        self.assertLess(priority.of(Unit.pattern("Q")), 0.1)
        self.assertEqual(priority.of(Unit.lemma("unlisted")), 0.0)


if __name__ == "__main__":
    unittest.main()
