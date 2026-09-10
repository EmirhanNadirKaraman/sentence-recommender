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
from unittest import mock

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


class AskingTest(unittest.TestCase):
    """`_ask`, which has to cope with there being nobody there.

    Started without a terminal — a pipe, a hook, an agent shelling out — the
    prompt used to raise EOFError and print a traceback over the first
    question. The quiz is a conversation; with no one to answer it should say
    so and keep what it already has.
    """

    def answers(self, *replies):
        it = iter(replies)

        def fake(_prompt=""):
            try:
                return next(it)
            except StopIteration:
                raise EOFError
        return mock.patch("builtins.input", fake)

    def test_an_answer_comes_back_lowered_and_stripped(self) -> None:
        with self.answers("  N  "):
            self.assertEqual(QuizCommand._ask(), "n")

    def test_enter_is_an_answer(self) -> None:
        with self.answers(""):
            self.assertEqual(QuizCommand._ask(), "")

    def test_a_typo_asks_again(self) -> None:
        with self.answers("k", "yes"):
            self.assertEqual(QuizCommand._ask(), "yes")

    def test_no_terminal_quits_instead_of_raising(self) -> None:
        with self.answers():
            self.assertEqual(QuizCommand._ask(), "q")

    def test_it_quits_rather_than_looping_on_a_closed_stdin(self) -> None:
        """A typo then EOF must not spin: the re-prompt reads from the same
        dead stream."""
        with self.answers("k"):
            self.assertEqual(QuizCommand._ask(), "q")


class RestoreTest(unittest.TestCase):
    """Putting back a line the quiz struck.

    The terminal never needed this: a wrong answer there is a deliberate
    keystroke. The web page is a thumb on a phone, and the write it causes is
    to a file under version control — so there has to be a way back that is
    not `git checkout`.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "known_words.txt"
        self.original = ("das Haus\n# struck by hand, long ago\n"
                         "der Baum  # 5x\nweil\n")
        self.path.write_text(self.original, encoding="utf-8")

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_a_strike_can_be_taken_back(self) -> None:
        QuizCommand._comment_out(self.path, ["der Baum  # 5x"])
        self.assertNotEqual(self.path.read_text(encoding="utf-8"), self.original)
        QuizCommand.restore(self.path, ["der Baum  # 5x"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.original)

    def test_it_says_how_many_it_put_back(self) -> None:
        QuizCommand._comment_out(self.path, ["das Haus", "weil"])
        self.assertEqual(QuizCommand.restore(self.path, ["das Haus", "weil"]), 2)

    def test_restoring_twice_changes_nothing(self) -> None:
        QuizCommand._comment_out(self.path, ["weil"])
        QuizCommand.restore(self.path, ["weil"])
        self.assertEqual(QuizCommand.restore(self.path, ["weil"]), 0)

    def test_a_line_struck_by_hand_is_left_alone(self) -> None:
        """It carries no marker, so it was not this that struck it."""
        QuizCommand.restore(self.path, ["struck by hand, long ago"])
        self.assertIn("# struck by hand, long ago",
                      self.path.read_text(encoding="utf-8"))


class PoolTest(unittest.TestCase):
    """What is left to ask — shared by the terminal and the web page, so the
    two cannot drift into asking different questions."""

    def setUp(self) -> None:
        self.grouped = {Unit.lemma("haus"): [entry("haus", Unit.lemma("haus"))],
                        Unit.lemma("baum"): [entry("baum", Unit.lemma("baum"))],
                        Unit.lemma("nie"): [entry("nie", Unit.lemma("nie"))]}
        self.counts = Counter({Unit.lemma("haus"): 100,
                               Unit.lemma("baum"): 5,
                               Unit.lemma("nie"): 0})

    def test_the_most_frequent_comes_first(self) -> None:
        _, pending = QuizCommand.pool(self.grouped, self.counts, frozenset(), 2)
        self.assertEqual(pending[0][0]["unit"], Unit.lemma("haus"))

    def test_a_word_the_corpus_never_says_is_not_asked(self) -> None:
        """Being wrong about it costs nothing, so it is not worth a question."""
        left, _ = QuizCommand.pool(self.grouped, self.counts, frozenset(), 9)
        self.assertNotIn(Unit.lemma("nie"), [g[0]["unit"] for g in left])

    def test_a_confirmed_word_drops_out(self) -> None:
        left, _ = QuizCommand.pool(self.grouped, self.counts,
                                   frozenset({Unit.lemma("haus")}), 9)
        self.assertEqual([g[0]["unit"] for g in left], [Unit.lemma("baum")])

    def test_the_limit_is_the_sitting_not_the_pool(self) -> None:
        left, pending = QuizCommand.pool(self.grouped, self.counts, frozenset(), 1)
        self.assertEqual((len(left), len(pending)), (2, 1))

    def test_a_word_the_known_set_does_not_hold_is_not_asked(self) -> None:
        """The premise of the question is that the word is being taken on
        trust. For 130 entries it was not: they key to a pattern unit, which
        the lemma resolvers never produce, so they were assumed known here and
        taught by the roadmap at the same time."""
        left, _ = QuizCommand.pool(self.grouped, self.counts, frozenset(), 9,
                                   known=frozenset({Unit.lemma("haus")}))
        self.assertEqual([g[0]["unit"] for g in left], [Unit.lemma("haus")])

    def test_no_known_set_means_no_filter(self) -> None:
        """The library default, so a caller without one still gets a pool."""
        left, _ = QuizCommand.pool(self.grouped, self.counts, frozenset(), 9)
        self.assertEqual(len(left), 2)

    def test_asking_for_more_than_there_is_is_not_an_error(self) -> None:
        _, pending = QuizCommand.pool(self.grouped, self.counts, frozenset(), 99)
        self.assertEqual(len(pending), 2)


if __name__ == "__main__":
    unittest.main()
