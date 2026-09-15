"""The deck as an Anki package.

`deck.tsv` imports too, but leaves the media to be copied by hand. The point
of an `.apkg` is that it carries its audio, so it is one file to move onto a
phone — and the two things that silently go wrong are the order the cards
come out in and the meaning being repeated once per sentence.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from deck import Card, Example
from deck.anki import build, first_meaning, sentences_html


def card(position: int, word: str = "die Zeit", means=("die Zeit means time.",),
         sentences: int = 3) -> Card:
    return Card(position, word, True,
                tuple(Example(f"Satz {i}.", f"Sentence {i}.",
                              means[min(i - 1, len(means) - 1)])
                      for i in range(1, sentences + 1)),
                None, 3902)


class HtmlTest(unittest.TestCase):
    def test_a_sense_is_written_once(self) -> None:
        """Same rule as the page and the audio: the model gives every
        sentence in a group the same words, so equal strings mean the sense
        has not changed."""
        html = sentences_html(card(1))
        self.assertEqual(html.count("die Zeit means time."), 1)

    def test_a_shift_is_written_again(self) -> None:
        html = sentences_html(card(1, "die Bank",
                                   ("die Bank means bench.",
                                    "die Bank means bench.",
                                    "die Bank means the bank.")))
        self.assertEqual(html.count("means bench"), 1)
        self.assertEqual(html.count("means the bank"), 1)

    def test_every_sentence_and_translation_is_there(self) -> None:
        html = sentences_html(card(1))
        for i in (1, 2, 3):
            self.assertIn(f"Satz {i}.", html)
            self.assertIn(f"Sentence {i}.", html)

    def test_markup_in_a_sentence_is_escaped(self) -> None:
        """Corpus text is not HTML, and a stray angle bracket would eat the
        rest of the card."""
        one = Card(1, "x", False, (Example("a < b & c", "a < b", "x means y."),),
                   None, 1)
        self.assertIn("&lt;", sentences_html(one))
        self.assertNotIn("a < b", sentences_html(one))

    def test_the_meaning_is_the_first_one_there_is(self) -> None:
        one = Card(1, "x", False,
                   (Example("a", "b"), Example("c", "d", "x means y.")), None, 1)
        self.assertIn("x means y.", first_meaning(one))

    def test_a_card_with_no_meaning_yet_still_renders(self) -> None:
        one = Card(1, "x", False, (Example("a", "b"),), None, 1)
        self.assertEqual(first_meaning(one), "")


class PackageTest(unittest.TestCase):
    @staticmethod
    def _notes(path: Path):
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(path) as archive:
                archive.extractall(tmp)
            db = next(p for p in Path(tmp).iterdir()
                      if p.name.startswith("collection"))
            conn = sqlite3.connect(db)
            return conn.execute("SELECT sfld FROM notes ORDER BY sfld").fetchall()

    def test_it_splits_into_packages(self) -> None:
        """A gigabyte import looks hung on a phone."""
        cards = [card(i) for i in range(1, 8)]
        with tempfile.TemporaryDirectory() as tmp:
            written = build(cards, Path(tmp) / "none", Path(tmp) / "out",
                            "probe", per_package=3)
            self.assertEqual(len(written), 3)
            self.assertEqual([len(self._notes(p)) for p in written], [3, 3, 1])

    def test_the_order_is_the_teaching_order(self) -> None:
        """Anki's sort column has integer affinity, so a plain number sorts
        numerically — but a text sort there would list 1, 10, 100, 1000, 11
        and the deck would bear no relation to the plan."""
        cards = [card(i) for i in (1, 2, 9, 10, 11, 99, 100, 1000)]
        with tempfile.TemporaryDirectory() as tmp:
            written = build(cards, Path(tmp) / "none", Path(tmp) / "out",
                            "probe", per_package=100)
            order = [row[0] for row in self._notes(written[0])]
        self.assertEqual(order, sorted(order, key=int))
        self.assertEqual(order[:4], [1, 2, 9, 10])

    def test_a_card_without_audio_is_still_written(self) -> None:
        """Text-only is worth having; refusing the whole deck is not."""
        with tempfile.TemporaryDirectory() as tmp:
            written = build([card(1)], Path(tmp) / "none", Path(tmp) / "out",
                            "probe")
            self.assertEqual(len(self._notes(written[0])), 1)


if __name__ == "__main__":
    unittest.main()
