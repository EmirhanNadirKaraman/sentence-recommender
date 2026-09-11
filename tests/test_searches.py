"""The rota over goals worth looking for.

`gather` walks the stranded words in priority order and stops as soon as it
has enough candidates, so the few at the top were searched every round and
the rest never at all — ten rounds, the same six terms, 55 words untried.

The property that matters here is that it is a rota and not a blacklist. A
word can stop being unfindable; that is the whole premise of hunting. So
stepping aside has to be temporary, and the slate has to wipe itself once
everyone has had a turn.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ingest.searches import SearchLog
from vocab.entry import Unit


def u(key: str) -> Unit:
    return Unit("lemma", key)


class RotaTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.log = SearchLog(Path(self._dir.name) / "state.sqlite3")
        self.stuck = [(u("a"), 9), (u("b"), 5), (u("c"), 1)]

    def try_it(self, key: str, times: int = 1) -> None:
        for _ in range(times):
            self.log.record([u(key)])

    def keys(self, rows) -> list[str]:
        return [unit.key for unit, _ in rows]

    def test_nothing_tried_means_everything_is_offered(self) -> None:
        turn, waiting = self.log.rota(self.stuck)
        self.assertEqual(self.keys(turn), ["a", "b", "c"])
        self.assertEqual(waiting, 0)

    def test_one_fruitless_turn_is_not_enough_to_step_aside(self) -> None:
        """Two, so a single unlucky round does not sideline a good word."""
        self.try_it("a")
        self.assertEqual(self.keys(self.log.rota(self.stuck)[0]),
                         ["a", "b", "c"])

    def test_a_tried_word_steps_aside(self) -> None:
        self.try_it("a", 2)
        turn, waiting = self.log.rota(self.stuck)
        self.assertEqual(self.keys(turn), ["b", "c"])
        self.assertEqual(waiting, 1)

    def test_the_order_of_the_rest_is_kept(self) -> None:
        """Priority still decides who goes first among those left."""
        self.try_it("b", 2)
        self.assertEqual(self.keys(self.log.rota(self.stuck)[0]), ["a", "c"])

    def test_when_everyone_has_had_a_turn_the_slate_wipes(self) -> None:
        """A rota, not a blacklist — a word can stop being unfindable."""
        for key in ("a", "b", "c"):
            self.try_it(key, 2)
        turn, waiting = self.log.rota(self.stuck)
        self.assertEqual(self.keys(turn), ["a", "b", "c"])
        self.assertEqual(waiting, 0)
        self.assertEqual(self.log.tried(), {})

    def test_a_wipe_really_clears_the_counts(self) -> None:
        for key in ("a", "b", "c"):
            self.try_it(key, 2)
        self.log.rota(self.stuck)
        self.try_it("a", 2)
        self.assertEqual(self.keys(self.log.rota(self.stuck)[0]), ["b", "c"])

    def test_counts_accumulate_across_runs(self) -> None:
        self.try_it("a")
        self.try_it("a")
        self.assertEqual(self.log.tried()[u("a")], 2)

    def test_forgetting_one_word_leaves_the_others(self) -> None:
        self.try_it("a", 2)
        self.try_it("b", 2)
        self.log.forget([u("a")])
        self.assertEqual(sorted(k.key for k in self.log.tried()), ["b"])

    def test_recording_nothing_is_harmless(self) -> None:
        self.log.record([])
        self.assertEqual(self.log.tried(), {})

    def test_an_empty_stuck_list_wipes_rather_than_hangs(self) -> None:
        turn, waiting = self.log.rota([])
        self.assertEqual((turn, waiting), ([], 0))
