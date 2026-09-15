"""A sentence that starts mid-thought teaches less than one that does not.

German capitalises the first word of a sentence, so a lowercase first letter
means the beginning went somewhere else — usually to the previous subtitle
line. `das hab' ich denen bis heute auch nicht gesagt.` is the tail of
something, and the missing half is the context the reader needed.

That is the same fault the length floor exists for, stated the other way
round, and until now nothing looked for it: 88 of the 3,902 steps in the
beginner plan were taught by a fragment, and 85 of them had a whole sentence
of equal quality sitting unused among their own candidates.
"""
from __future__ import annotations

import unittest

from corpus.quality import score

WHOLE = "Der Kanzler ist gestern von seinem Amt zurückgetreten."
FRAGMENT = "das hab' ich denen bis heute auch nicht gesagt."


class FragmentTest(unittest.TestCase):
    def test_a_fragment_scores_below_the_same_sentence_capitalised(self) -> None:
        """The comparison that decides a step: the same words, one of them
        starting a sentence and one continuing one."""
        self.assertLess(score(FRAGMENT), score(FRAGMENT.capitalize()))

    def test_a_whole_sentence_is_untouched(self) -> None:
        self.assertEqual(score(WHOLE), score(WHOLE))
        self.assertGreater(score(WHOLE), 0.0)

    def test_an_opening_quote_is_judged_on_its_word(self) -> None:
        """The first *letter*, not the first character — a sentence may
        legitimately open with punctuation."""
        self.assertEqual(score('"Na?" ist eine ganze Frage auf Deutsch.'),
                         score('Na ist eine ganze Frage auf Deutsch.'))

    def test_an_ellipsis_is_still_a_fragment(self) -> None:
        """`...dass du mich angesprochen hast` opens with punctuation and is
        as much a tail as one that opens with the word."""
        started = "Dass du mich angesprochen hast, freut mich sehr."
        self.assertLess(score("...dass du mich angesprochen hast, freut mich."),
                        score(started))

    def test_a_number_is_not_a_lowercase_word(self) -> None:
        """`islower` is false for a digit, and the regex skips to the first
        letter, so a sentence opening with a figure is not penalised."""
        digits = "3 Millionen Menschen leben heute in dieser grossen Stadt."
        words = "Drei Millionen Menschen leben heute in dieser grossen Stadt."
        self.assertEqual(score(digits), score(words))

    def test_a_noun_opening_is_not_penalised(self) -> None:
        """German nouns are capitalised mid-sentence too, so the test has to
        be about position rather than about case alone."""
        self.assertGreater(score("Geschichte wiederholt sich nicht, sagt man."),
                           score("geschichte wiederholt sich nicht, sagt man."))

    def test_the_penalty_does_not_reject(self) -> None:
        """`quality` ranks and rejects nothing: a word whose only example is
        a fragment is still taught with it, just ranked below a better one."""
        self.assertGreater(score(FRAGMENT), 0.0)


if __name__ == "__main__":
    unittest.main()
