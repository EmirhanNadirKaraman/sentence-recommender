"""One goal per word.

The study list writes `nennen` and it also writes `jdn. (Akk) + Name (Akk)
nennen`. Both became goals, and they are one German word — so every sentence
saying it carried two unknown units and could never be i+1 for either. 263
sentences for that verb alone, "So nennt man das Fastenbrechen" among them,
one word away from readable and unreachable for ever.

`covered_forms` cannot reach this: `_drop_duplicates` keeps anything that is
`in goals`, and the bare verb is itself a goal.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vocab.entry import Unit
from vocab.goal_list import GoalList


class OneGoalPerVerbTest(unittest.TestCase):
    def keep(self, *units: Unit) -> set[Unit]:
        return set(GoalList._one_goal_per_verb(units))

    def test_the_frame_swallows_the_bare_verb(self) -> None:
        frame = Unit.pattern("jdn. (Akk) + Name (Akk) nennen")
        self.assertEqual(self.keep(frame, Unit.lemma("nennen")), {frame})

    def test_the_frame_is_the_one_that_survives(self) -> None:
        """It teaches the verb and the cases it governs; the lemma teaches
        only the verb."""
        frame = Unit.pattern("jdm. (Dat) helfen")
        self.assertIn(frame, self.keep(Unit.lemma("helfen"), frame))

    def test_an_article_noun_is_not_a_frame(self) -> None:
        """`das Russisch` would otherwise eat the adjective `russisch`, and
        `der Morgen` the adverb `morgen`."""
        for entry, word in (("das Russisch", "russisch"),
                            ("der Morgen", "morgen"),
                            ("der Halt", "halt")):
            kept = self.keep(Unit.pattern(entry), Unit.lemma(word))
            self.assertIn(Unit.lemma(word), kept, entry)

    def test_a_noun_keeps_its_place_against_a_verb_frame(self) -> None:
        """A capitalised key is a noun that shares a lemma with a verb — a
        different word, whatever the frame governs."""
        kept = self.keep(Unit.pattern("etw. (Akk) essen"), Unit("lemma", "Essen"))
        self.assertIn(Unit("lemma", "Essen"), kept)

    def test_a_bare_verb_with_no_frame_is_untouched(self) -> None:
        self.assertEqual(self.keep(Unit.lemma("gehen")), {Unit.lemma("gehen")})

    def test_a_frame_with_no_bare_verb_is_untouched(self) -> None:
        frame = Unit.pattern("jdm. (Dat) etw. (Akk) erzählen")
        self.assertEqual(self.keep(frame), {frame})

    def test_order_is_kept(self) -> None:
        """The list is written most-useful-first and that is its only
        ranking."""
        a, b = Unit.pattern("etw. (Akk) sehen"), Unit.lemma("baum")
        self.assertEqual(GoalList._one_goal_per_verb((a, b)), (a, b))


class EntriesTest(unittest.TestCase):
    """Two shapes of word list, and the one that used to read as empty.

    `build-study-list` writes two tab-separated columns and the blueprint is
    column two, because that is the string the matcher and `phrase_table`
    speak. A list copied out of a syllabus is one column — and taking column
    two of that yielded nothing at all, silently, since a file of the wrong
    shape and a file with no goals look identical from here.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "list.txt"

    def tearDown(self) -> None:
        self._dir.cleanup()

    def entries(self, body: str) -> tuple[str, ...]:
        self.path.write_text(body, encoding="utf-8")
        return GoalList(self.path).entries()

    def test_two_columns_take_the_blueprint(self) -> None:
        self.assertEqual(self.entries("haben\tetw./jdn. (Akk) haben\n"),
                         ("etw./jdn. (Akk) haben",))

    def test_one_column_takes_the_word(self) -> None:
        self.assertEqual(self.entries("die Abbildung\nder Abend\n"),
                         ("die Abbildung", "der Abend"))

    def test_order_is_kept(self) -> None:
        """These files are written most-useful-first and that is the only
        ranking a goal list carries."""
        self.assertEqual(self.entries("zebra\nabend\nhaus\n"),
                         ("zebra", "abend", "haus"))

    def test_repeats_collapse(self) -> None:
        self.assertEqual(self.entries("haus\nhaus\n"), ("haus",))

    def test_comments_and_blanks_are_skipped(self) -> None:
        self.assertEqual(self.entries("# a note\n\nhaus\n"), ("haus",))

    def test_a_missing_file_is_not_a_crash(self) -> None:
        self.assertEqual(GoalList(self.path.parent / "nope.txt").entries(), ())


if __name__ == "__main__":
    unittest.main()
