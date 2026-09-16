"""A card's three examples should teach three things, not one thing thrice.

`der Fall` opened on `auf jeden Fall` three times over, while `Das wäre der
Fall, wenn es Schengen nicht mehr gäbe.` sat unused in its own candidate
list. `der Mensch` showed a sentence beside a copy of itself that differed by
one letter of dialect.

Both are caught on word trigrams: the first by asking whether a trigram
containing the taught word repeats, the second by asking how much the two
sentences overlap at all.
"""
from __future__ import annotations

import unittest

from corpus.sentence import Sentence
from roadmap.examples import spread
from vocab.entry import Unit

FALL = Unit("pattern", "der Fall")
MENSCH = Unit("lemma", "der Mensch")


def sentence(text: str, unit: Unit, surface: str) -> Sentence:
    return Sentence(text=text, units=frozenset({unit}),
                    surfaces=((unit, surface),))


class CollocationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = [
            sentence("Also, ich glaube, man könnte auf jeden Fall noch mehr "
                     "machen.", FALL, "Fall"),
            sentence("Ja auf jeden Fall, so machen wir das in Deutschland.",
                     FALL, "Fall"),
            sentence("Ja, das ist auf jeden Fall auch anders in Mexiko.",
                     FALL, "Fall"),
            sentence("Das wäre der Fall, wenn es Schengen nicht mehr gäbe.",
                     FALL, "der Fall"),
            sentence("Im Fall von George Floyd ist aber genau das passiert.",
                     FALL, "Fall"),
        ]

    def test_the_same_collocation_is_not_shown_twice(self) -> None:
        chosen = [s.text for s in spread(self.candidates, FALL, 3)]
        said = [text for text in chosen if "auf jeden Fall" in text]
        self.assertEqual(len(said), 1, chosen)

    def test_the_best_example_still_comes_first(self) -> None:
        """Greedy down the ranked list: the sentence the step is taught with
        does not move, only the ones beside it."""
        self.assertEqual(spread(self.candidates, FALL, 3)[0],
                         self.candidates[0])

    def test_it_reaches_past_the_repeats_for_variety(self) -> None:
        chosen = [s.text for s in spread(self.candidates, FALL, 3)]
        self.assertIn("Das wäre der Fall, wenn es Schengen nicht mehr gäbe.",
                      chosen)

    def test_a_full_card_beats_a_varied_one(self) -> None:
        """Where the corpus says a word one way only, the repetition is the
        truth about the corpus and the card is still filled."""
        only = self.candidates[:3]
        self.assertEqual(len(spread(only, FALL, 3)), 3)


class NearDuplicateTest(unittest.TestCase):
    def test_a_sentence_is_not_shown_beside_a_copy_of_itself(self) -> None:
        candidates = [
            sentence("Ech find', die machen es einem sehr einfach, die "
                     "Menschen da.", MENSCH, "die Menschen"),
            sentence("Ich find', die machen es einem sehr einfach, die "
                     "Menschen da.", MENSCH, "die Menschen"),
            sentence("Der Mensch glaubt immer das, was er glauben will.",
                     MENSCH, "Der Mensch"),
        ]
        chosen = spread(candidates, MENSCH, 2)
        self.assertEqual(chosen[0], candidates[0])
        self.assertEqual(chosen[1], candidates[2])

    def test_a_card_is_never_filled_with_an_exact_repeat(self) -> None:
        """A short card beats one showing the same sentence twice. Card 3865
        did exactly that: the same line imported from two builds, both kept
        because the fill did not look at what it was filling with."""
        twice = "Bitte detaillieren Sie die Kosten für jeden einzelnen Punkt."
        candidates = [sentence(twice, MENSCH, "Mensch"),
                      sentence(twice, MENSCH, "Mensch")]
        self.assertEqual(len(spread(candidates, MENSCH, 3)), 1)

    def test_identical_text_is_caught(self) -> None:
        twice = "Das Wort Weib benutzt heute kaum noch ein Mensch."
        candidates = [sentence(twice, MENSCH, "Mensch"),
                      sentence(twice, MENSCH, "Mensch"),
                      sentence("Er ist ein Mensch, aber noch viel mehr als "
                               "das.", MENSCH, "ein Mensch")]
        chosen = [s.text for s in spread(candidates, MENSCH, 2)]
        self.assertEqual(len(set(chosen)), 2, chosen)

    def test_different_sentences_sharing_the_word_are_both_kept(self) -> None:
        """The test is about repetition, not about the word itself — every
        candidate contains the taught word by construction."""
        candidates = [
            sentence("Der Mensch glaubt immer das, was er glauben will.",
                     MENSCH, "Der Mensch"),
            sentence("Sie ist der beste Mensch, den ich kenne!",
                     MENSCH, "der beste Mensch"),
        ]
        self.assertEqual(len(spread(candidates, MENSCH, 2)), 2)


class SameMeaningTest(unittest.TestCase):
    """One sentence rewritten, sharing neither a collocation nor its wording.

    `Du würdest doch mich nicht töten, deinen Freund Frank.` and `Du würdest
    doch nicht deinen alten Freund Frank Bimbel töten.` share no trigram
    holding the taught word, and their overall overlap is 0.46 — under the
    line. 87 of the 3,807 cards carried a pair like this.
    """

    TOETEN = Unit("lemma", "töten")

    def test_a_rewritten_sentence_is_not_shown_beside_its_original(self) -> None:
        candidates = [
            sentence("Du würdest doch mich nicht töten, deinen Freund Frank.",
                     self.TOETEN, "töten"),
            sentence("Du würdest doch nicht deinen alten Freund Frank Bimbel "
                     "töten.", self.TOETEN, "töten"),
            sentence("Man darf einen anderen Menschen niemals einfach so "
                     "töten.", self.TOETEN, "töten"),
        ]
        chosen = spread(candidates, self.TOETEN, 2)
        self.assertEqual(chosen[0], candidates[0])
        self.assertEqual(chosen[1], candidates[2])

    def test_two_different_sentences_are_both_kept(self) -> None:
        """The threshold sits well above the mean pair, so ordinary variety
        is untouched — it is set at 0.90 against a corpus mean of 0.598."""
        candidates = [
            sentence("Man darf einen anderen Menschen niemals einfach so "
                     "töten.", self.TOETEN, "töten"),
            sentence("Im Krieg töten Soldaten leider auch ganz normale "
                     "Menschen.", self.TOETEN, "töten"),
        ]
        self.assertEqual(len(spread(candidates, self.TOETEN, 2)), 2)


class LimitTest(unittest.TestCase):
    def test_one_example_needs_no_comparison(self) -> None:
        one = [sentence("Der Mensch glaubt immer das, was er will.",
                        MENSCH, "Der Mensch")]
        self.assertEqual(spread(one, MENSCH, 1), one)

    def test_nothing_in_nothing_out(self) -> None:
        self.assertEqual(spread([], MENSCH, 3), [])

    def test_a_sentence_too_short_for_a_trigram(self) -> None:
        candidates = [sentence("Ein Mensch.", MENSCH, "Mensch"),
                      sentence("Ein Mensch.", MENSCH, "Mensch"),
                      sentence("Der Mensch glaubt immer das, was er will.",
                               MENSCH, "Der Mensch")]
        chosen = [s.text for s in spread(candidates, MENSCH, 2)]
        self.assertEqual(len(set(chosen)), 2, chosen)


if __name__ == "__main__":
    unittest.main()
