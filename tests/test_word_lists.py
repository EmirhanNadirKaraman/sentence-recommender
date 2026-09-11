"""Lists the reader builds, and the search that builds them.

Neither touches a database or a corpus: the store is given a temporary file
and the search a Counter, which is exactly what `unit_counts` returns.
"""
from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path

from vocab.goal_list import GoalList
from vocab.search import UnitSearch, trigrams
from vocab.word_lists import WordListStore


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.store = WordListStore(Path(self._dir.name) / "state.sqlite3")

    def test_order_survives(self) -> None:
        """A goal list's order is the only ranking it carries."""
        self.store.save("mine", ["der Hund", "die Katze", "das Pferd"])
        self.assertEqual(self.store.entries("mine"),
                         ("der Hund", "die Katze", "das Pferd"))

    def test_duplicates_keep_their_first_place(self) -> None:
        self.store.save("mine", ["b", "a", "b"])
        self.assertEqual(self.store.entries("mine"), ("b", "a"))

    def test_blank_entries_are_dropped(self) -> None:
        self.assertEqual(self.store.save("mine", ["a", "", "  ", "b"]), 2)

    def test_saving_replaces_rather_than_merges(self) -> None:
        """The page hands over the whole list, so a merge would make
        removing a word impossible."""
        self.store.save("mine", ["a", "b", "c"])
        self.store.save("mine", ["a", "c"])
        self.assertEqual(self.store.entries("mine"), ("a", "c"))

    def test_lists_do_not_bleed_into_each_other(self) -> None:
        self.store.save("one", ["a"])
        self.store.save("two", ["b"])
        self.assertEqual(self.store.entries("one"), ("a",))
        self.assertEqual(self.store.entries("two"), ("b",))

    def test_an_unknown_list_is_empty_not_an_error(self) -> None:
        self.assertEqual(self.store.entries("never"), ())
        self.assertNotIn("never", self.store)

    def test_names_counts_and_remembers(self) -> None:
        self.store.save("mine", ["a", "b"])
        [(name, count, saved)] = self.store.names()
        self.assertEqual((name, count), ("mine", 2))
        self.assertTrue(saved)

    def test_forgetting_takes_the_entries_with_it(self) -> None:
        self.store.save("mine", ["a"])
        self.store.forget("mine")
        self.assertEqual(self.store.entries("mine"), ())
        self.assertEqual(self.store.names(), [])


class GoalsFromAnywhereTest(unittest.TestCase):
    """`GoalList` reading a stored list instead of a file."""

    def test_handed_entries_are_used_verbatim(self) -> None:
        goals = GoalList(Path("data/never-read.txt"),
                         entries=("der Hund", "die Katze"))
        self.assertEqual(goals.entries(), ("der Hund", "die Katze"))

    def test_it_still_names_the_list(self) -> None:
        """`build-roadmap` puts the stem in the plan's label, so a stored
        list needs a name there like any other."""
        goals = GoalList(Path("data/mine.txt"), entries=("a",))
        self.assertEqual(goals._path.stem, "mine")

    def test_a_file_is_still_read_when_nothing_is_handed_over(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "goals.txt"
            path.write_text("haben\tetw. (Akk) haben\nwerden\n",
                            encoding="utf-8")
            self.assertEqual(GoalList(path).entries(),
                             ("etw. (Akk) haben", "werden"))

    def test_an_empty_list_is_not_a_missing_one(self) -> None:
        """`()` handed over means an empty list; None means read the file."""
        goals = GoalList(Path("data/nothing-here.txt"), entries=())
        self.assertEqual(goals.entries(), ())


class SearchTest(unittest.TestCase):
    def search(self) -> UnitSearch:
        return UnitSearch(Counter({
            ("lemma", "haus"): 500,
            ("pattern", "das Haus"): 300,
            ("lemma", "krankenhaus"): 40,
            ("lemma", "haut"): 90,
            ("lemma", "schriftlich"): 33,
            ("lemma", "arbeitslosigkeit"): 7,
        }))

    def keys(self, needle: str, **kw) -> list[str]:
        return [u.key for u, _, _ in self.search().find(needle, **kw)]

    def test_a_substring_wins_outright(self) -> None:
        """Jaccard alone ranks the exact word below shorter near-misses,
        because the padding dominates a short string."""
        self.assertEqual(self.keys("haus")[0], "haus")

    def test_the_commoner_word_breaks_a_tie(self) -> None:
        found = self.keys("haus")
        self.assertLess(found.index("das Haus"), found.index("krankenhaus"))

    def test_it_forgives_a_misspelling(self) -> None:
        self.assertIn("schriftlich", self.keys("shriftlich"))
        self.assertIn("arbeitslosigkeit", self.keys("arbeitslosikeit"))

    def test_nothing_alike_is_nothing(self) -> None:
        self.assertEqual(self.keys("zzzzzzz"), [])

    def test_an_empty_needle_is_not_everything(self) -> None:
        self.assertEqual(self.keys(""), [])
        self.assertEqual(self.keys("   "), [])

    def test_the_limit_holds(self) -> None:
        self.assertEqual(len(self.keys("haus", limit=2)), 2)

    def test_the_floor_excludes_the_merely_similar(self) -> None:
        loose = self.keys("hauz", floor=0.0)
        tight = self.keys("hauz", floor=0.9)
        self.assertGreater(len(loose), len(tight))

    def test_patterns_and_lemmas_both_come_back(self) -> None:
        kinds = {u.kind for u, _, _ in self.search().find("haus")}
        self.assertEqual(kinds, {"lemma", "pattern"})

    def test_trigrams_are_padded(self) -> None:
        """So a short word still yields enough to score, and the start of a
        word counts for more than its middle."""
        self.assertIn("  h", trigrams("haus"))
        self.assertIn("us ", trigrams("haus"))

    def test_case_and_spacing_do_not_matter(self) -> None:
        self.assertEqual(trigrams("  Haus "), trigrams("haus"))
