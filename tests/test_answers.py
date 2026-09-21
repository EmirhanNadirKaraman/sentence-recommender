"""The judge's answers, stored raw and read as a ranking.

Absent means unjudged and scores 1.0, so an empty store reorders nothing;
only a sentence the judge has doubted moves, and it moves down. A refusal
by the gloss is a fact about a pair — `es gibt` refused as `geben` — and is
keyed on the pair, not on the sentence.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from corpus.answers import AnswerStore
from corpus.sentence import Sentence
from roadmap.examples import ExampleIndex
from vocab.entry import Unit

GEBEN = Unit.pattern("jdm. (Dat) etw. (Akk) geben")
GIVE = "Ich gebe dir das Buch."
THERE = "Es gibt ein Problem."
BROKEN = "Ich gebe nicht kam mir das."


def store():
    tmp = tempfile.TemporaryDirectory()
    return tmp, AnswerStore(Path(tmp.name) / "state.sqlite3")


class StoreTest(unittest.TestCase):
    def test_answers_come_back_as_a_quality_and_a_fit(self) -> None:
        tmp, answers = store()
        with tmp:
            answers.save(GIVE, "jev", 1, {
                "stands_alone": (0.9, None), "complete": (1.0, None),
                "standard": (1.0, None), "well_formed": (0.5, None),
                "plain:u1": (0.8, None), "guessable:u1": (1.0, None),
            }, units={"u1": GEBEN})
            judged = answers.load("jev", 1)
        self.assertAlmostEqual(judged.sentence(GIVE), 0.45)
        self.assertAlmostEqual(judged.unit(GIVE, GEBEN), 0.8)

    def test_guessable_is_kept_but_not_read(self) -> None:
        """Asked of some sentences and not others, a factor would order the
        judged below the unjudged; the raw answer stays for later."""
        tmp, answers = store()
        with tmp:
            answers.save(GIVE, "jev", 1, {"plain:u1": (1.0, None),
                                          "guessable:u1": (0.0, None)}, units={"u1": GEBEN})
            judged = answers.load("jev", 1)
            self.assertEqual(answers.counts()["guessable"], 1)
        self.assertEqual(judged.unit(GIVE, GEBEN), 1.0)

    def test_with_nothing_judged_nothing_moves(self) -> None:
        tmp, answers = store()
        with tmp:
            judged = answers.load("jev", 1)
        self.assertEqual(judged.sentence(GIVE), 1.0)
        self.assertEqual(judged.unit(GIVE, GEBEN), 1.0)

    def test_unjudged_scores_as_a_typical_judged_sentence(self) -> None:
        """Not as a perfect one: the walk picks candidates from every
        sentence saying the word, and at 1.0 the unjudged would win every
        pick. At the median, judged-good stays, judged-bad drops out."""
        tmp, answers = store()
        with tmp:
            for text, quality in ((GIVE, 0.9), (BROKEN, 0.1), (THERE, 0.4)):
                answers.save(text, "jev", 1, {"complete": (quality, None)})
            answers.save(GIVE, "jev", 1, {"plain:u1": (0.8, None)}, units={"u1": GEBEN})
            judged = answers.load("jev", 1)
        unjudged = "Kannst du mir das Salz geben?"
        self.assertEqual(judged.sentence(unjudged), 0.4)          # the median
        self.assertGreater(judged.sentence(GIVE), judged.sentence(unjudged))
        self.assertLess(judged.sentence(BROKEN), judged.sentence(unjudged))
        self.assertEqual(judged.unit(unjudged, GEBEN), 0.8)       # the one plain answer

    def test_another_version_or_model_is_not_read(self) -> None:
        tmp, answers = store()
        with tmp:
            answers.save(GIVE, "jev", 1, {"complete": (0.1, None)})
            answers.save(THERE, "other", 2, {"complete": (0.1, None)})
            judged = answers.load("jev", 2)
        self.assertEqual(judged.sentence(GIVE), 1.0)
        self.assertEqual(judged.sentence(THERE), 1.0)

    def test_a_refusal_is_about_the_pair(self) -> None:
        """`Es gibt ein Problem.` refused as `geben` is worthless for `geben`
        and untouched for any other word -- and it is the gloss's model
        that refused, so it is read under the judge's name too."""
        tmp, answers = store()
        with tmp:
            answers.refuse(THERE, GEBEN, "local")
            judged = answers.load("jev", 1)
        self.assertEqual(judged.unit(THERE, GEBEN), 0.0)
        self.assertEqual(judged.unit(THERE, Unit.pattern("es gibt")), 1.0)
        self.assertEqual(judged.sentence(THERE), 1.0)

    def test_the_level_is_an_ease_and_a_label(self) -> None:
        """Stored as the expected level over A1–C1 scaled to one; read as
        a share of the sentence's worth, a fifth off per level, and as the
        nearest label for a badge."""
        tmp, answers = store()
        with tmp:
            answers.save(GIVE, "jev", 1, {"level": (0.0, {"A1": 1.0})})       # A1
            answers.save(THERE, "jev", 1, {"level": (0.5, {"B1": 1.0})})      # B1
            answers.save(BROKEN, "jev", 1, {"level": (0.75, {"B2": 1.0})})    # B2
            judged = answers.load("jev", 1)
        self.assertEqual(judged.level(GIVE), "A1")
        self.assertEqual(judged.level(THERE), "B1")
        self.assertIsNone(judged.level("Nie gefragt."))
        self.assertAlmostEqual(judged.ease(GIVE), 1.0)
        self.assertAlmostEqual(judged.ease(THERE), 0.6)
        self.assertAlmostEqual(judged.ease(BROKEN), 0.4)
        # Unjudged is a typical judged sentence, the median: B1 here.
        self.assertAlmostEqual(judged.ease("Nie gefragt."), 0.6)

    def test_with_no_level_judged_ease_is_everything(self) -> None:
        tmp, answers = store()
        with tmp:
            judged = answers.load("jev", 1)
        self.assertEqual(judged.ease(GIVE), 1.0)
        self.assertIsNone(judged.level(GIVE))

    def test_doubted_is_the_pairs_the_judge_said_no_to(self) -> None:
        """`plain` under the doubt line, or a refusal; a pair the judge
        merely thinks less of is ranked, not dropped."""
        tmp, answers = store()
        with tmp:
            answers.save(GIVE, "jev", 1, {"plain:u1": (0.05, None), "plain:u2": (0.4, None)},
                         units={"u1": Unit.pattern("jdm. (Dat) gehören"), "u2": GEBEN})
            answers.refuse(THERE, GEBEN, "local")
            judged = answers.load("jev", 1)
        self.assertEqual(judged.doubted(), {GIVE: frozenset({"jdm. (Dat) gehören"}),
                                            THERE: frozenset({GEBEN.key})})

    def test_answered_is_what_a_resumed_pass_skips(self) -> None:
        tmp, answers = store()
        with tmp:
            answers.save(GIVE, "jev", 1, {"complete": (0.9, None)})
            self.assertEqual(answers.answered("jev", 1), {GIVE})
            self.assertEqual(answers.answered("jev", 2), set())

    def test_answered_means_every_question_the_run_asks(self) -> None:
        """A level-only run over a video skips what the full pass levelled;
        the full pass does not skip a sentence that has only its level."""
        tmp, answers = store()
        with tmp:
            answers.save(GIVE, "jev", 1, {"complete": (0.9, None), "level": (0.2, None)})
            answers.save(THERE, "jev", 1, {"level": (0.2, None)})
            self.assertEqual(answers.answered("jev", 1, ("level",)), {GIVE, THERE})
            self.assertEqual(answers.answered("jev", 1, ("complete", "level")), {GIVE})
            self.assertEqual(answers.answered("jev", 1), {GIVE})


