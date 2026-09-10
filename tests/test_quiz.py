"""One word, one question.

The quiz already grouped by unit, because the same word is often written in
both vocabulary files and being asked about `sein` twice is a good way to be
answered carelessly the second time. But the study list writes a verb with the
cases it governs — `etw./jdn. (Akk) haben` — while `function_words.txt` writes
`haben`, and those are two different units. So the reader was asked about the
same verb twice after all, and could answer it two different ways.

The trap is `das Essen`, which shares a lemma with `essen` the verb and is a
different word. The article is the only evidence available here without a
parser, so it is what the rule turns on.
"""
from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from commands.quiz import QuizCommand
from vocab.entry import Unit


def entry(surface: str, unit: Unit, line: str = "") -> dict:
    return {"path": None, "line": line or surface, "surface": surface,
            "unit": unit}


class MergeFramesTest(unittest.TestCase):
    def group(self, *entries: dict) -> dict[Unit, list[dict]]:
        grouped: dict[Unit, list[dict]] = {}
        for e in entries:
            grouped.setdefault(e["unit"], []).append(e)
        QuizCommand._merge_frames(grouped)
        return grouped

    def test_a_case_frame_folds_into_the_bare_verb(self) -> None:
        grouped = self.group(
            entry("haben", Unit.lemma("haben")),
            entry("etw./jdn. (Akk) haben", Unit.pattern("etw./jdn. (Akk) haben")))
        self.assertEqual(list(grouped), [Unit.lemma("haben")])
        self.assertEqual(len(grouped[Unit.lemma("haben")]), 2)

    def test_the_bare_verb_leads_the_group(self) -> None:
        """It is the more frequent of the two, so its count orders the
        question and its unit is what a confirmation records."""
        grouped = self.group(
            entry("haben", Unit.lemma("haben")),
            entry("etw./jdn. (Akk) haben", Unit.pattern("etw./jdn. (Akk) haben")))
        self.assertEqual(grouped[Unit.lemma("haben")][0]["surface"], "haben")

    def test_a_noun_is_not_a_verb(self) -> None:
        """`das Essen` shares its lemma with `essen` and is a different word."""
        grouped = self.group(
            entry("das Essen", Unit.lemma("essen")),
            entry("etw. (Akk) essen", Unit.pattern("etw. (Akk) essen")))
        self.assertIn(Unit.pattern("etw. (Akk) essen"), grouped)
        self.assertEqual(len(grouped[Unit.lemma("essen")]), 1)

    def test_a_pattern_without_a_case_frame_is_left_alone(self) -> None:
        """`der Anschluss` is a noun written with its article, not a frame."""
        grouped = self.group(
            entry("anschluss", Unit.lemma("anschluss")),
            entry("der Anschluss", Unit.pattern("der Anschluss")))
        self.assertEqual(len(grouped), 2)

    def test_a_frame_with_no_bare_verb_stays(self) -> None:
        grouped = self.group(
            entry("jdm. (Dat) etw. (Akk) erzählen",
                  Unit.pattern("jdm. (Dat) etw. (Akk) erzählen")))
        self.assertEqual(list(grouped), [Unit.pattern("jdm. (Dat) etw. (Akk) erzählen")])

    def test_the_dative_frame_folds_too(self) -> None:
        grouped = self.group(
            entry("helfen", Unit.lemma("helfen")),
            entry("jdm. (Dat) helfen", Unit.pattern("jdm. (Dat) helfen")))
        self.assertEqual(list(grouped), [Unit.lemma("helfen")])

    def test_nothing_to_merge_changes_nothing(self) -> None:
        grouped = self.group(entry("haus", Unit.lemma("haus")),
                             entry("baum", Unit.lemma("baum")))
        self.assertEqual(len(grouped), 2)


class SourceTest(unittest.TestCase):
    """`--from`, which points the quiz at one vocabulary file.

    The two hold different kinds of claim. `function_words.txt` is generated
    and closed-class, so nearly every answer is yes; `known_words.txt` is a
    published wordlist never checked against this reader. Auditing them
    together tells you less than auditing either alone.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        root = Path(self._dir.name)
        self.known = root / "known_words.txt"
        self.function = root / "function_words.txt"
        self.known.write_text("das Haus\n# der Baum\n", encoding="utf-8")
        self.function.write_text("der\nweil\n", encoding="utf-8")
        self.app = SimpleNamespace(settings=SimpleNamespace(
            known_words=self.known, function_words=self.function))

    def tearDown(self) -> None:
        self._dir.cleanup()

    def surfaces(self, files: str) -> set[str]:
        return {e["surface"] for e in
                QuizCommand()._entries(self.app, Counter(), files)}

    def test_both_is_the_default(self) -> None:
        self.assertEqual(self.surfaces("both"), {"das Haus", "der", "weil"})

    def test_known_only(self) -> None:
        self.assertEqual(self.surfaces("known"), {"das Haus"})

    def test_function_only(self) -> None:
        self.assertEqual(self.surfaces("function"), {"der", "weil"})

    def test_an_unknown_name_falls_back_to_both(self) -> None:
        """argparse already refuses one; this is the library door."""
        self.assertEqual(self.surfaces("nonsense"), {"das Haus", "der", "weil"})

    def test_struck_lines_are_never_asked(self) -> None:
        self.assertNotIn("der Baum", self.surfaces("known"))

    def test_a_missing_file_is_not_an_error(self) -> None:
        self.function.unlink()
        self.assertEqual(self.surfaces("function"), set())


if __name__ == "__main__":
    unittest.main()
