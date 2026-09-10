"""What the study list already teaches, under whatever name it uses.

This is what stops a goal being blocked by its own bare form: `die Schule`
teaches `schule`, so the lemma arriving beside it is one word twice, not a
gap. It broke when the noun/verb split landed. The split gives a noun that
shares a lemma with a verb a capital — `Unternehmen` against `unternehmen` —
and `keep` stopped lowercasing so a verb frame could not claim a noun. But
`covered_forms` still wrote only the lowercase, so `das Unternehmen` covered
`unternehmen` and not `Unternehmen`, and the goal was blocked by the very
word it exists to teach.

Both cases are written now, and both halves of that are load-bearing.
"""
from __future__ import annotations

import unittest

from context import Application
from vocab.entry import Unit


def covered(*goals: Unit) -> frozenset[str]:
    """`covered_forms` over a made-up goal list, without an Application."""
    stub = type("Stub", (), {"goal_units": goals,
                             "PLACEHOLDERS": Application.PLACEHOLDERS})()
    return Application.covered_forms.func(stub)


class CoveredFormsTest(unittest.TestCase):
    def test_an_article_noun_covers_its_lemma(self) -> None:
        """The original job: `das Jahr` teaches `jahr`."""
        self.assertIn("jahr", covered(Unit.pattern("das Jahr")))

    def test_it_also_covers_the_capital(self) -> None:
        """`Unternehmen` is a noun that shares a lemma with a verb, so it
        keeps its capital — and `das Unternehmen` has to reach it."""
        self.assertIn("Unternehmen", covered(Unit.pattern("das Unternehmen")))

    def test_both_at_once(self) -> None:
        forms = covered(Unit.pattern("der Laden"))
        self.assertEqual({"Laden", "laden"} & forms, {"Laden", "laden"})

    def test_a_verb_frame_does_not_reach_the_noun(self) -> None:
        """The whole point of the split. The frame is written in lowercase,
        so it covers the verb and leaves the noun alone."""
        forms = covered(Unit.pattern("jdn. (Akk) / sich mit jdm. treffen"))
        self.assertIn("treffen", forms)
        self.assertNotIn("Treffen", forms)

    def test_placeholders_are_not_words(self) -> None:
        forms = covered(Unit.pattern("jdm. (Dat) etw. (Akk) geben"))
        self.assertIn("geben", forms)
        for junk in ("jdm", "etw", "akk", "dat"):
            self.assertNotIn(junk, forms, junk)

    def test_short_words_are_skipped(self) -> None:
        """Two letters carry no evidence and collide with everything."""
        self.assertNotIn("im", covered(Unit.pattern("im Jahr")))


if __name__ == "__main__":
    unittest.main()