class RankTest(unittest.TestCase):
    def sentences(self):
        return [Sentence(text=t, units=frozenset({GEBEN, Unit.exact("ich")}))
                for t in (BROKEN, GIVE)]

    def test_the_judge_moves_a_doubted_sentence_down(self) -> None:
        index = ExampleIndex(self.sentences())
        tmp, answers = store()
        with tmp:
            answers.save(BROKEN, "jev", 1, {"well_formed": (0.1, None)})
            judged = answers.load("jev", 1)
        first = index.examples(GEBEN, frozenset({Unit.exact("ich")}), limit=1,
                               judged=judged)[0]
        self.assertEqual(first.text, GIVE)

    def test_an_empty_store_changes_nothing(self) -> None:
        index = ExampleIndex(self.sentences())
        tmp, answers = store()
        with tmp:
            judged = answers.load("jev", 1)
        known = frozenset({Unit.exact("ich")})
        self.assertEqual(index.examples(GEBEN, known, limit=2),
                         index.examples(GEBEN, known, limit=2, judged=judged))

    def test_of_two_sentences_the_judge_likes_alike_the_easier_is_first(self) -> None:
        """A B2 sentence at .9 loses to an A2 one at .7: the level is a
        factor in the worth, not a key after it, because a key after a
        continuous product hardly ever fires."""
        index = ExampleIndex(self.sentences())
        tmp, answers = store()
        with tmp:
            answers.save(BROKEN, "jev", 1, {"complete": (0.9, None), "level": (0.75, None)})
            answers.save(GIVE, "jev", 1, {"complete": (0.7, None), "level": (0.25, None)})
            judged = answers.load("jev", 1)
        first = index.examples(GEBEN, frozenset({Unit.exact("ich")}), limit=1,
                               judged=judged)[0]
        self.assertEqual(first.text, GIVE)


if __name__ == "__main__":
    unittest.main()
