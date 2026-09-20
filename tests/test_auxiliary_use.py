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
