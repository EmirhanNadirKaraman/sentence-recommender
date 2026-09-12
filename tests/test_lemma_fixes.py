"""Lemmas the parser invented, corrected by the lemma they came out as.

The parser is an edit-tree model: it predicts a transformation, applies it,
and never checks that the result is a word. "Teilchen" and "Teilchens" both
came back as "teilche", which is not German, and the blocked page duly showed
`das Teilchen` — said fourteen times — as needing "1 other new word here:
teilche". The goal was blocked by a misspelling of itself.

Keyed on the observed *lemma* rather than the surface, which is the whole
safety argument. `data/lemma_overrides.txt` is surface-keyed and verb-only,
and has to be: widening it would apply "muss -> müssen" to the noun in "ein
Muss". A line here fires only once the analyser has already produced one
particular non-word, so it cannot take a reading away from a word that has
one.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from corpus.analyzer import UnitAnalyzer
from fingerprint import SOURCES

FIXES = Path(__file__).resolve().parents[1] / "data" / "lemma_fixes.txt"


class ReadingTest(unittest.TestCase):
    def test_the_file_is_read(self) -> None:
        self.assertEqual(UnitAnalyzer._read_fixes().get("teilche"), "teilchen")

    def test_comments_and_blank_lines_are_ignored(self) -> None:
        """The file is mostly commentary explaining what not to put in it."""
        fixes = UnitAnalyzer._read_fixes()
        self.assertTrue(all(k and v for k, v in fixes.items()))
        self.assertNotIn("#", "".join(fixes))

    def test_every_entry_is_lowercase(self) -> None:
        """Lemmas are compared lowercased everywhere else, so an entry with a
        capital would simply never fire."""
        for observed, corrected in UnitAnalyzer._read_fixes().items():
            self.assertEqual(observed, observed.lower())
            self.assertEqual(corrected, corrected.lower())

    def test_nothing_maps_to_itself(self) -> None:
        """A no-op line is a mistake worth catching: it says a correction was
        intended and none was made."""
        for observed, corrected in UnitAnalyzer._read_fixes().items():
            self.assertNotEqual(observed, corrected)


class ContractTest(unittest.TestCase):
    def test_the_file_is_fingerprinted(self) -> None:
        """It decides what units a sentence yields, so a cached corpus built
        before an entry was added has to be reported stale. Without this the
        correction would apply to new analysis only, and the halves of the
        corpus would disagree with nothing to say so."""
        self.assertIn(FIXES.resolve(), [p.resolve() for p in SOURCES])

    def test_the_ambiguous_cases_are_not_in_it(self) -> None:
        """`gewiss`, `lokale` and `innerer` are real German words, and which
        reading is meant is context rather than spelling. Correcting them
        would be wrong wherever the other reading was intended, so the file
        documents them as deliberately absent -- this keeps it that way."""
        fixes = UnitAnalyzer._read_fixes()
        for word in ("gewiß", "gewiss", "lokale", "innerer", "dolmetscherin"):
            self.assertNotIn(word, fixes)


if __name__ == "__main__":
    unittest.main()
