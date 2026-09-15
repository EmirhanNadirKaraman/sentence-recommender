"""What somebody thought of a sentence, and what the ranking does with it.

`corpus.quality.score` reads a sentence's length and how many of its words
are distinct, and ranks examples on that already. What it cannot see is that
`Du hast studiert, also wo die Verlet zurückgetreten ist` is a transcription
error: ordinary length, ordinary variety, and a word that is not German.

So a verdict is the judgement that has to come from outside the text — a
reader saying so, or a model asked to translate the sentence and declining.
It sits above the computed score in the ranking, because known-bad should
lose to merely-thought-worse.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from corpus.overrides import SentenceOverrides
from corpus.sentence import Sentence
from roadmap.examples import ExampleIndex, rank
from vocab.entry import Unit

WORD = Unit.exact("zurücktreten")
GOOD = "Der Kanzler ist gestern von seinem Amt zurückgetreten."
BAD = "Du hast studiert, also wo die Verlet zurückgetreten ist."


def sentences() -> list[Sentence]:
    return [Sentence(text=BAD, units=frozenset({WORD})),
            Sentence(text=GOOD, units=frozenset({WORD}))]


class StoreTest(unittest.TestCase):
    def _store(self, tmp) -> SentenceOverrides:
        return SentenceOverrides(Path(tmp) / "state.sqlite3")

    def test_a_verdict_is_kept_and_returned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.mark(BAD, 0.0, source="model")
            self.assertEqual(store.verdicts(), {BAD: 0.0})

    def test_an_unjudged_sentence_is_simply_absent(self) -> None:
        """Absent is not the same as middling: a sentence nobody has read
        should rank on its merits, not be penalised for going unread."""
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.mark(BAD, 0.0)
            self.assertNotIn(GOOD, store.verdicts())

    def test_unmarking_forgets_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.mark(BAD, 0.0)
            store.unmark(BAD)
            self.assertEqual(store.verdicts(), {})

    def test_a_later_verdict_replaces_an_earlier_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.mark(BAD, 0.0, source="model")
            store.mark(BAD, 1.0, source="reader")
            self.assertEqual(store.verdicts()[BAD], 1.0)

    def test_it_is_held_to_nought_and_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.mark(BAD, -3.0)
            store.mark(GOOD, 7.0)
            self.assertEqual(store.verdicts(), {BAD: 0.0, GOOD: 1.0})


class RankTest(unittest.TestCase):
    def _first(self, verdicts=None) -> str:
        index = ExampleIndex(sentences())
        found = index.examples(WORD, frozenset(), limit=2, verdicts=verdicts)
        return found[0].text

    def test_without_verdicts_nothing_moves(self) -> None:
        """The guard: adding this must reorder nothing unmarked. Both
        sentences are well formed, so the existing key decides — and it has
        to go on deciding."""
        self.assertEqual(self._first(), self._first(verdicts={}))

    def test_a_sentence_marked_bad_sinks(self) -> None:
        self.assertEqual(self._first(verdicts={BAD: 0.0}), GOOD)

    def test_it_outranks_the_computed_score(self) -> None:
        """`quality` cannot see the transcription error, so the only way the
        broken sentence loses is for the verdict to be checked first."""
        from corpus.quality import score
        # If the broken one scores at least as well on text alone, then any
        # ordering that fixes it must be coming from the verdict.
        self.assertGreaterEqual(score(BAD), score(GOOD) - 0.5)
        self.assertEqual(self._first(verdicts={BAD: 0.0}), GOOD)

    def test_marking_the_good_one_moves_it_too(self) -> None:
        """Symmetry, so the term is doing what it says rather than happening
        to agree with the existing order."""
        self.assertEqual(self._first(verdicts={GOOD: 0.0}), BAD)

    def test_the_key_is_shared_with_the_walk(self) -> None:
        """`rank` is what the walk stores decks with. Given the same
        verdicts it must produce the same order, or a page served from the
        store opens on a different sentence than one rebuilt from the
        corpus."""
        verdicts = {BAD: 0.0}
        walked = sorted(sentences(),
                        key=rank(WORD, frozenset(), None, None, verdicts))
        page = ExampleIndex(sentences()).examples(
            WORD, frozenset(), limit=2, verdicts=verdicts)
        self.assertEqual([s.text for s in walked], [s.text for s in page])


if __name__ == "__main__":
    unittest.main()
