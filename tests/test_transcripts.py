"""Reading sentences out of written transcripts.

A subtitle is not a sentence — it is a cue of a second or two, cut wherever
the line filled up — which is why `alignment` exists. A transcript has the
same problem without the timings to solve it: the text is wrapped to a column
and a sentence runs across two or three lines. What it has instead is
punctuation, which subtitles largely lack.

The bilingual layout is the valuable one. German and English alternate line
for line, so the English travels with the German as its translation — a field
the reading page has always had and never been able to fill.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from corpus.sentence import TRANSCRIPT
from corpus.transcripts import TranscriptSource, language


class LanguageTest(unittest.TestCase):
    def test_it_tells_the_two_apart(self) -> None:
        self.assertEqual(language("Ich habe das nicht gesehen und das ist gut."), "de")
        self.assertEqual(language("I have not seen that and this is the one."), "en")

    def test_it_admits_when_it_cannot_say(self) -> None:
        """Names, numbers, interjections — nothing to count either way."""
        self.assertEqual(language("Berlin 1989"), "?")


class ReadTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def write(self, name: str, body: str) -> Path:
        path = self.root / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_wrapped_lines_become_one_sentence(self) -> None:
        """The wrap is a column width, not a sentence boundary."""
        got = TranscriptSource.read(self.write(
            "a.txt", "Ich habe das nicht\ngesehen und das ist gut.\n"))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].text, "Ich habe das nicht gesehen und das ist gut.")

    def test_punctuation_ends_a_sentence(self) -> None:
        got = TranscriptSource.read(self.write(
            "a.txt", "Das ist gut.\nUnd das ist nicht gut.\n"))
        self.assertEqual(len(got), 2)

    def test_a_bilingual_file_keeps_the_translation(self) -> None:
        body = ("Ich habe das nicht gesehen und das ist gut.\n"
                "I have not seen that and this is the one.\n") * 6
        got = TranscriptSource.read(self.write("b.txt", body))
        self.assertTrue(all(s.translation for s in got))
        self.assertNotIn("have", got[0].text)

    def test_a_single_language_file_has_none(self) -> None:
        body = "Ich habe das nicht gesehen und das ist gut.\n" * 6
        got = TranscriptSource.read(self.write("c.txt", body))
        self.assertTrue(all(s.translation is None for s in got))

    def test_the_layout_is_read_not_guessed_from_the_name(self) -> None:
        """Most bilingual files are unmarked and most single ones say
        `German only`, but not reliably enough to trust — a misread drops
        every second line or teaches English as German."""
        body = ("Ich habe das nicht gesehen und das ist gut.\n"
                "I have not seen that and this is the one.\n") * 6
        got = TranscriptSource.read(self.write("d - German only.txt", body))
        self.assertTrue(all(s.translation for s in got))

    def test_the_doubled_line_endings_are_handled(self) -> None:
        """These files carry `\\n\\r\\n` runs; splitting on `\\n` alone leaves
        every other line holding a lone carriage return."""
        got = TranscriptSource.read(self.write(
            "e.txt", "Das ist gut.\n\r\nUnd das ist nicht gut.\n"))
        self.assertEqual([s.text for s in got],
                         ["Das ist gut.", "Und das ist nicht gut."])

    def test_the_origin_says_where_it_came_from(self) -> None:
        got = TranscriptSource.read(self.write("f.txt", "Das ist gut.\n"))
        self.assertEqual(got[0].origin, TRANSCRIPT)

    def test_an_empty_file_is_not_an_error(self) -> None:
        self.assertEqual(TranscriptSource.read(self.write("g.txt", "\n\r\n\n")), [])


if __name__ == "__main__":
    unittest.main()
