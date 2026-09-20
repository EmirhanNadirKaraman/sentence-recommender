"""An auxiliary is not the verb the dictionary describes.

`Ich habe nicht bestanden` was credited with `etw./jdn. (Akk) haben`, and
`Ich kann jetzt machen, was ich möchte` with `etw. (Akk) können` — the
verb's blueprint handed to every use of the verb, auxiliary or not. The
guard meant to stop it, `dep_ != "aux"`, never fired: the German parse puts
the auxiliary at the head and the participle or infinitive under it as
`oc`. Those two patterns were the most frequent in the corpus, and most of
their sentences did not carry them.

These run the real parser, because the bug was about what the parse looks
like and a fake token would only pin what the test author believed.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

try:
    import spacy
    spacy.util.get_package_path("de_core_news_md")
    _PARSER = True
except Exception:                                    # noqa: BLE001 — optional model
    _PARSER = False

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "matcher"))


@unittest.skipUnless(_PARSER, "de_core_news_md is not installed")
class AuxiliaryUseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import phrase_finder                              # noqa: PLC0415 — loads spaCy
        cls.finder = phrase_finder

    def entries(self, text: str) -> set[str]:
        doc = self.finder.nlp(text)
        return {p["dictionary_entry"] for p in self.finder.extract_german_logic(doc)}

    def test_the_perfect_tense_is_not_haben(self) -> None:
        self.assertNotIn("etw./jdn. (Akk) haben", self.entries("Ich habe nicht bestanden."))

    def test_a_modal_in_front_of_a_verb_is_not_koennen(self) -> None:
        self.assertNotIn("etw. (Akk) können",
                         self.entries("Den Restbetrag können sie später zahlen."))

    def test_the_carried_verb_still_gets_its_own_pattern(self) -> None:
        """Skipping the auxiliary must not lose the verb it carries."""
        found = self.entries("Ich habe die Prüfung bestanden.")
        self.assertIn("aus etw. / etw. (Akk) bestehen bestehen", found)
        self.assertNotIn("etw./jdn. (Akk) haben", found)

    def test_haben_with_an_object_is_still_haben(self) -> None:
        self.assertIn("etw./jdn. (Akk) haben", self.entries("Ich habe einen Gast."))

    def test_a_modal_with_an_object_and_no_verb_is_still_koennen(self) -> None:
        self.assertIn("etw. (Akk) können", self.entries("Ich kann Deutsch."))

    def test_the_copula_is_still_sein(self) -> None:
        """`pd`, not `oc`: the predicate is not a verb being carried."""
        self.assertIn("sein", self.entries("Das ist gut."))

    def test_a_full_verb_carrying_a_clause_keeps_its_pattern(self) -> None:
        """`glauben` takes a clause; that is what `glauben` does."""
        self.assertIn("jdm. (Dat) / etw. (Akk) glauben",
                      self.entries("Ich glaube, ich habe nicht bestanden."))


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(_PARSER, "de_core_news_md is not installed")
class ExpletiveTest(unittest.TestCase):
    """`es gibt` is not `jdm. (Dat) etw. (Akk) geben`.

    Five sentences in six that said `gibt` were *there is*, and every one
    was credited with *give someone something*. The parse marks the
    expletive `es` as `ep`, and the construction is its own canonical.
    """

    GIVE = "jdm. (Dat) etw. (Akk) geben"

    @classmethod
    def setUpClass(cls) -> None:
        import phrase_finder                              # noqa: PLC0415 — loads spaCy
        cls.finder = phrase_finder

    def phrases(self, text: str) -> dict[str, list[str]]:
        doc = self.finder.nlp(text)
        return {p["dictionary_entry"]: p["sentence_phrase"]
                for p in self.finder.extract_german_logic(doc)}

    def test_there_is_becomes_its_own_unit(self) -> None:
        found = self.phrases("Es gibt ein Problem.")
        self.assertIn("es gibt", found)
        self.assertNotIn(self.GIVE, found)

    def test_the_expletive_is_part_of_the_phrase(self) -> None:
        """The `es` is what makes it the construction, so it belongs to it."""
        self.assertIn("Es", self.phrases("Es gibt ein Problem.")["es gibt"])

    def test_the_question_form_is_the_same_construction(self) -> None:
        self.assertIn("es gibt", self.phrases("Was gibt es zum Essen?"))

    def test_under_a_modal_or_auxiliary_the_es_is_the_carrier_s(self) -> None:
        """`Es wird immer Probleme geben` — the miss the sixty-sentence read
        found: the verb sits under `wird` and `es` is the subject of `wird`."""
        self.assertIn("es gibt", self.phrases("Es wird immer Probleme geben."))
        self.assertIn("es gibt", self.phrases("Es kann Ausnahmen geben."))

    def test_the_clitic_is_the_construction(self) -> None:
        """`gibt's` stays one token with a nonsense lemma; `gibt’s` splits
        and was credited with *give*. Both are `es gibt`."""
        for text in ("Da gibt's auch Probleme.", "Da gibt’s den Kanal.",
                     "Für alle gibts auch ne gute Nachricht."):
            found = self.phrases(text)
            self.assertIn("es gibt", found, text)
            self.assertNotIn(self.GIVE, found, text)

    def test_giving_it_is_still_giving(self) -> None:
        """`es` as the accusative object is the thing given, not the expletive."""
        found = self.phrases("Sie gibt es ihm.")
        self.assertNotIn("es gibt", found)
        self.assertIn(self.GIVE, found)

    def test_giving_someone_something_is_untouched(self) -> None:
        found = self.phrases("Ich gebe dir das Buch.")
        self.assertIn(self.GIVE, found)
        self.assertNotIn("es gibt", found)
