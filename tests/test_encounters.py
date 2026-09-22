"""Hearing a word climbs a ladder of spaced days; the top calls the test.

Every heard line is logged as it is. The word's heard level is another
thing: rung one at the first hearing, and each rung after that only once
the ladder's days have passed since the hearing that was counted -- ten
hearings in one evening are rung one, five over a month are the top.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from srs.card import Card
from srs.scheduler import BY_DATE, BY_HEARING, due_now
from vocab.encounters import ENOUGH, LADDER, Encounters, Rung
from vocab.entry import Unit

DAY0 = datetime(2026, 9, 22, 20, 0)
ALSO = Unit.lemma("also")


def heard(store: Encounters, unit: Unit, days: float, text: str = "Also gut.") -> None:
    store.add([(unit, text, "vid", 12.0)], DAY0 + timedelta(days=days))


class LadderTest(unittest.TestCase):
    def test_the_rungs_come_on_days_0_1_4_11_and_25_at_the_earliest(self) -> None:
        self.assertEqual(LADDER, (0, 1, 3, 7, 14))
        with tempfile.TemporaryDirectory() as tmp:
            store = Encounters(Path(tmp) / "state.sqlite3")
            self.assertEqual(store.rung(ALSO), Rung())
            # An evening of hearings is one rung.
            for days in (0, 0, 0.01, 0.5, 0.99):
                heard(store, ALSO, days)
            self.assertEqual(store.rung(ALSO), Rung(1, DAY0))
            self.assertEqual(store.rung(ALSO).next_from, DAY0 + timedelta(days=1))
            # The days are counted from the hearing that was counted, not
            # the last one: 0.99 did not move the clock.
            heard(store, ALSO, 1)
            self.assertEqual(store.rung(ALSO), Rung(2, DAY0 + timedelta(days=1)))
            heard(store, ALSO, 3.5)
            self.assertEqual(store.rung(ALSO).level, 2)
            heard(store, ALSO, 4)
            self.assertEqual(store.rung(ALSO), Rung(3, DAY0 + timedelta(days=4)))
            heard(store, ALSO, 10)
            heard(store, ALSO, 11)
            self.assertEqual(store.rung(ALSO).level, 4)
            heard(store, ALSO, 24)
            self.assertEqual(store.rung(ALSO).level, 4)
            heard(store, ALSO, 25)
            top = store.rung(ALSO)
            self.assertEqual((top.level, top.familiar, top.next_from),
                             (ENOUGH, True, None))
            # The top is the top: a year of hearings changes nothing.
            heard(store, ALSO, 400)
            self.assertEqual(store.rung(ALSO), Rung(ENOUGH, DAY0 + timedelta(days=25)))
            # Every hearing was logged all the same.
            self.assertEqual(store.count(ALSO), 13)
            self.assertEqual(store.rungs(), {ALSO: store.rung(ALSO)})

    def test_a_batch_counts_each_word_once_and_logs_every_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Encounters(Path(tmp) / "state.sqlite3")
            gut = Unit.lemma("gut")
            store.add([(ALSO, "Also gut.", "vid", 12.0), (gut, "Also gut.", "vid", 12.0),
                       (ALSO, "Also, los.", "vid", 40.0)], DAY0)
            self.assertEqual({u: r.level for u, r in store.rungs().items()}, {ALSO: 1, gut: 1})
            self.assertEqual(store.count(ALSO), 2)
            self.assertEqual([(l["text"], l["times"]) for l in store.lines(ALSO)],
                             [("Also, los.", 1), ("Also gut.", 1)])


class CalledTest(unittest.TestCase):
    def card(self, key: str, due_in: float, last_review: datetime | None = None) -> Card:
        return Card(Unit.lemma(key), DAY0 + timedelta(days=due_in), 1.0, 2.5, 0, last_review)

    def test_the_top_of_the_ladder_calls_the_test_once_per_review(self) -> None:
        now = DAY0 + timedelta(days=30)
        overdue = self.card("gut", due_in=29)
        familiar = self.card("also", due_in=40, last_review=DAY0 + timedelta(days=20))
        climbing = self.card("sogar", due_in=40, last_review=DAY0 + timedelta(days=20))
        tested = self.card("anders", due_in=40, last_review=DAY0 + timedelta(days=26))
        # Familiar on day 25 and marked known on day 29, due the day after
        # (`claimed`): every hearing came before there was a claim to test.
        claimed = Card(Unit.lemma("bloß"), DAY0 + timedelta(days=30, hours=1), 1.0, 2.5, 0)
        heard = {familiar.unit: Rung(ENOUGH, DAY0 + timedelta(days=25)),
                 climbing.unit: Rung(ENOUGH - 1, DAY0 + timedelta(days=25)),
                 # Familiar since day 25, and reviewed on day 26: the call
                 # was answered.
                 tested.unit: Rung(ENOUGH, DAY0 + timedelta(days=25)),
                 claimed.unit: Rung(ENOUGH, DAY0 + timedelta(days=25))}
        self.assertEqual(
            due_now([familiar, climbing, tested, claimed, overdue], now, heard, ENOUGH),
            [(overdue, BY_DATE), (familiar, BY_HEARING)])
        # Heard again after that review, at the top still: nothing moves,
        # so nothing calls.
        self.assertEqual(due_now([tested], now, heard, ENOUGH), [])


if __name__ == "__main__":
    unittest.main()
