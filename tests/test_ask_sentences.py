"""The corpus pass: one request per sentence, every question in it, the
answers read back as numbers in [0, 1]."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from commands.ask_sentences import _once, read, state_and_questions
from corpus.sentence import Sentence
from vocab.entry import Unit


class RequestTest(unittest.TestCase):
    def sentence(self) -> Sentence:
        geben = Unit.pattern("jdm. (Dat) etw. (Akk) geben")
        return Sentence(text="Ich gebe dir das Buch.",
                        units=frozenset({geben, Unit.exact("ich"), Unit.exact("buch")}),
                        surfaces=((geben, "gebe dir dir das Buch"),))

    def test_only_pattern_units_are_asked_about(self) -> None:
        state, asked, which = state_and_questions(self.sentence())
        self.assertEqual(list(state["units"]), ["u1"])
        self.assertEqual(which["u1"].key, "jdm. (Dat) etw. (Akk) geben")
        self.assertEqual(state["units"]["u1"]["spoken"], "geben")

    def test_the_surface_says_each_word_once(self) -> None:
        state, _, _ = state_and_questions(self.sentence())
        self.assertEqual(state["units"]["u1"]["surface"], "gebe dir das Buch")
        self.assertEqual(_once("tue mir mir an an 0:3."), "tue mir an 0:3.")

    def test_every_question_travels_in_one_request(self) -> None:
        _, asked, _ = state_and_questions(self.sentence())
        self.assertEqual(set(asked), {"stands_alone", "complete", "standard", "well_formed",
                                      "expression", "level", "plain:u1", "guessable:u1"})


class ReadTest(unittest.TestCase):
    def test_each_kind_becomes_a_number_in_the_unit_interval(self) -> None:
        answers = {
            "complete": SimpleNamespace(type="noul", noul=0.93),
            "guessable:u1": SimpleNamespace(type="score", score=1.5, legend={0: "", 1: "", 2: ""}),
            "level": SimpleNamespace(type="choice", choice="A2",
                                     probabilities={"A1": 0.2, "A2": 0.6, "B1": 0.2,
                                                    "B2": 0.0, "C1": 0.0}),
        }
        response = SimpleNamespace(answers=answers)
        out = read(response, dict.fromkeys(answers))
        self.assertEqual(out["complete"], (0.93, None))
        self.assertEqual(out["guessable:u1"], (0.75, None))
        value, distribution = out["level"]
        self.assertAlmostEqual(value, 0.25)      # expected level 1.0 of 4
        self.assertEqual(distribution["A2"], 0.6)


if __name__ == "__main__":
    unittest.main()
