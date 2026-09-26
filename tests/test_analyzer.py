"""The analyser's separable-verb folding.

Found by reading a gloss where `trage ... ein` was credited as `tragen`.
The fold is old and mostly works — measured at 83% of the separable verbs
the tagger finds — and these are the two places it leaked.
"""
from __future__ import annotations

import unittest


class SeparableVerbTest(unittest.TestCase):
    """Separable verbs, whose halves the parse sometimes fails to join.

    The fold itself is old — the parse hangs the particle under its verb as
    `svp` and `_units` glues them. These are the two places it leaked, both
    found by reading `trage ... ein` credited as `tragen`.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from context import Application
        cls.app = Application()

    def units(self, text: str) -> set[str]:
        from corpus.sentence import Sentence
        done = self.app.analyzer.analyze_all([Sentence(text=text)])
        return {u.key for u in done[0].units}

    def test_a_zu_infinitive_keeps_its_prefix_and_loses_the_zu(self) -> None:
        """`abzunehmen` is `abnehmen`. The model folds some of these itself
        and leaves others as their own surface, and neither guard in
        `_verb_lemma` catches that: one wants a lemma unlike the surface, the
        other exempts everything ending `-en`."""
        for text, want in (
                ("Das ist eine gute Idee, um abzunehmen.", "abnehmen"),
                ("Das kann befriedigend sein, die abzuhaken.", "abhaken"),
                ("Oswald hatte den Befehl abzudrücken.", "abdrücken")):
            with self.subTest(want):
                self.assertIn(want, self.units(text))

    def test_the_zu_that_is_a_prefix_is_left_alone(self) -> None:
        """`zunehmen` is not the zu-infinitive of `nehmen`."""
        self.assertIn("zunehmen", self.units("Ich möchte zunehmen."))

    def test_an_imperative_still_folds(self) -> None:
        """`Räum bitte dein Zimmer auf!` — the parse marks `auf` as `svp` and
        then tags `Räum` NOUN, and requiring the tag threw the fold away."""
        self.assertIn("aufräumen", self.units("Räum bitte dein Zimmer auf!"))

    def test_nothing_is_folded_that_does_not_spell_a_verb(self) -> None:
        """The guard is the table, asked about the *combined* word. Without
        it the imperative branch would invent `aufräum` as readily."""
        got = self.units("Räum bitte dein Zimmer auf!")
        self.assertNotIn("aufräum", got)
        self.assertNotIn("räum", got)

    def test_the_ordinary_case_is_untouched(self) -> None:
        for text, want in (("Er steht jeden Morgen früh auf.", "aufstehen"),
                           ("Wir fangen jetzt mit der Arbeit an.", "anfangen"),
                           ("Aber ich trage sie nicht als Fehler ein.", "eintragen")):
            with self.subTest(want):
                self.assertIn(want, self.units(text))

    def test_a_mistagged_zu_infinitive_is_still_folded(self) -> None:
        """The first version of this gated on the `VVIZU` tag, and a rebuilt
        corpus still held 235 of them: the tagger reaches for `VVINF` and
        `VVPP` too. The guard is the table, not the tag."""
        self.assertIn("abbrechen", self.units(
            "Es wäre einfacher, große Eisstücke abzubrechen."))

    def test_a_prefix_that_ends_in_zu_is_not_split_there(self) -> None:
        """`hinzu`, `dazu` and `herzu` end in `zu`, so the first `zu` in
        `hinzuziehen` is not the infinitive marker — and splitting there
        spells `hinziehen`, a real verb and the wrong one. The repair must
        refuse that position and still find the marker in `hinzuzufügen`.

        Tested on the rule rather than through a sentence: the parser hands
        back `hinziehen` for `hinzuziehen` on its own, before any of this
        runs, which is a separate defect this cannot reach.
        """
        without = self.app.analyzer._without_zu
        self.assertEqual(without("hinzuziehen"), "")
        self.assertEqual(without("hinzuzufügen"), "hinzufügen")
        self.assertEqual(without("abzubrechen"), "abbrechen")
        self.assertEqual(without("zunehmen"), "")

    def test_a_prefix_is_not_glued_onto_a_verb_that_has_one(self) -> None:
        """The model sometimes returns a lemma that already carries its
        prefix, and the fold glued a second one on: `aufanfangen`,
        `anauffordern`, `anhinweisen` — 283 units that are not words.

        The test cannot be "starts with a prefix", which would refuse
        `mit` + `teilen`. It is "starts with a prefix and the rest is itself
        a verb".
        """
        prefixed = self.app.analyzer._already_prefixed
        for whole in ("auffordern", "anfangen", "hinweisen", "aufräumen"):
            with self.subTest(whole):
                self.assertTrue(prefixed(whole))
        for stem in ("teilen", "nehmen", "stehen", "fangen", "räumen"):
            with self.subTest(stem):
                self.assertFalse(prefixed(stem), "a plain stem was refused")

    def test_mitteilen_still_folds(self) -> None:
        """The case the naive guard would have broken."""
        self.assertIn("mitteilen", self.units("Ich teile dir das Ergebnis mit."))
