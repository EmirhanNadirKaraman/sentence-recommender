"""The walk's last resort: two new words from one sentence.

The roadmap halts when nothing anywhere is the sole unknown, and what is left
is stranded for good — 254 goals on this corpus, each said only in sentences
holding something else unknown too. Often that something is not on the study
list at all, so no amount of progress reaches it.

Relaxing pays two words at once to break the deadlock. It is gated as a last
resort and these tests exist to keep it one: a relaxed step must never be
taken while an i+1 step is available, because the whole value of the roadmap
is the order, and a scorer free to weigh two-word steps against one-word steps
throughout would spend the reader's attention faster for the same words.
"""
from __future__ import annotations

import unittest

from corpus.sentence import Sentence
from roadmap import CorpusIndex, KnownSet, UnitPriority
from roadmap.builder import RoadmapBuilder
from vocab.entry import Unit

A, B, C, D = (Unit.lemma(k) for k in "abcd")


def sentence(text: str, *units: Unit) -> Sentence:
    return Sentence(text=text, origin="t").with_units(frozenset(units), ())


def walk(sentences, relax: bool, **kw):
    index = CorpusIndex(sentences, KnownSet(frozenset()))
    builder = RoadmapBuilder(index, UnitPriority.build(()), relax=relax, **kw)
    return builder.build()


class RelaxTest(unittest.TestCase):
    def test_without_it_the_walk_stops_at_the_wall(self) -> None:
        steps = walk([sentence("a", A), sentence("bc", B, C)], relax=False)
        self.assertEqual([s.unit for s in steps], [A])

    def test_with_it_the_wall_is_climbed(self) -> None:
        steps = walk([sentence("a", A), sentence("bc", B, C)], relax=True)
        self.assertEqual(len(steps), 2)
        self.assertEqual({steps[1].unit, steps[1].beside}, {B, C})

    def test_the_easy_step_still_comes_first(self) -> None:
        """The order is the point. A relaxed step is a last resort, never a
        preference."""
        steps = walk([sentence("a", A), sentence("bc", B, C)], relax=True)
        self.assertIsNone(steps[0].beside)
        self.assertIsNotNone(steps[1].beside)

    def test_both_words_are_learned(self) -> None:
        """Otherwise the next pass finds the same wall and never moves."""
        steps = walk([sentence("bc", B, C), sentence("bcd", B, C, D)], relax=True)
        learned = {s.unit for s in steps} | {s.beside for s in steps if s.beside}
        self.assertIn(D, learned)

    def test_a_plain_step_carries_no_partner(self) -> None:
        steps = walk([sentence("a", A)], relax=True)
        self.assertIsNone(steps[0].beside)

    def test_three_unknowns_are_still_out_of_reach(self) -> None:
        """Relaxing buys one extra word, not an open door. Three new words in
        a sentence is not comprehensible input."""
        steps = walk([sentence("bcd", B, C, D)], relax=True)
        self.assertEqual(steps, [])

    def test_nothing_to_walk_is_not_an_error(self) -> None:
        self.assertEqual(walk([], relax=True), [])
