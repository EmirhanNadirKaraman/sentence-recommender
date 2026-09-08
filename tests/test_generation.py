"""The generate-and-verify loop.

The model is asked for a sentence using only known words, and cannot be
trusted to comply.  Verification is therefore the feature, not a safety net:
a candidate is accepted only when re-analysis says its unknowns are exactly
the target.  These tests drive that loop with a scripted client, so they cover
the part that would otherwise first run against a live endpoint.
"""
from __future__ import annotations

import unittest

from corpus.sentence import GENERATED, Sentence
from generation import SentenceGenerator
from vocab.entry import Unit

KNOWN = frozenset({Unit.lemma("ich"), Unit.lemma("sein")})
TARGET = Unit.lemma("haus")


class ScriptedClient:
    """Returns canned replies in order and records what it was asked."""

    available = True

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, system: str, user: str, temperature: float = 0.7) -> str:
        self.prompts.append(user)
        if not self._replies:
            raise RuntimeError("model unreachable")
        return self._replies.pop(0)


class FakeAnalyzer:
    """Assigns units by looking words up in a table, standing in for spaCy."""

    def __init__(self, table: dict[str, set[Unit]]) -> None:
        self._table = table

    def analyze_all(self, sentences: list[Sentence]) -> list[Sentence]:
        return [s.with_units(frozenset(self._table.get(s.text, set()))) for s in sentences]


def reply(german: str, english: str = "x") -> str:
    return f'{{"german": "{german}", "english": "{english}"}}'


class SentenceGeneratorTest(unittest.TestCase):
    def test_accepts_a_sentence_whose_only_unknown_is_the_target(self) -> None:
        client = ScriptedClient(reply("Ich bin ein Haus.", "I am a house."))
        analyzer = FakeAnalyzer({"Ich bin ein Haus.": KNOWN | {TARGET}})
        generator = SentenceGenerator(client, analyzer)

        result = generator.generate(TARGET, KNOWN, ["ich", "sein"])

        self.assertIsNotNone(result)
        self.assertEqual(result.text, "Ich bin ein Haus.")
        self.assertEqual(result.translation, "I am a house.")
        self.assertEqual(result.origin, GENERATED)
        self.assertEqual((generator.attempts, generator.accepted), (1, 1))

    def test_rejects_extra_unknowns_and_names_them_on_the_retry(self) -> None:
        client = ScriptedClient(reply("Ich sehe das Haus."), reply("Ich bin ein Haus."))
        analyzer = FakeAnalyzer({
            "Ich sehe das Haus.": KNOWN | {TARGET, Unit.lemma("sehen")},
            "Ich bin ein Haus.": KNOWN | {TARGET},
        })
        generator = SentenceGenerator(client, analyzer)

        result = generator.generate(TARGET, KNOWN, ["ich"])

        self.assertEqual(result.text, "Ich bin ein Haus.")
        self.assertEqual(generator.attempts, 2)
        self.assertIn("sehen", client.prompts[1])

    def test_rejects_a_sentence_that_never_uses_the_target(self) -> None:
        client = ScriptedClient(reply("Ich bin."), reply("Ich bin."))
        analyzer = FakeAnalyzer({"Ich bin.": KNOWN})
        generator = SentenceGenerator(client, analyzer, max_attempts=2)

        self.assertIsNone(generator.generate(TARGET, KNOWN, ["ich"]))
        self.assertEqual(generator.accepted, 0)

    def test_gives_up_after_max_attempts(self) -> None:
        bad = reply("Ich sehe das Haus.")
        client = ScriptedClient(bad, bad, bad, bad, bad)
        analyzer = FakeAnalyzer({
            "Ich sehe das Haus.": KNOWN | {TARGET, Unit.lemma("sehen")}
        })
        generator = SentenceGenerator(client, analyzer, max_attempts=3)

        self.assertIsNone(generator.generate(TARGET, KNOWN, ["ich"]))
        self.assertEqual(generator.attempts, 3)

    def test_a_dead_model_returns_nothing_rather_than_raising(self) -> None:
        """A review must survive an unreachable endpoint."""
        analyzer = FakeAnalyzer({})
        generator = SentenceGenerator(ScriptedClient(), analyzer, max_attempts=2)
        self.assertIsNone(generator.generate(TARGET, KNOWN, ["ich"]))

    def test_finds_json_wrapped_in_prose_or_fences(self) -> None:
        client = ScriptedClient(
            'Sure! Here you go:\n```json\n{"german": "Ich bin ein Haus.", '
            '"english": "I am a house."}\n```\nHope that helps.'
        )
        analyzer = FakeAnalyzer({"Ich bin ein Haus.": KNOWN | {TARGET}})
        result = SentenceGenerator(client, analyzer).generate(TARGET, KNOWN, ["ich"])
        self.assertEqual(result.text, "Ich bin ein Haus.")

    def test_unparseable_replies_are_skipped_not_accepted(self) -> None:
        client = ScriptedClient("I cannot do that.", reply("Ich bin ein Haus."))
        analyzer = FakeAnalyzer({"Ich bin ein Haus.": KNOWN | {TARGET}})
        generator = SentenceGenerator(client, analyzer)
        self.assertEqual(
            generator.generate(TARGET, KNOWN, ["ich"]).text, "Ich bin ein Haus."
        )


if __name__ == "__main__":
    unittest.main()
