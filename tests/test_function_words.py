"""Regenerating the closed-class file without losing the review of it.

`write` overwrote blindly. Every `#` in that file is the reader saying they do
not know a word — twenty-four by hand, plus every "no" the quiz records there
— and `python main.py function-words` threw all of it away without a word.
Nothing failed, nothing warned; the judgements were simply gone and the words
were assumed known again.

The list is derived and can be rebuilt at any time. The review of it cannot.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from db.word_repo import FunctionWord
from vocab.function_words import FunctionWordFile


def word(lemma: str, category: str = "Indefinitpronomen", n: int = 5) -> FunctionWord:
    return FunctionWord(lemma=lemma, category=category, frequency=n,
                        examples=(lemma,))


class PreservingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "function_words.txt"
        self.file = FunctionWordFile()
        self.words = [word("der"), word("aufn"), word("wovon")]

    def tearDown(self) -> None:
        self._dir.cleanup()

    def live(self) -> set[str]:
        return {m.group(1) for m in map(
            FunctionWordFile.LIVE.match,
            self.path.read_text(encoding="utf-8").splitlines()) if m}

    def strike(self, lemma: str) -> None:
        """What a reader does by hand, and what the quiz does on a "no"."""
        text = self.path.read_text(encoding="utf-8").splitlines()
        self.path.write_text("\n".join(
            f"# {line}" if FunctionWordFile.LIVE.match(line)
            and FunctionWordFile.LIVE.match(line).group(1) == lemma else line
            for line in text) + "\n", encoding="utf-8")

    def test_a_strike_survives_regeneration(self) -> None:
        self.file.write(self.path, self.words)
        self.strike("aufn")
        self.assertEqual(FunctionWordFile.struck(self.path), {"aufn"})
        self.file.write(self.path, self.words)          # regenerate
        self.assertEqual(FunctionWordFile.struck(self.path), {"aufn"})

    def test_the_others_stay_live(self) -> None:
        self.file.write(self.path, self.words)
        self.strike("aufn")
        self.file.write(self.path, self.words)
        self.assertEqual(self.live(), {"der", "wovon"})

    def test_a_first_write_has_nothing_to_keep(self) -> None:
        self.assertEqual(FunctionWordFile.struck(self.path), set())
        self.file.write(self.path, self.words)
        self.assertEqual(self.live(), {"der", "aufn", "wovon"})

    def test_the_header_is_not_read_as_words(self) -> None:
        """It is entirely `#` lines, and none of them is a struck lemma."""
        self.file.write(self.path, self.words)
        self.assertEqual(FunctionWordFile.struck(self.path), set())

    def test_a_word_that_left_the_corpus_is_not_resurrected(self) -> None:
        """Struck, then gone from the source: it should simply not appear."""
        self.file.write(self.path, self.words)
        self.strike("aufn")
        self.file.write(self.path, [word("der"), word("wovon")])
        self.assertEqual(self.live(), {"der", "wovon"})
        self.assertNotIn("aufn", self.path.read_text(encoding="utf-8"))

    def test_it_still_reports_how_many_it_wrote(self) -> None:
        self.assertEqual(self.file.write(self.path, self.words), 3)


if __name__ == "__main__":
    unittest.main()
