"""Vocabulary parsing, subtitle assembly, and sentence filtering."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from corpus import MergeCorrector, SentenceFilter
from corpus.sentence import RawLine, Sentence
from vocab import Unit, WordListLoader


def line(sentence_id: int, content: str) -> RawLine:
    return RawLine(sentence_id=sentence_id, video_id="v", start_time=float(sentence_id),
                   content=content, tokens=tuple(content.split()))


class UnitTest(unittest.TestCase):
    def test_lemmas_are_case_folded_so_they_dedupe(self) -> None:
        self.assertEqual(Unit.lemma("Geben"), Unit.lemma("geben"))
        self.assertEqual(len({Unit.lemma("Geben"), Unit.lemma("geben")}), 1)

    def test_a_pattern_never_collides_with_a_word(self) -> None:
        self.assertNotEqual(Unit.lemma("geben"), Unit.pattern("geben"))


class WordListLoaderTest(unittest.TestCase):
    def load(self, text: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "words.txt"
            path.write_text(text, encoding="utf-8")
            return WordListLoader().load(path)

    def test_strips_articles_and_splits_on_commas(self) -> None:
        words = self.load("der Abend\nder, die, das\ndie Adresse\n")
        self.assertEqual(words.surfaces, ("abend", "der", "die", "das", "adresse"))

    def test_ignores_comments_and_blank_lines(self) -> None:
        words = self.load("# a heading\n\nhaus   # trailing note\n")
        self.assertEqual(words.surfaces, ("haus",))

    def test_deduplicates_but_keeps_first_position(self) -> None:
        words = self.load("und\nhaus\nund\n")
        self.assertEqual(words.surfaces, ("und", "haus"))
        self.assertEqual(words.ranks()["haus"], 1)

    def test_a_multiword_entry_survives_intact(self) -> None:
        self.assertEqual(self.load("zu Hause\n").surfaces, ("zu hause",))


class MergeCorrectorTest(unittest.TestCase):
    def test_joins_a_sentence_split_across_subtitle_lines(self) -> None:
        result = MergeCorrector().correct([
            line(1, "Wir haben heute Namen dabei,"),
            line(2, "die man kennen sollte."),
        ])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "Wir haben heute Namen dabei, die man kennen sollte.")
        self.assertEqual(result[0].source_ids, (1, 2))
        self.assertFalse(result[0].was_corrected)   # joined, but no text changed

    def test_splits_a_line_holding_two_sentences(self) -> None:
        result = MergeCorrector().correct([line(1, "Das ist gut. Ich gehe jetzt.")])
        self.assertEqual([s.text for s in result], ["Das ist gut.", "Ich gehe jetzt."])

    def test_strips_stage_directions(self) -> None:
        result = MergeCorrector().correct([line(1, "*Olaf lacht.* Ach, hier sind sie.")])
        self.assertEqual([s.text for s in result], ["Ach, hier sind sie."])
        self.assertTrue(result[0].was_corrected)
        self.assertEqual(result[0].original, "*Olaf lacht.* Ach, hier sind sie.")

    def test_keeps_abbreviations_whole(self) -> None:
        for text in ("Ich mag z.B. Kaffee sehr.", "Das ist Dr. Meier.",
                     "Er kommt bzw. Sie kommt."):
            with self.subTest(text=text):
                result = MergeCorrector().correct([line(1, text)])
                self.assertEqual([s.text for s in result], [text])

    def test_does_not_split_on_a_lowercase_continuation(self) -> None:
        """German abbreviations end in a dot but continue in lower case."""
        result = MergeCorrector().correct([line(1, "Ich mag z.B. Kaffee sehr.")])
        self.assertEqual([s.text for s in result], ["Ich mag z.B. Kaffee sehr."])


class SentenceFilterTest(unittest.TestCase):
    def reasons(self, *texts: str) -> dict:
        f = SentenceFilter(4, 15)
        f.apply([Sentence(text=t) for t in texts])
        return dict(f.rejected)

    def test_rejects_fragments_and_artifacts(self) -> None:
        self.assertEqual(
            self.reasons("Das ist ein Satz ohne Ende", "Das ist [Musik] hier."),
            {"unterminated": 1, "artifact": 1},
        )

    def test_bounds_length_at_both_ends(self) -> None:
        self.assertEqual(
            self.reasons("Ja gut.", " ".join(["wort"] * 20) + "."),
            {"length": 2},
        )

    def test_deduplicates_ignoring_case_and_punctuation(self) -> None:
        f = SentenceFilter(2, 15)
        kept = f.apply([Sentence(text="Das ist gut."), Sentence(text="das ist gut!")])
        self.assertEqual(len(kept), 1)
        self.assertEqual(f.rejected["duplicate"], 1)

    def test_keeps_a_clean_sentence(self) -> None:
        f = SentenceFilter(4, 15)
        self.assertEqual(len(f.apply([Sentence(text="Ich habe ein neues Auto.")])), 1)
        self.assertEqual(dict(f.rejected), {})


if __name__ == "__main__":
    unittest.main()


class LLMCorrectorTest(unittest.TestCase):
    """Repairing subtitle lines with the local model.

    The model is never load-bearing: a chunk it fails on falls through to the
    rule-based corrector rather than being lost, and provenance survives the
    rewrite so the original is always recoverable.
    """

    def setUp(self) -> None:
        self.lines = [
            line(11, "Wir haben heute Namen dabei,"),
            line(12, "die man kennen sollte."),
        ]

    def correct(self, *replies: str, chunk_size: int = 25):
        from corpus import LLMCorrector
        client = ScriptedClient(*replies)
        corrector = LLMCorrector(client, chunk_size=chunk_size)
        return corrector, corrector.correct(self.lines), client

    def test_takes_the_model_s_sentences_and_their_provenance(self) -> None:
        corrector, result, _ = self.correct(
            '{"sentences": [{"german": "Wir haben heute Namen dabei, '
            'die man kennen sollte.", "lines": [1, 2]}]}'
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source_ids, (11, 12))
        self.assertEqual(result[0].original,
                         "Wir haben heute Namen dabei, die man kennen sollte.")
        self.assertEqual(corrector.fallbacks, 0)

    def test_a_repair_is_visible_as_a_correction(self) -> None:
        _, result, _ = self.correct(
            '{"sentences": [{"german": "Wir haben heute Namen dabei, '
            'die man kennen sollte!", "lines": [1, 2]}]}'
        )
        self.assertTrue(result[0].was_corrected)
        self.assertNotEqual(result[0].original, result[0].text)

    def test_an_unparseable_reply_falls_back_rather_than_losing_the_lines(self) -> None:
        corrector, result, _ = self.correct("I'm sorry, I can't help with that.")
        self.assertEqual(corrector.fallbacks, 1)
        self.assertEqual([s.text for s in result],
                         ["Wir haben heute Namen dabei, die man kennen sollte."])

    def test_a_dead_model_falls_back(self) -> None:
        corrector, result, _ = self.correct()      # client raises
        self.assertEqual(corrector.fallbacks, 1)
        self.assertEqual(len(result), 1)

    def test_out_of_range_line_numbers_do_not_crash(self) -> None:
        _, result, _ = self.correct(
            '{"sentences": [{"german": "Etwas.", "lines": [1, 99]}]}'
        )
        self.assertEqual(result[0].source_ids, (11,))

    def test_lines_are_sent_in_chunks(self) -> None:
        good = '{"sentences": [{"german": "Etwas.", "lines": [1]}]}'
        corrector, result, client = self.correct(good, good, chunk_size=1)
        self.assertEqual(corrector.chunks, 2)
        self.assertEqual(len(client.prompts), 2)
        self.assertIn("1. Wir haben heute Namen dabei,", client.prompts[0])
        self.assertIn("1. die man kennen sollte.", client.prompts[1])


class ScriptedClient:
    """Returns canned replies in order; raises once they run out."""

    available = True

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, system: str, user: str, temperature: float = 0.7) -> str:
        self.prompts.append(user)
        if not self._replies:
            raise RuntimeError("model unreachable")
        return self._replies.pop(0)


class LemmaLookupTest(unittest.TestCase):
    """The guards around spaCy's context-free German lemma table.

    Applied broadly that table is destructive — it maps `sein` to `mein` and
    `sie` to `ich`, because it conflates whole pronoun paradigms. These tests
    pin the three conditions that make consulting it safe.
    """

    def setUp(self) -> None:
        from corpus.analyzer import UnitAnalyzer
        self.analyzer = UnitAnalyzer(frozenset())
        self.analyzer._verb_lemmas = _FakeLookup({
            "willst": "wollen", "sein": "mein", "sie": "ich", "muss": "müssen",
        })

    def lemma(self, text: str, spacy_lemma: str, tag: str) -> str:
        return self.analyzer._verb_lemma(_FakeToken(text, spacy_lemma, tag))

    def test_folds_an_inflected_verb_the_parser_gave_up_on(self) -> None:
        self.assertEqual(self.lemma("willst", "willst", "VMFIN"), "wollen")

    def test_leaves_an_infinitive_alone_even_when_the_table_has_it(self) -> None:
        """This is what keeps `sein` from becoming `mein`."""
        self.assertEqual(self.lemma("sein", "sein", "VAINF"), "sein")

    def test_never_touches_a_non_verb(self) -> None:
        """And this is what keeps `sie` from becoming `ich`."""
        self.assertEqual(self.lemma("sie", "sie", "PPER"), "sie")

    def test_leaves_a_lemma_the_parser_resolved(self) -> None:
        self.assertEqual(self.lemma("musst", "müssen", "VMFIN"), "müssen")

    def test_lower_cases_so_units_dedupe(self) -> None:
        self.assertEqual(self.lemma("Haus", "Haus", "NN"), "haus")

    def test_drops_the_placeholder_lemma(self) -> None:
        self.assertEqual(self.lemma(".", "--", "$."), "")


class LemmaCorrectionsTest(unittest.TestCase):
    """The corpus-wide vote that catches what the tag guard cannot."""

    def corrections(self, observed: dict[str, dict[str, int]]) -> dict:
        from collections import Counter
        from corpus.analyzer import Evidence, UnitAnalyzer
        evidence = Evidence()
        for surface, lemmas in observed.items():
            evidence.by_surface[surface] = Counter(lemmas)
        return UnitAnalyzer(frozenset())._lemma_corrections(evidence)

    def test_repairs_a_form_the_parser_usually_gets_right(self) -> None:
        """`Willst` is mis-tagged sentence-initially but fine elsewhere."""
        self.assertEqual(
            self.corrections({"willst": {"wollen": 900, "willst": 100}}),
            {"willst": "wollen"},
        )

    def test_leaves_a_genuine_ambiguity_alone(self) -> None:
        """`weiß` is both a colour and a form of `wissen`; both are real."""
        self.assertEqual(self.corrections({"weiß": {"wissen": 600, "weiß": 500}}), {})

    def test_ignores_a_surface_that_never_failed(self) -> None:
        self.assertEqual(self.corrections({"hat": {"haben": 5000}}), {})


class _FakeToken:
    def __init__(self, text: str, lemma: str, tag: str) -> None:
        self.text, self.lemma_, self.tag_ = text, lemma, tag


class _FakeLookup:
    def __init__(self, table: dict[str, str]) -> None:
        self._table = table

    def get(self, surface: str, default: str = "") -> str:
        return self._table.get(surface, default)
