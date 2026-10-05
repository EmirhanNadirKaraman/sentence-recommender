"""English as a language to learn: its units, its filter, its word lists.

The analyser tests load `en_core_web_md`, the way the German ones load the
German model -- a phrasal verb is found on the parse, and a parse is the
thing that has to be right.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from languages import ENGLISH, GERMAN
from tests import pg
from vocab.aliases import Aliases, heads
from vocab.entry import Unit
from vocab.goal_list import GoalList
from vocab.loader import ARTICLES, WordListLoader


def _analyzer():
    from corpus.english import EnglishAnalyzer
    from vocab.expressions import canonicals
    return EnglishAnalyzer(frozenset(canonicals(ENGLISH.expressions)))


class EnglishUnitsTest(unittest.TestCase):
    analyzer = None

    @classmethod
    def setUpClass(cls) -> None:
        try:
            import en_core_web_md  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("en_core_web_md is not installed")
        cls.analyzer = _analyzer()

    def units(self, text: str) -> set[str]:
        from corpus.sentence import Sentence
        (sentence,) = self.analyzer.analyze_all([Sentence(text)])
        return {f"{u.kind}:{u.key}" for u in sentence.units}

    def test_a_phrasal_verb_is_one_unit_and_not_its_halves(self) -> None:
        found = self.units("She gave up smoking last year.")
        self.assertIn("pattern:give up", found)
        self.assertNotIn("lemma:give", found)
        self.assertNotIn("lemma:up", found)

    def test_a_phrasal_verb_split_by_its_object_is_still_found(self) -> None:
        self.assertIn("pattern:give up", self.units("He finally gave it up."))
        self.assertIn("pattern:put off", self.units("He put the meeting off."))

    def test_a_preposition_leading_a_phrase_is_not_a_particle(self) -> None:
        found = self.units("Tom went to London on Monday.")
        self.assertNotIn("pattern:go on", found)
        self.assertIn("lemma:go", found)
        self.assertIn("pattern:go on", self.units("The show must go on."))

    def test_a_verb_and_its_preposition_with_an_object(self) -> None:
        self.assertIn("pattern:depend on", self.units("It depends on the weather."))
        self.assertIn("pattern:look after", self.units("Can you look after my dog?"))

    def test_the_longest_expression_wins(self) -> None:
        found = self.units("She looks up to her older sister.")
        self.assertIn("pattern:look up to", found)
        self.assertNotIn("pattern:look up", found)

    def test_fixed_phrases_in_a_row(self) -> None:
        found = self.units("In spite of the rain, the match took place.")
        self.assertIn("pattern:in spite of", found)
        self.assertIn("pattern:take place", found)

    def test_names_and_numbers_are_free(self) -> None:
        found = self.units("Tom and Mary bought 3 books in London.")
        self.assertFalse({"lemma:tom", "lemma:mary", "lemma:london",
                          "lemma:3"} & found)
        self.assertIn("lemma:book", found)

    def test_contractions_are_the_words_they_stand_for(self) -> None:
        found = self.units("I'm not sure he'll come, but we've tried.")
        self.assertTrue({"lemma:be", "lemma:not", "lemma:will",
                         "lemma:have", "lemma:i"} <= found)

    def test_a_possessive_is_not_a_word(self) -> None:
        self.assertNotIn("lemma:'s", self.units("It is the teacher's book."))

    def test_fillers_are_not_words(self) -> None:
        self.assertNotIn("lemma:uh", self.units("Uh, I think it is fine."))

    def test_the_lemmas_spacy_gets_wrong_are_put_right(self) -> None:
        found = self.units("We need more data on this species.")
        self.assertIn("lemma:data", found)
        self.assertIn("lemma:species", found)

    def test_a_word_list_entry_meets_the_corpus_lemma(self) -> None:
        self.assertEqual(
            self.analyzer.lemmatise_each(["data", "to abandon", "species",
                                          "", "abundant"]),
            ["data", "abandon", "species", "", "abundant"])

    def test_a_word_said_mostly_as_a_name_is_dropped_everywhere(self) -> None:
        from corpus.sentence import Sentence
        texts = ["Paris is lovely in spring."] * 3 + ["The paris was here."]
        analysed = self.analyzer.analyze_all([Sentence(t) for t in texts])
        self.assertFalse(any(Unit.lemma("paris") in s.units for s in analysed))


class ExpressionFileTest(unittest.TestCase):
    def test_every_line_parses(self) -> None:
        from corpus.english import Expression
        lines = [line for line in ENGLISH.expressions.read_text(
                     encoding="utf-8").splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        self.assertGreater(len(lines), 100)
        for line in lines:
            with self.subTest(line=line):
                self.assertIsNotNone(Expression.parse(line))

    def test_a_slot_marks_the_word_before_it_as_leading_a_phrase(self) -> None:
        from corpus.english import Expression
        found = Expression.parse("look forward to\tlook :: forward to sth")
        self.assertEqual(found.leads, (False, True))
        self.assertEqual(found.verb, frozenset({"look"}))

    def test_slots_at_the_ends_of_a_bare_canonical_are_dropped(self) -> None:
        from corpus.english import Expression
        found = Expression.parse("take sth into account")
        self.assertEqual(found.steps, (frozenset({"take"}), None,
                                       frozenset({"into"}),
                                       frozenset({"account"})))


class EnglishFilterTest(unittest.TestCase):
    def test_an_english_sentence_is_kept_and_a_german_one_refused(self) -> None:
        from corpus.english import EnglishFilter
        from corpus.sentence import Sentence
        kept, dropped = EnglishFilter(4, 25).split([
            Sentence("I think we should go home now."),
            Sentence("Ich glaube, wir sollten jetzt nach Hause gehen."),
        ])
        self.assertEqual([s.text for s in kept],
                         ["I think we should go home now."])
        self.assertEqual(len(dropped), 1)


class EnglishListsTest(unittest.TestCase):
    def test_german_markers_are_what_the_loader_reads(self) -> None:
        self.assertEqual(GERMAN.markers, ARTICLES)

    def test_an_english_list_strips_its_own_markers_not_german_ones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "words.txt"
            path.write_text("to abandon\nthe internet\ndie out\n", encoding="utf-8")
            surfaces = WordListLoader(ENGLISH.markers).load(path).surfaces
        self.assertEqual(surfaces, ("abandon", "internet", "die out"))

    def test_a_goal_list_keeps_an_english_entry_whole(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "list.txt"
            path.write_text("die out\nto abandon\n", encoding="utf-8")
            units = GoalList(path, markers=ENGLISH.markers).units(frozenset())
        self.assertEqual([u.key for u in units], ["die out", "abandon"])

    def test_an_english_phrasal_verb_names_no_bare_verb(self) -> None:
        self.assertEqual(heads("give up", "en"), set())
        self.assertEqual(heads("look forward to sth", "en"), set())
        self.assertEqual(heads("to abandon", "en"), {"abandon"})
        self.assertEqual(heads("die", "en"), {"die"})
        aliases = Aliases([Unit.pattern("give up"), Unit.lemma("die")], "en")
        self.assertEqual(aliases.of(Unit.lemma("give")), Unit.lemma("give"))
        self.assertEqual(aliases.of(Unit.lemma("die")), Unit.lemma("die"))

    def test_german_keeps_its_own_reading(self) -> None:
        self.assertEqual(heads("die Schule"), {"Schule"})
        self.assertEqual(heads("für jdn./etw. sorgen"), {"sorgen"})


class TranslatedSubtitlesTest(unittest.TestCase):
    """English subtitles over speech in another language are a translation.

    German channels often carry a hand-written English track for their
    viewers abroad. It reads as English and is not English anybody said,
    and nothing downstream could tell -- so it is refused at the door, from
    the language YouTube's own speech recognition filed its track under.
    """

    def add(self, tracks, language: str = "en", **kwargs):
        from unittest import mock
        from config import Settings
        from ingest.video import VideoIngestor
        from readers import Reader
        from tests.test_captions import _Pipeline, spoken, track_list

        with tempfile.TemporaryDirectory() as home:
            settings = Settings.for_reader(Reader("r", Path(home), language))
            ingestor = VideoIngestor(settings, None)
            ingestor._pipeline = _Pipeline()
            read: list[str] = []

            def payload(url, agent, http=None):
                read.append(url)
                return spoken(30, "This is a sentence.")

            with mock.patch("ingest.video.list_tracks",
                            lambda _video: track_list(tracks)), \
                    mock.patch("ingest.captions._payload", payload):
                try:
                    ingestor.add("vid", **kwargs)
                except SystemExit as refused:
                    return refused, read
        self.fail("add wrote to the catalogue")

    def test_english_over_german_speech_is_refused_unread(self) -> None:
        from ingest.attempts import SETTLED
        refused, read = self.add([(".en", "en", None), ("a.de", "de", "asr")])
        self.assertEqual(read, [])
        self.assertEqual(refused.outcome, "translated")
        self.assertIn("translation", str(refused))
        self.assertIn(refused.outcome, SETTLED)

    def test_english_over_english_speech_is_read(self) -> None:
        refused, read = self.add([(".en", "en", None), ("a.en", "en", "asr")],
                                 wanted=("zebra",))
        self.assertEqual(read, ["https://yt.test/.en"])
        self.assertIn("off target", str(refused))

    def test_no_machine_track_says_nothing_either_way(self) -> None:
        refused, read = self.add([(".en-GB", "en-GB", None)], wanted=("zebra",))
        self.assertEqual(read, ["https://yt.test/.en-GB"])

    def test_german_keeps_what_it_always_took(self) -> None:
        refused, read = self.add([(".de", "de", None), ("a.en", "en", "asr")],
                                 language="de", wanted=("Zebra",))
        self.assertEqual(read, ["https://yt.test/.de"])
        self.assertIn("off target", str(refused))


class LanguageFlagTest(unittest.TestCase):
    def test_a_language_other_than_the_readers_is_refused(self) -> None:
        from types import SimpleNamespace
        from config import Settings
        from main import _same_language
        from readers import Registry
        with tempfile.TemporaryDirectory() as tmp:
            registry = Registry(pg.schema(self, "accounts"),
                                homes=Path(tmp) / "readers")
            with self.assertRaises(SystemExit) as refused:
                _same_language(SimpleNamespace(command="add-channel",
                                               language="en"),
                               Settings(), registry)
        self.assertIn("learns de, not en", str(refused.exception))
        _same_language(SimpleNamespace(command="add-channel", language="de"),
                       Settings())
        _same_language(SimpleNamespace(command="add-channel", language=None),
                       Settings())


class PrivateFunctionWordsTest(unittest.TestCase):
    def test_a_new_reader_strikes_words_from_their_own_copy(self) -> None:
        from config import Settings
        from readers import Registry
        with tempfile.TemporaryDirectory() as tmp:
            registry = Registry(pg.schema(self, "accounts"), homes=Path(tmp) / "readers")
            reader = registry.add("ahmet", "en", "tr")
            settings = Settings.for_reader(reader)
            self.assertEqual(settings.function_words,
                             reader.home / "function_words.txt")
            self.assertEqual(settings.function_words.read_bytes(),
                             ENGLISH.function_words.read_bytes())

    def test_a_new_english_reader_starts_knowing_the_starter_words(self) -> None:
        from config import Settings
        from readers import Registry
        with tempfile.TemporaryDirectory() as tmp:
            reader = Registry(pg.schema(self, "accounts"), homes=Path(tmp) / "readers").add("ahmet", "en", "tr")
            known = Settings.for_reader(reader).known_words
            self.assertEqual(known, reader.home / "known_words.txt")
            self.assertEqual(known.read_bytes(),
                             ENGLISH.starter_words.read_bytes())

    def test_a_german_reader_gets_no_starter_list(self) -> None:
        from readers import Registry
        with tempfile.TemporaryDirectory() as tmp:
            reader = Registry(pg.schema(self, "accounts"), homes=Path(tmp) / "readers").add("max", "de", "en")
            self.assertFalse((reader.home / "known_words.txt").exists())


class StarterWordsTest(unittest.TestCase):
    """The list a new English reader is assumed to know."""

    def setUp(self) -> None:
        loader = WordListLoader(ENGLISH.markers)
        self.starters = loader.load(ENGLISH.starter_words).surfaces
        self.function = set(loader.load(ENGLISH.function_words).surfaces)

    def test_a_thousand_words_none_of_them_a_function_word(self) -> None:
        self.assertEqual(len(self.starters), 1000)
        self.assertEqual(len(set(self.starters)), 1000)
        self.assertFalse(self.function & set(self.starters))

    def test_the_commonest_words_come_first(self) -> None:
        self.assertEqual(self.starters[:5], ("say", "go", "know", "get", "think"))

    def test_it_says_where_it_came_from_and_under_what_licence(self) -> None:
        text = ENGLISH.starter_words.read_text(encoding="utf-8")
        self.assertIn("New General Service List", text)
        self.assertIn("Attribution-ShareAlike 4.0", text)


class FingerprintTest(unittest.TestCase):
    def test_each_language_is_fingerprinted_on_its_own_rules(self) -> None:
        from fingerprint import ENGLISH_SOURCES, SOURCES, analyser_fingerprint
        self.assertNotEqual(analyser_fingerprint("de"), analyser_fingerprint("en"))
        self.assertEqual(analyser_fingerprint(), analyser_fingerprint("de"))
        self.assertIn(ENGLISH.expressions, ENGLISH_SOURCES)
        self.assertNotIn(ENGLISH.expressions, SOURCES)


if __name__ == "__main__":
    unittest.main()
