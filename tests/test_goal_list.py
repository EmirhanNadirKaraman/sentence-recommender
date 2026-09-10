"""One goal per word.

The study list writes `nennen` and it also writes `jdn. (Akk) + Name (Akk)
nennen`. Both became goals, and they are one German word — so every sentence
saying it carried two unknown units and could never be i+1 for either. 263
sentences for that verb alone, "So nennt man das Fastenbrechen" among them,
one word away from readable and unreachable for ever.

`covered_forms` cannot reach this: `_drop_duplicates` keeps anything that is
`in goals`, and the bare verb is itself a goal.
"""
from __future__ import annotations

import unittest

from vocab.entry import Unit
from vocab.goal_list import GoalList


class OneGoalPerVerbTest(unittest.TestCase):
    def keep(self, *units: Unit) -> set[Unit]:
        return set(GoalList._one_goal_per_verb(units))

    def test_the_frame_swallows_the_bare_verb(self) -> None:
        frame = Unit.pattern("jdn. (Akk) + Name (Akk) nennen")
        self.assertEqual(self.keep(frame, Unit.lemma("nennen")), {frame})

    def test_the_frame_is_the_one_that_survives(self) -> None:
        """It teaches the verb and the cases it governs; the lemma teaches
        only the verb."""
        frame = Unit.pattern("jdm. (Dat) helfen")
        self.assertIn(frame, self.keep(Unit.lemma("helfen"), frame))

    def test_an_article_noun_is_not_a_frame(self) -> None:
        """`das Russisch` would otherwise eat the adjective `russisch`, and
        `der Morgen` the adverb `morgen`."""
        for entry, word in (("das Russisch", "russisch"),
                            ("der Morgen", "morgen"),
                            ("der Halt", "halt")):
            kept = self.keep(Unit.pattern(entry), Unit.lemma(word))
            self.assertIn(Unit.lemma(word), kept, entry)

    def test_a_noun_keeps_its_place_against_a_verb_frame(self) -> None:
        """A capitalised key is a noun that shares a lemma with a verb — a
        different word, whatever the frame governs."""
        kept = self.keep(Unit.pattern("etw. (Akk) essen"), Unit("lemma", "Essen"))
        self.assertIn(Unit("lemma", "Essen"), kept)

    def test_a_bare_verb_with_no_frame_is_untouched(self) -> None:
        self.assertEqual(self.keep(Unit.lemma("gehen")), {Unit.lemma("gehen")})

    def test_a_frame_with_no_bare_verb_is_untouched(self) -> None:
        frame = Unit.pattern("jdm. (Dat) etw. (Akk) erzählen")
        self.assertEqual(self.keep(frame), {frame})

    def test_order_is_kept(self) -> None:
        """The list is written most-useful-first and that is its only
        ranking."""
        a, b = Unit.pattern("etw. (Akk) sehen"), Unit.lemma("baum")
        self.assertEqual(GoalList._one_goal_per_verb((a, b)), (a, b))


if __name__ == "__main__":
    unittest.main()
