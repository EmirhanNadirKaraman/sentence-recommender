"""A pronoun is only worth as much as what it points at.

`Und jetzt erwartet der von ihnen, dass sie ihm glauben.` is four pronouns
and nobody to hang them on: the sentence cannot be understood without the one
before it. `Warum hast du ihm nicht gesagt, dass Riton Albana ist?` has a
pronoun too and is perfectly clear.

Counting pronouns cannot tell those apart — 53.6% of the roadmap has one, and
German simply talks that way. What separates them is whether the sentence
carries its own antecedent, and German orthography nearly answers that for
free: nouns are capitalised.

Measured over the 3,902 beginner steps this charges 714 of them, and 689 of
those steps already had a pronoun-free candidate among their own examples.
"""
from __future__ import annotations

import unittest

from corpus.quality import score, unbound

STRANDED = "Und jetzt erwartet der von ihnen, dass sie ihm glauben."
NAMED = "Und jetzt erwartet Klaus von den Gästen, dass sie ihm glauben."


class UnboundPronounTest(unittest.TestCase):
    def test_a_stranded_pronoun_scores_below_a_named_one(self) -> None:
        """The comparison that decides a step: the same shape of sentence,
        one of them saying who it is about."""
        self.assertLess(score(STRANDED), score(NAMED))

    def test_a_pronoun_after_its_noun_is_free(self) -> None:
        """`Andes` is right there, so `er` costs nothing."""
        self.assertEqual(
            unbound("Weil Andes aus Indonesien kommt, mag er gerne scharf."), 0)

    def test_charged_once_for_each(self) -> None:
        """Two unresolved pronouns are worse than one, and the score says so."""
        one = "Sie hat gestern einen ganzen Kuchen alleine gegessen."
        self.assertEqual(unbound(one), 1)
        self.assertEqual(unbound(STRANDED), 4)
        self.assertLess(score(STRANDED), score(one))

    def test_first_and_second_person_are_not_pronouns_for_this(self) -> None:
        """`ich` and `du` are fixed by the act of speaking: a sentence with
        `ich` in it is about whoever said it, and needs no earlier line."""
        self.assertEqual(
            unbound("Ich habe gestern den ganzen Tag zu Hause gearbeitet."), 0)
        self.assertEqual(unbound("Warum hast du mir nicht früher geholfen?"), 0)

    def test_ihr_before_a_verb_is_you(self) -> None:
        """`Wie ihr wisst` is the second person plural, not a stranded `her`.
        This sentence was charged twice before the exemption and is entirely
        self-contained."""
        whole = "Wie ihr wisst, ist es schwierig, eine Sprache zu lernen."
        self.assertEqual(unbound(whole), 0)
        self.assertEqual(score(whole), score(whole.replace("ihr wisst",
                                                           "alle wissen")))

    def test_ihr_before_a_noun_is_the_possessive(self) -> None:
        self.assertEqual(unbound("Ihr Vater arbeitet seit Jahren in Hamburg."), 0)

    def test_es_holding_a_seat_is_not_a_reference(self) -> None:
        """`es` before a `dass` clause or a `zu`-infinitive points forward,
        inside the same sentence."""
        self.assertEqual(
            unbound("Es freut mich sehr, dass du gekommen bist."), 0)
        self.assertEqual(unbound("Es gibt hier keinen Kaffee mehr."), 0)

    def test_a_referring_es_is_still_charged(self) -> None:
        self.assertEqual(unbound("Es war wirklich viel zu teuer."), 1)

    def test_das_with_its_noun_behind_it_is_an_article(self) -> None:
        self.assertEqual(unbound("Das rote Auto steht seit Tagen hier."), 0)

    def test_das_standing_alone_is_a_pronoun(self) -> None:
        """`Nein, das habe ich nicht` needs whatever `das` was."""
        self.assertGreaterEqual(unbound("Das habe ich wirklich nicht gewusst."), 1)

    def test_an_empty_sentence_does_not_explode(self) -> None:
        self.assertEqual(unbound(""), 0)
        self.assertEqual(unbound("..."), 0)


if __name__ == "__main__":
    unittest.main()
