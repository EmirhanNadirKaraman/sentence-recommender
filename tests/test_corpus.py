"""Vocabulary parsing, subtitle assembly, and sentence filtering."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from corpus import MergeCorrector, SentenceFilter
from corpus.sentence import RawLine, Sentence
from vocab import Unit, WordListLoader


def line(sentence_id: int, content: str, start: float | None = None,
         duration: float = 2.0) -> RawLine:
    return RawLine(
        sentence_id=sentence_id, video_id="v",
        start_time=float(sentence_id) if start is None else start,
        duration=duration, content=content, tokens=tuple(content.split()),
    )


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


class GoalCorrectionTest(unittest.TestCase):
    """`goal_lemmas.txt` has to be able to overrule a pattern match.

    It is hand-checked, one line per entry the derived machinery gets wrong.
    The pattern branch used to run first and `continue`, so a correction
    written for a registered canonical was silently dead — which is what
    `gucken, kucken` was: registered as a pattern, emitted by nothing, and
    stranded while the corpus said `gucken` five hundred times.
    """

    def units(self, entries, patterns, corrections):
        import tempfile
        from pathlib import Path as P

        from vocab.goal_list import GoalList
        with tempfile.TemporaryDirectory() as d:
            path = P(d) / "goals.txt"
            path.write_text("\n".join(entries) + "\n", encoding="utf-8")
            return GoalList(path).units(frozenset(patterns),
                                        corrections=corrections)

    def test_a_correction_beats_a_pattern(self) -> None:
        got = self.units(["gucken, kucken"], {"gucken, kucken"},
                         {"gucken, kucken": "gucken"})
        self.assertEqual([u.key for u in got], ["gucken"])
        self.assertFalse(got[0].is_pattern)

    def test_a_pattern_with_no_correction_is_untouched(self) -> None:
        got = self.units(["etw. (Akk) haben"], {"etw. (Akk) haben"}, {})
        self.assertEqual([u.key for u in got], ["etw. (Akk) haben"])
        self.assertTrue(got[0].is_pattern)

    def test_alternatives_still_split_when_nothing_claims_them(self) -> None:
        got = self.units(["gucken, kucken"], set(), {})
        self.assertEqual(sorted(u.key for u in got), ["gucken", "kucken"])


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

    def test_out_of_range_line_numbers_are_ignored(self) -> None:
        """The model can name a line that does not exist; the rest still map.

        Content is preserved here so the check passes and the line handling is
        what is actually under test.
        """
        _, result, _ = self.correct(
            '{"sentences": [{"german": "Wir haben heute Namen dabei, '
            'die man kennen sollte.", "lines": [1, 99]}]}'
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
        self.analyzer._verb_lemmas = _FakeLookup(
            # spaCy's table, including the two entries that show why it is
            # never applied without guards.
            table={"willst": "wollen", "sein": "mein", "sie": "ich"},
            # The hand-written file.
            overrides={"muss": "müssen"},
            # Real German lemmas, for the invention check. `mussn` is not
            # here, which is the whole point of it.
            lemmas={"wollen", "mein", "ich", "müssen", "gehen", "wissen"},
        )

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

    def test_a_written_correction_beats_an_invented_lemma(self) -> None:
        """The parser does not only fail cleanly — it also invents.

        `muss` came back as `mussn` and `mussen`, and because neither equals
        the surface, the correction written for it was skipped and the
        invention became a unit of its own: 1,773 rows for this one word,
        against a file that had said what to do since the day it was written.
        """
        self.assertEqual(self.lemma("muss", "mussn", "VMFIN"), "müssen")
        self.assertEqual(self.lemma("muss", "mussen", "VMFIN"), "müssen")

    def test_the_table_still_cannot_beat_a_resolved_lemma(self) -> None:
        """Only the curated file is trusted that far.

        `willst` is in the table, so had this relaxation been applied to the
        table as well, a lemma the parser got right would be overwritten by a
        context-free guess.
        """
        self.assertEqual(self.lemma("willst", "wollen", "VMFIN"), "wollen")

    def test_a_written_correction_is_still_only_for_verbs(self) -> None:
        """The one guard that stays, and the reason `weißen` is safe: the
        adjective keeps its own lemma, only the verb form is folded."""
        self.assertEqual(self.lemma("muss", "muss", "NN"), "muss")

    def test_an_invented_lemma_is_refused(self) -> None:
        """The parser is an edit-tree model: it predicts a transformation,
        applies it, and never checks the result is a word. `gehst` came back
        as `hsen`, `warst` as `warn`.

        Refusing means handing back the surface, which is the shape the rest
        of this file already copes with — an identity lemma is exactly what
        the override table and the majority pass repair.
        """
        self.assertEqual(self.lemma("gehst", "hsen", "VVFIN"), "gehst")
        self.assertEqual(self.lemma("nehm", "nehmn", "VVFIN"), "nehm")

    def test_a_real_lemma_is_left_alone(self) -> None:
        """The check can only refuse, so anything the lexicon vouches for
        passes untouched."""
        self.assertEqual(self.lemma("ging", "gehen", "VVFIN"), "gehen")

    def test_only_verbs_are_checked(self) -> None:
        """A noun's lemma is not asked to be a verb lemma — this check would
        refuse most of the language if it ran on everything."""
        self.assertEqual(self.lemma("Häuser", "haus", "NN"), "haus")

    def test_lower_cases_so_units_dedupe(self) -> None:
        self.assertEqual(self.lemma("Haus", "Haus", "NN"), "haus")

    def test_drops_the_placeholder_lemma(self) -> None:
        self.assertEqual(self.lemma(".", "--", "$."), "")


class LemmaCorrectionsTest(unittest.TestCase):
    """The corpus-wide vote that catches what the tag guard cannot."""

    def corrections(self, observed: dict[str, dict[str, int]],
                    lookup: dict[str, str] | None = None) -> dict:
        from collections import Counter
        from corpus.analyzer import Evidence, UnitAnalyzer
        evidence = Evidence()
        for surface, lemmas in observed.items():
            evidence.by_surface[surface] = Counter(lemmas)
        analyzer = UnitAnalyzer(frozenset())
        analyzer._verb_lemmas = _FakeLookup(lookup or {})
        return analyzer._lemma_corrections(evidence)

    def test_repairs_a_form_the_parser_usually_gets_right(self) -> None:
        """`Willst` is mis-tagged sentence-initially but fine elsewhere."""
        self.assertEqual(
            self.corrections({"willst": {"wollen": 900, "willst": 100}}),
            {"willst": "wollen"},
        )

    def test_the_lookup_agreeing_is_enough_without_a_margin(self) -> None:
        """Sentence-initial mis-tagging can be half the occurrences."""
        observed = {"willst": {"wollen": 672, "willst": 503}}
        self.assertEqual(self.corrections(observed), {})
        self.assertEqual(
            self.corrections(observed, lookup={"willst": "wollen"}),
            {"willst": "wollen"},
        )

    def test_a_disagreeing_lookup_does_not_force_a_correction(self) -> None:
        self.assertEqual(
            self.corrections({"weiß": {"wissen": 600, "weiß": 500}},
                             lookup={"weiß": "weissen"}),
            {},
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
    """Both halves, kept apart as the real one keeps them.

    The distinction is the whole point: spaCy's table is machine-generated and
    destructive applied broadly, so it is only ever consulted behind guards.
    The hand-written file is curated, and is trusted over anything the parser
    produced. Modelling them as one dict hid that difference.
    """

    def __init__(self, table: dict[str, str],
                 overrides: dict[str, str] | None = None,
                 lemmas: set[str] | None = None) -> None:
        self._table = table
        self._overrides = overrides or {}
        # What the lexicon will vouch for as a lemma. Defaults to the table's
        # own right-hand side, which is what the real one uses.
        self._lemmas = lemmas if lemmas is not None else set(table.values())

    def override(self, surface: str) -> str:
        return self._overrides.get(surface, "")

    def is_lemma(self, word: str) -> bool:
        return word in self._lemmas

    def get(self, surface: str, default: str = "") -> str:
        if surface in self._overrides:
            return self._overrides[surface]
        return self._table.get(surface, default)


class LLMContentCheckTest(unittest.TestCase):
    """A reply is only a correction if the original words are still in it.

    Truncation, summarising and refusals all parse as valid JSON, so
    parseability proves nothing about whether the model did the job.
    """

    def setUp(self) -> None:
        self.lines = [line(1, "Wir haben heute viele bekannte Namen dabei,"),
                      line(2, "die man wirklich kennen sollte.")]

    def correct(self, *replies: str):
        from corpus import LLMCorrector
        corrector = LLMCorrector(ScriptedClient(*replies), chunk_size=25)
        return corrector, corrector.correct(self.lines)

    @staticmethod
    def reply(*sentences: str) -> str:
        import json
        return json.dumps({"sentences": [{"german": s, "lines": [1, 2]}
                                         for s in sentences]})

    def test_accepts_a_genuine_repair(self) -> None:
        corrector, result = self.correct(self.reply(
            "Wir haben heute viele bekannte Namen dabei, die man wirklich kennen sollte."
        ))
        self.assertEqual(corrector.rejected, 0)
        self.assertEqual(len(result), 1)

    def test_rejects_a_summary(self) -> None:
        corrector, result = self.correct(self.reply("Es geht um Namen."))
        self.assertEqual(corrector.rejected, 1)
        self.assertEqual(corrector.fallbacks, 1)
        self.assertIn("bekannte", result[0].text)      # the fallback kept everything

    def test_rejects_a_model_that_starts_explaining(self) -> None:
        padding = " ".join(["Das bedeutet, dass der Satz hier erklärt wird."] * 6)
        corrector, _ = self.correct(self.reply(padding))
        self.assertEqual(corrector.rejected, 1)

    def test_rejects_a_polite_refusal_that_happens_to_be_json(self) -> None:
        corrector, _ = self.correct(self.reply("I cannot process this request."))
        self.assertEqual(corrector.rejected, 1)

    def test_tolerates_the_edits_a_correction_actually_makes(self) -> None:
        """Punctuation, casing and a fixed word must not trip the check."""
        corrector, result = self.correct(self.reply(
            "Wir hatten heute viele bekannte Namen dabei.",
            "Die man wirklich kennen sollte!",
        ))
        self.assertEqual(corrector.rejected, 0)
        self.assertEqual(len(result), 2)


class UnitAcrossProcessesTest(unittest.TestCase):
    def test_a_unit_that_crosses_a_pickle_is_equal_to_one_made_here(self) -> None:
        """Its hash is a per-process number; restored as pickled it would
        sit in the wrong bucket of every set, equal to nothing."""
        import pickle
        from vocab.entry import Unit
        unit = Unit.lemma("auf")
        back = pickle.loads(pickle.dumps(unit))
        self.assertEqual(back, unit)
        self.assertIn(back, {unit})
        self.assertEqual(hash(back), hash(unit))

