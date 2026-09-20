"""A separated prefix belongs to its verb — on the word side too.

The matcher has folded `svp` into the verb since the beginning: `Er steht
auf` yields the pattern `aufstehen`. The analyser's word side read the
tokens one at a time and yielded `stehen` and `auf` beside it, so under
strict counting `aufstehen` was blocked by `stehen`, `anfangen` by `fangen`,
and `einwilligen` by `willigen`, which is not a word. Measured over 5,000
subtitle sentences: 432 carry a separated prefix and 350 of the 379 the
parse attached came through as the bare stem.
"""
from __future__ import annotations

import unittest
from collections import Counter

from corpus.analyzer import Evidence, UnitAnalyzer

try:
    import spacy
    spacy.util.get_package_path("de_core_news_md")
    _PARSER = True
except Exception:                                    # noqa: BLE001 — optional model
    _PARSER = False


@unittest.skipUnless(_PARSER, "de_core_news_md is not installed")
class SeparatedPrefixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.analyzer = UnitAnalyzer(frozenset({"aufstehen"}))

    def lemmas(self, text: str) -> set[str]:
        doc = self.analyzer.matcher.nlp(text)
        units, _ = self.analyzer._units(doc, Evidence())
        return {u.key for u in units if u.kind == "lemma"}

    def test_the_prefix_folds_into_its_verb(self) -> None:
        found = self.lemmas("Er steht auf und geht.")
        self.assertIn("aufstehen", found)
        self.assertNotIn("stehen", found)
        self.assertNotIn("auf", found)

    def test_a_stem_that_is_not_a_word_never_becomes_a_unit(self) -> None:
        """The corpus's own sentence. Cut to `Der Krisenstab willigt ein.`
        the tagger reads `willigt` as an adjective and the fold, which trusts
        the tag like the rest of the analyser, leaves it alone."""
        found = self.lemmas("Der Krisenstab willigt ein und beginnt gleichzeitig "
                            "mit den Planungen.")
        self.assertIn("einwilligen", found)
        self.assertNotIn("willigen", found)

    def test_the_surface_shows_both_halves(self) -> None:
        doc = self.analyzer.matcher.nlp("Er steht auf und geht.")
        _, surfaces = self.analyzer._units(doc, Evidence())
        said = dict(surfaces)
        unit = next(u for u in said if u.key == "aufstehen")
        self.assertEqual(said[unit], "steht auf")

    def test_a_particle_on_a_non_verb_is_left_as_it_was(self) -> None:
        """The tagger calls `zusammen` a prefix here; nothing verbal owns it."""
        found = self.lemmas("Mehr als CDU und SPD zusammen.")
        self.assertIn("zusammen", found)

    def test_the_vote_still_sees_the_bare_stem(self) -> None:
        """`steht` must keep meaning `stehen` to the corpus vote, or the
        sentence-initial failures it repairs would start becoming `aufstehen`."""
        evidence = Evidence()
        doc = self.analyzer.matcher.nlp("Er steht auf und geht.")
        self.analyzer._units(doc, evidence)
        self.assertEqual(evidence.by_surface["steht"], Counter({"stehen": 1}))
        self.assertIn(("auf", "stehen"), evidence.prefixed)


class PrefixedCorrectionTest(unittest.TestCase):
    def test_a_repaired_stem_is_repaired_under_its_prefix(self) -> None:
        """`Kommst du mit?` opens on its verb and comes back `kommst`; the
        fold makes that `mitkommst`, and the remap has to reach it."""
        evidence = Evidence()
        evidence.prefixed = {("mit", "kommst"), ("an", "fangen")}
        fixed = UnitAnalyzer._prefixed_corrections(evidence, {"kommst": "kommen"})
        self.assertEqual(fixed, {"mitkommst": "mitkommen"})


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(_PARSER, "de_core_news_md is not installed")
class ConstructionConsumesItsVerbTest(unittest.TestCase):
    """`Es gibt ein Problem` is `es gibt` and nothing else.

    With the bare lemma left in, strict counting renamed `geben` back into
    the `geben` goal, and the sentence stayed a `geben` example after the
    pattern row had gone — the whole reason `es gibt` was split off.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.analyzer = UnitAnalyzer(frozenset({"es gibt", "jdm. (Dat) etw. (Akk) geben"}))

    def units(self, text: str) -> set[str]:
        doc = self.analyzer.matcher.nlp(text)
        found, _ = self.analyzer._units(doc, Evidence())
        return {str(u) for u in found}

    def test_there_is_carries_no_geben(self) -> None:
        found = self.units("Es gibt ein Problem.")
        self.assertIn("pattern:es gibt", found)
        self.assertNotIn("lemma:geben", found)
        self.assertNotIn("pattern:jdm. (Dat) etw. (Akk) geben", found)

    def test_the_expletive_leaves_no_stray_unit(self) -> None:
        """`es` is not the pronoun here, and `’s` split off `gibt’s` is
        not a word — neither may stand in front of the sentence."""
        found = self.units("Da gibt’s den Kanal.")
        self.assertIn("pattern:es gibt", found)
        self.assertNotIn("lemma:’s", found)
        self.assertNotIn("lemma:es", self.units("Es gibt ein Problem."))

    def test_giving_still_carries_geben(self) -> None:
        found = self.units("Ich gebe dir das Buch.")
        self.assertIn("lemma:geben", found)
        self.assertIn("pattern:jdm. (Dat) etw. (Akk) geben", found)
