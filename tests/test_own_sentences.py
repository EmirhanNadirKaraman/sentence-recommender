"""The sentences you wrote to say: kept, scheduled, and asked for again."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from srs.scheduler import SM2Scheduler
from vocab.own_sentences import OwnSentences

FUZZ = SM2Scheduler.FUZZ


class OwnSentencesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.own = OwnSentences(Path(self._dir.name) / "state.sqlite3")
        self.now = datetime(2026, 9, 21, 12, 0)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_a_kept_sentence_is_due_at_once_and_spaced_once_said(self) -> None:
        self.own.add("Ich muss mein Visum verlängern.", "I have to renew my visa.", self.now)
        self.assertEqual([d["english"] for d in self.own.due(self.now)],
                         ["I have to renew my visa."])
        self.own.grade("Ich muss mein Visum verlängern.", True, self.now)
        self.assertEqual(self.own.due(self.now), [])
        said = self.own.due(self.now + timedelta(days=3))
        self.assertEqual([(d["text"], d["english"]) for d in said],
                         [("Ich muss mein Visum verlängern.", "I have to renew my visa.")])
        # Two and a half days out, nudged off the exact hour like any
        # other card: sentences kept in one sitting come back spread out
        # (`srs.scheduler._due`).
        asked = datetime.fromisoformat(said[0]["due"]) - self.now
        self.assertAlmostEqual(asked.total_seconds() / 86400, 2.5, delta=2.5 * FUZZ)
        self.assertNotEqual(asked, timedelta(days=2.5))
        self.assertEqual(self.own.all()[0]["repetitions"], 1)

    def test_not_said_comes_back_tomorrow(self) -> None:
        self.own.add("Wo ist der Bahnhof?", "Where is the station?", self.now)
        self.own.grade("Wo ist der Bahnhof?", False, self.now)
        self.assertEqual(self.own.due(self.now + timedelta(hours=23)), [])
        self.assertEqual(len(self.own.due(self.now + timedelta(days=1))), 1)

    def test_kept_twice_is_one_and_forgotten_is_gone(self) -> None:
        self.own.add("Bis später.", "See you later.", self.now)
        self.own.add("Bis später.", "See you later!", self.now)
        self.assertEqual(self.own.texts(), frozenset({"Bis später."}))
        self.assertEqual(self.own.all()[0]["english"], "See you later!")
        self.own.remove("Bis später.")
        self.assertEqual(self.own.all(), [])


if __name__ == "__main__":
    unittest.main()
