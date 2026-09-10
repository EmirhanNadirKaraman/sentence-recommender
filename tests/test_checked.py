"""Confirmations, and the reason they are written down at all.

A "no" in the quiz has always left a trace — the line is commented out and
shows up in a diff. A "yes" left none, which sounds harmless and is not: the
quiz asks the most frequent words first, forty at a time, so with no record of
what was already confirmed the second run asks the same forty as the first.
The property worth pinning is therefore the boring one, that a confirmation
survives the process, plus the two ways a word can leave the pool.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from commands.quiz import ANSWERS, PROMPT
from vocab.checked_store import CheckedStore
from vocab.entry import Unit

HAUS = Unit.lemma("haus")
BAUM = Unit.lemma("baum")
DER = Unit.pattern("der Hut")


class CheckedTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "state.sqlite3"
        self.store = CheckedStore(self.path)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_a_confirmation_survives_the_process(self) -> None:
        self.store.confirm(HAUS)
        self.assertIn(HAUS, CheckedStore(self.path).units())

    def test_confirming_twice_is_one_confirmation(self) -> None:
        """The same word is written in both vocabulary files often enough."""
        self.store.confirm(HAUS)
        self.store.confirm(HAUS)
        self.assertEqual(len(self.store), 1)

    def test_only_what_was_confirmed(self) -> None:
        self.store.confirm(HAUS)
        self.assertNotIn(BAUM, self.store.units())

    def test_kinds_are_kept_apart(self) -> None:
        """`der Hut` the pattern is not `der hut` the lemma."""
        self.store.confirm(DER)
        self.assertEqual(self.store.units(), {DER})

    def test_a_denial_puts_it_back_in_the_pool(self) -> None:
        """Confirmed once, thought better of later: the file is being changed,
        so the confirmation that contradicts it has to go."""
        self.store.confirm(HAUS)
        self.store.forget(HAUS)
        self.assertEqual(len(self.store), 0)

    def test_forgetting_what_was_never_confirmed_is_quiet(self) -> None:
        self.store.forget(BAUM)
        self.assertEqual(len(self.store), 0)


class AnswerTest(unittest.TestCase):
    """What the prompt offers and what it accepts have to agree.

    A typo used to mean yes — the dispatch ended in an `else` that counted the
    word as known — so a slipped keystroke silently confirmed a word nobody
    had looked at.
    """

    def test_every_offered_key_is_accepted(self) -> None:
        for key in ("n", "s", "q", ""):
            self.assertIn(key, ANSWERS, f"the prompt offers {key!r}")

    def test_the_obvious_yes_is_accepted(self) -> None:
        """Nobody reads the prompt closely enough not to type it."""
        self.assertIn("y", ANSWERS)

    def test_a_typo_is_not_an_answer(self) -> None:
        for typo in ("yy", "k", "no idea", "1"):
            self.assertNotIn(typo, ANSWERS)

    def test_the_prompt_names_the_keys_it_takes(self) -> None:
        for key in ("n=", "s=", "q="):
            self.assertIn(key, PROMPT)


if __name__ == "__main__":
    unittest.main()
