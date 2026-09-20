"""The deck as one text file, and back again.

The PDF and the slideshow are 11.5 MB of binary, and git keeps whole copies
of a binary rather than deltas — so committing a rebuild costs 11.5 MB
whether one card moved or three thousand did, and the diff says nothing a
person can read. The same deck as a sheet is a diff you can read, and the
renderers take cards and nothing else, so the sheet plus this repository
rebuilds both documents with no corpus, no Postgres and no model.

Which makes the round trip the thing that has to hold: whatever a card knows
has to survive being written down and read back, or the file is a lossy copy
of something only the database has.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deck import Card, Example
from deck.sheet import read_sheet, write_sheet

DECK = [
    Card(1, "die Zeit", True,
         (Example("Ich habe keine Zeit.", "I have no time.",
                  "die Zeit means time."),
          Example("Die Zeit vergeht schnell.", "Time passes quickly.",
                  "die Zeit means time."),
          Example("Wir hatten eine schöne Zeit.", "We had a lovely time.",
                  "die Zeit means time.")),
         None, 3),
    Card(2, "jdm. (Dat) passieren", True,
         (Example("Das ist mir passiert.", "That happened to me.", None),),
         "jetzt", 3),
    Card(3, "genau", False, (Example("Genau so ist es.",),), None, 3),
]


class RoundTripTest(unittest.TestCase):
    def _back(self, cards=DECK):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_sheet(cards, Path(tmp) / "deck.tsv")
            return read_sheet(path)

    def test_every_card_survives(self) -> None:
        self.assertEqual(len(self._back()), len(DECK))

    def test_the_word_and_its_position_survive(self) -> None:
        back = self._back()
        self.assertEqual([(c.position, c.word) for c in back],
                         [(c.position, c.word) for c in DECK])

    def test_the_spoken_form_is_read_not_recomputed(self) -> None:
        """Deriving it again would mean a sheet written today rendering
        differently tomorrow if the key-to-speech rule changed, which is the
        drift a tracked file exists to prevent."""
        card = Card(2, "jdm. (Dat) passieren", True,
                    (Example("Das ist mir passiert.", "That happened to me.", None),),
                    "jetzt", 3, spoken="jemandem passieren")   # how it was said then
        back = self._back([card])
        self.assertEqual(back[0].spoken, "jemandem passieren")
        self.assertNotEqual(back[0].spoken, Card(2, card.word, True, card.examples,
                                                 "jetzt", 3).spoken)

    def test_pattern_and_plain_words_are_told_apart(self) -> None:
        back = self._back()
        self.assertEqual([c.is_pattern for c in back], [True, True, False])

    def test_every_sentence_and_its_english_survive(self) -> None:
        back = self._back()
        self.assertEqual([e.text for e in back[0].examples],
                         [e.text for e in DECK[0].examples])
        self.assertEqual(back[0].examples[1].translation,
                         "Time passes quickly.")

    def test_a_meaning_survives_and_so_does_its_absence(self) -> None:
        """Absent has to come back absent, not as an empty string: the
        renderers print a meaning when there is one and a blank line when
        there is not."""
        back = self._back()
        self.assertEqual(back[0].examples[0].means, "die Zeit means time.")
        self.assertIsNone(back[1].examples[0].means)

    def test_a_relaxed_step_keeps_its_second_word(self) -> None:
        self.assertEqual(self._back()[1].beside, "jetzt")
        self.assertIsNone(self._back()[0].beside)

    def test_cards_with_fewer_than_three_examples_survive(self) -> None:
        back = self._back()
        self.assertEqual([len(c.examples) for c in back], [3, 1, 1])

    def test_a_tab_free_corpus_is_the_whole_assumption(self) -> None:
        """Tab-separated because the sentences are full of commas. A tab
        inside one would split a row and shift every column after it."""
        odd = [Card(1, "x", False,
                    (Example('Er sagte: "Ja, genau!" — und ging.',
                             "He said 'Yes, exactly!' — and left.",
                             "x means y."),), None, 1)]
        back = self._back(odd)
        self.assertEqual(back[0].examples[0].text,
                         'Er sagte: "Ja, genau!" — und ging.')

    def test_a_sentence_holding_a_newline_survives(self) -> None:
        """One does, in the real corpus. csv quotes it; a naive splitter
        would read it as two cards."""
        odd = [Card(1, "x", False,
                    (Example("Erste Zeile\nzweite Zeile.", "One\ntwo.", None),),
                    None, 1)]
        self.assertEqual(self._back(odd)[0].examples[0].text,
                         "Erste Zeile\nzweite Zeile.")


if __name__ == "__main__":
    unittest.main()
