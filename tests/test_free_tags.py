"""What a reader gets for nothing, and why the article joined that list.

A name, a number and a stray bit of English cost a reader nothing: you need
not have learned "Dresden" to read a sentence containing it. The German
article is the same kind of thing and was not on the list, so `der` was a
word the roadmap had to teach — and until it did, the commonest unit in the
corpus stood in front of 80 b1 goals as their only blocker.

The pattern side had the rule too, written against `NE` alone rather than
against the set the word side reads. So widening the set was not enough on
its own: the collocation `der, die, das` matches a bare article, and until
both halves agreed it survived the word side dropping it.
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from corpus.analyzer import UnitAnalyzer
from db.word_repo import FREE_TAGS


@dataclass
class _Token:
    tag_: str


class _Doc(list):
    pass


def trustworthy(match_type: str, *tags: str, entry: str = "etw. (Akk) haben") -> bool:
    doc = _Doc(_Token(t) for t in tags)
    phrase = {"match_type": match_type, "indices": list(range(len(tags))),
              "dictionary_entry": entry}
    return UnitAnalyzer._trustworthy(phrase, doc)


class FreeTagsTest(unittest.TestCase):
    def test_the_article_is_free(self) -> None:
        self.assertIn("ART", FREE_TAGS)

    def test_names_and_numbers_are_still_free(self) -> None:
        self.assertLessEqual({"NE", "CARD", "FM", "XY"}, FREE_TAGS)


class PatternSideTest(unittest.TestCase):
    def test_a_match_entirely_on_articles_is_refused(self) -> None:
        """`der, die, das` matching a bare article is matching an article."""
        self.assertFalse(trustworthy("exact", "ART"))

    def test_a_match_entirely_on_names_is_still_refused(self) -> None:
        self.assertFalse(trustworthy("exact", "NE", "NE"))

    def test_an_article_beside_a_noun_is_kept(self) -> None:
        """`das Jahr` is a real collocation and must survive.

        This is the line between the two: the rule asks whether the match
        holds *nothing* but free tags, not whether it holds one.
        """
        self.assertTrue(trustworthy("exact", "ART", "NN"))

    def test_a_weak_fuzzy_match_is_still_refused(self) -> None:
        self.assertFalse(trustworthy("fuzzy (0.10)", "NN"))

    def test_an_article_noun_entry_needs_a_noun(self) -> None:
        """`meisten` is a pronoun whose lemma spells `Meister`; the fuzzy
        fallback matched it to `der Meister` at 1.00, 730 times."""
        self.assertFalse(trustworthy("fuzzy (1.00): der Meister", "PIS", entry="der Meister"))
        self.assertFalse(trustworthy("exact (with article)", "ADV", entry="das Mal"))
        self.assertTrue(trustworthy("exact (with article)", "ART", "NN", entry="das Jahr"))
        self.assertTrue(trustworthy("fuzzy (1.00): der Meister", "NN", entry="der Meister"))

    def test_a_verb_entry_asks_nothing_of_the_tags(self) -> None:
        self.assertTrue(trustworthy("exact", "VVFIN", entry="etw. (Akk) machen"))


if __name__ == "__main__":
    unittest.main()
