"""Setting a word aside, and when it comes back.

The behaviour this replaced was a set on the viewer that nothing ever wrote
down, so the property worth pinning hardest is the dull one: that a snooze
survives the process. Everything else here is arithmetic on a counter, which
is easy to get subtly wrong and impossible to notice — a word that comes back
one decision late looks exactly like a word that comes back on time.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vocab.entry import Unit
from vocab.snooze_store import CAP, DELAY, SnoozeStore

HAUS = Unit.lemma("haus")
BAUM = Unit.lemma("baum")


class SnoozeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "state.sqlite3"
        self.store = SnoozeStore(self.path)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def decide(self, n: int) -> None:
        """`n` other words dealt with, whatever the verdict was."""
        for _ in range(n):
            self.store.advance()

    # --- the counter ------------------------------------------------------

    def test_it_comes_back_after_exactly_that_many_words(self) -> None:
        self.assertEqual(self.store.snooze(HAUS, delay=20), 20)

        self.decide(19)
        self.assertIn(HAUS, self.store.asleep())   # nineteen is not twenty

        self.decide(1)
        self.assertNotIn(HAUS, self.store.asleep())

    def test_snoozing_is_itself_a_decision(self) -> None:
        """Otherwise a run of skips would never bring the first one back."""
        before = self.store.tick()
        self.store.snooze(HAUS)
        self.assertEqual(self.store.tick(), before + 1)

    def test_the_clock_is_shared(self) -> None:
        """Any decision counts toward every word's return, not just its own."""
        self.store.snooze(HAUS, delay=3)
        self.store.snooze(BAUM, delay=3)          # this one also ticks
        self.decide(2)

        self.assertNotIn(HAUS, self.store.asleep())
        self.assertIn(BAUM, self.store.asleep())

    # --- repeats ----------------------------------------------------------

    def test_a_word_skipped_again_goes_further_back(self) -> None:
        self.assertEqual(self.store.snooze(HAUS, delay=20), 20)
        self.assertEqual(self.store.snooze(HAUS, delay=20), 40)
        self.assertEqual(self.store.snooze(HAUS, delay=20), 80)

    def test_escalation_stops_at_the_cap(self) -> None:
        """The cap is the whole reason this is not "lost for good".

        Doubling unchecked puts an eighth skip two and a half thousand
        decisions away, which no one reaches.
        """
        waits = [self.store.snooze(HAUS, delay=20, cap=200) for _ in range(8)]
        self.assertEqual(waits, [20, 40, 80, 160, 200, 200, 200, 200])
        self.assertLessEqual(max(waits), 200)

    def test_the_shipped_defaults_escalate_sanely(self) -> None:
        waits = [self.store.snooze(HAUS) for _ in range(6)]
        self.assertEqual(waits[0], DELAY)
        self.assertLessEqual(max(waits), CAP)

    # --- waking -----------------------------------------------------------

    def test_waking_it_forgets_that_it_was_avoided(self) -> None:
        """Undo is a retraction, so the next skip starts from the beginning."""
        self.store.snooze(HAUS)
        self.store.snooze(HAUS)                   # now on 40
        self.store.wake(HAUS)

        self.assertEqual(self.store.snooze(HAUS), DELAY)

    def test_waking_offers_it_again_at_once(self) -> None:
        self.store.snooze(HAUS)
        self.assertTrue(self.store.is_asleep(HAUS))
        self.store.wake(HAUS)
        self.assertFalse(self.store.is_asleep(HAUS))

    def test_expiring_naturally_keeps_the_count(self) -> None:
        """Serving its time is not the same as being retracted: a word you
        keep skipping should keep going further back."""
        self.store.snooze(HAUS, delay=2)
        self.decide(5)
        self.assertNotIn(HAUS, self.store.asleep())

        self.assertEqual(self.store.snooze(HAUS, delay=2), 4)

    # --- durability, which is the entire point ---------------------------

    def test_it_survives_the_process(self) -> None:
        self.store.snooze(HAUS, delay=20)
        self.decide(5)

        reopened = SnoozeStore(self.path)
        self.assertIn(HAUS, reopened.asleep())
        self.assertEqual(dict(reopened.pending())[HAUS], 15)

    # --- reading ----------------------------------------------------------

    def test_pending_counts_down_and_sorts_by_soonest(self) -> None:
        self.store.snooze(BAUM, delay=50)
        self.store.snooze(HAUS, delay=5)

        self.assertEqual([u for u, _ in self.store.pending()], [HAUS, BAUM])
        # Five, not four: a word's own snooze bumps the clock before its
        # deadline is set from it, so "in five words" means five *other*
        # decisions rather than four and its own.
        self.assertEqual(dict(self.store.pending())[HAUS], 5)
        self.assertEqual(dict(self.store.pending())[BAUM], 49)

    def test_nothing_is_asleep_to_begin_with(self) -> None:
        self.assertEqual(self.store.asleep(), frozenset())
        self.assertEqual(len(self.store), 0)
        self.assertEqual(self.store.pending(), [])


if __name__ == "__main__":
    unittest.main()
