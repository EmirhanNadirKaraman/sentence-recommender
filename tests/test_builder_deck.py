"""The deck the walk stores must be the deck the page would rebuild.

Two ways of choosing examples exist, and they have to agree: the walk writes
one into the roadmap so a page can be served with no corpus in memory, and
`CorpusIndex.examples` builds the same thing live. They drifted twice.

The first time, the walk ranked without the video maps and 61 of 400 units
opened on a different sentence depending on which path served them. The
second time is what these tests pin: `CorpusIndex.examples` spread its
choices so a card would not repeat a collocation, and the walk did not, so
every stored deck was the plain ranking — `der Fall` showed `auf jeden Fall`
three times with a different use of the word four rows below it.

The `_example` case is the same failure one level down. The teaching sentence
is picked separately from the examples beside it, and it was picked on
quality alone. Quality reads characters; it cannot see that a sentence has no
verb. So the marks that said so reached the deck and never the step.
"""
from __future__ import annotations

import unittest

from corpus.sentence import Sentence
from roadmap import CorpusIndex, KnownSet, RoadmapBuilder, UnitPriority
from vocab.entry import Unit

FALL = Unit.lemma("fall")
KNOWN = {Unit.lemma("ich"), Unit.lemma("sein")}

# Lengths chosen so the plain ranking *must* put the two repeats first:
# `quality` peaks at nine to eleven words, so the pair sits on the peak and
# the distinct sentence sits below it. Without that the distinct one wins on
# quality alone, the test passes whether or not anything spreads, and the bug
# it exists to catch walks straight through it. It did.
REPEATS_ONE = "Ich bin auf jeden Fall sehr froh gewesen heute."     # 9 words
REPEATS_TWO = "Auf jeden Fall bin ich sehr froh und dabei."         # 9 words
DIFFERENT = "Das ist der Fall wenn ich gehe."                       # 7 words


def sentence(text: str, *keys: str) -> Sentence:
    return Sentence(text=text).with_units(
        frozenset(Unit.lemma(k) for k in keys))


def walk(sentences, verdicts=None):
    index = CorpusIndex(sentences, KnownSet(KNOWN))
    return RoadmapBuilder(index, UnitPriority.build(()), 0.0,
                          frozenset({FALL}), verdicts=verdicts).build()


class StoredDeckIsSpreadTest(unittest.TestCase):
    def test_the_walk_does_not_store_the_same_collocation_twice(self) -> None:
        plan = walk([sentence(REPEATS_ONE, "ich", "sein", "fall"),
                     sentence(REPEATS_TWO, "ich", "sein", "fall"),
                     sentence(DIFFERENT, "ich", "sein", "fall")])
        step = next(s for s in plan if s.unit == FALL)
        shown = [s.text for s in step.examples[:2]]
        repeated = [text for text in shown if "jeden fall" in text.lower()]
        self.assertLessEqual(len(repeated), 1, shown)

    def test_the_other_use_of_the_word_is_reached_for(self) -> None:
        plan = walk([sentence(REPEATS_ONE, "ich", "sein", "fall"),
                     sentence(REPEATS_TWO, "ich", "sein", "fall"),
                     sentence(DIFFERENT, "ich", "sein", "fall")])
        step = next(s for s in plan if s.unit == FALL)
        self.assertIn(DIFFERENT, [s.text for s in step.examples[:2]])

    def test_a_full_deck_is_still_stored_when_nothing_differs(self) -> None:
        """Rejected candidates fill up at the end rather than being dropped."""
        plan = walk([sentence(REPEATS_ONE, "ich", "sein", "fall"),
                     sentence(REPEATS_TWO, "ich", "sein", "fall")])
        step = next(s for s in plan if s.unit == FALL)
        self.assertEqual(len(step.examples), 2)


class TeachingSentenceReadsVerdictsTest(unittest.TestCase):
    def test_a_marked_sentence_is_not_what_the_step_teaches(self) -> None:
        marked = "Zum Beispiel von Markus Söder dem Fall der CSU heute."
        fine = "Das ist der Fall wenn ich hier nicht mehr sein kann."
        plan = walk([sentence(marked, "ich", "sein", "fall"),
                     sentence(fine, "ich", "sein", "fall")],
                    verdicts={marked: 0.4})
        step = next(s for s in plan if s.unit == FALL)
        self.assertEqual(step.sentence.text, fine)

    def test_without_a_verdict_nothing_moves(self) -> None:
        """A missing verdict is no opinion, not a bad score."""
        marked = "Zum Beispiel von Markus Söder dem Fall der CSU heute."
        fine = "Das ist der Fall wenn ich hier nicht mehr sein kann."
        pair = [sentence(marked, "ich", "sein", "fall"),
                sentence(fine, "ich", "sein", "fall")]
        plain = next(s for s in walk(pair) if s.unit == FALL)
        empty = next(s for s in walk(pair, verdicts={}) if s.unit == FALL)
        self.assertEqual(plain.sentence.text, empty.sentence.text)

    def test_a_marked_sentence_is_still_taught_when_it_is_all_there_is(self) -> None:
        """Demoted, never deleted — the word still gets taught."""
        only = "Zum Beispiel von Markus Söder dem Fall der CSU heute."
        plan = walk([sentence(only, "ich", "sein", "fall")],
                    verdicts={only: 0.4})
        step = next(s for s in plan if s.unit == FALL)
        self.assertEqual(step.sentence.text, only)


if __name__ == "__main__":
    unittest.main()
