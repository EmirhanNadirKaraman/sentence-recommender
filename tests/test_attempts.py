"""What you wrote with a word is kept, graded once graded, and read back
newest first."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from vocab.attempts import Attempts
from vocab.entry import Unit


class AttemptsTest(unittest.TestCase):
    def test_the_popups_check_is_ungraded_until_a_review_grades_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Attempts(Path(tmp) / "state.sqlite3")
            also = Unit.lemma("also")
            store.add(also, "Also, wir gehen.", "Also, wir gehen.", "Correct.", "So, we go.",
                      None, "popup", datetime(2026, 9, 21, 20, 0))
            store.add(also, "Ich habe also Hunger gegessen.", "Ich habe also Hunger.",
                      "Hunger is not eaten.", "So I am hungry.", None, "review",
                      datetime(2026, 9, 21, 21, 0))
            self.assertEqual([a["correct"] for a in store.of(also)], [None, None])
            store.grade_last(also, False)
            found = store.of(also)
            self.assertEqual([(a["written"], a["correct"], a["place"]) for a in found],
                             [("Ich habe also Hunger gegessen.", False, "review"),
                              ("Also, wir gehen.", None, "popup")])
            self.assertEqual(store.of(Unit.lemma("anders")), [])


if __name__ == "__main__":
    unittest.main()
