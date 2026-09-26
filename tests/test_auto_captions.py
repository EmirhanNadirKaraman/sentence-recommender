"""The gate that decides whether a machine track is worth catalogueing.

Three tests stand between the ASR and the corpus, and each exists because of
something measured rather than something imagined:

- *punctuation*, because `MergeCorrector` finds sentence boundaries by it, so
  a track without any becomes one enormous sentence that teaches nothing;
- *German*, because a German-teaching channel explains German in English and
  YouTube reports the audio language as `de` either way;
- *length*, because a two-line track is a title card.

Which track is the machine one, and fetching it, is `ingest.captions` and
tested beside it.
"""
from __future__ import annotations

import unittest

from corpus.sentence import RawLine
from ingest.auto_captions import (
    GERMAN, PUNCTUATED, Judgement, Refused, Unfetchable, german_share, judge,
    punctuation_rate,
)

GERMAN_PROSE = [
    "Das ist die vegane Fleischerei in Köln.",
    "Und was soll das? Eine vegane Fleischerei klingt erstmal nicht so sinnig.",
    "Es geht genau darum, dass wir zeigen wollen,",
    "dass man auch dann gut essen kann, wenn man auf tierische Produkte "
    "verzichtet.",
    "Schön, dass du da bist. Komm einfach mit, ich zeige dir das Sprachhaus.",
    "Hier ist unser Wartebereich, da kommen auch die Leute rein.",
]

ENGLISH_PROSE = [
    "Make sure to memorize these pronouns.",
    "Now, let's take a look at the most important accusative reflexive "
    "pronouns.",
    "Sich freuen auf means to look forward to something in the future.",
    "However, offensichtlich can be declined when used as an adjective.",
    "In that sentence, offensichtlich is an adverb and does not change.",
    "Try to remember the difference between these two, it matters a lot.",
]


def lines(texts, repeat: int = 1) -> list[RawLine]:
    """Caption rows, as `ingest.captions.lines` builds them."""
    out = []
    for n, text in enumerate(texts * repeat):
        out.append(RawLine(sentence_id=-(n + 1), video_id="vid",
                           start_time=float(n * 3), duration=3.0,
                           content=text, tokens=()))
    return out


def unpunctuated(texts):
    """The same words as the back catalogue writes them: no stops, no case.

    Not a contrivance. Every lingoni upload before 2026 comes back like this
    — "die blume die blumen die blume riecht gut" — and lowercasing matters
    beyond the gate, because German capitalises its nouns and the parser
    reads that.
    """
    return [t.replace(".", "").replace(",", "").replace("?", "").lower()
            for t in texts]


class PunctuationTest(unittest.TestCase):
    def test_prose_that_ends_its_sentences_passes(self) -> None:
        self.assertGreater(punctuation_rate(lines(GERMAN_PROSE)), PUNCTUATED)

    def test_a_track_with_no_stops_at_all_is_zero(self) -> None:
        self.assertEqual(
            punctuation_rate(lines(unpunctuated(GERMAN_PROSE))), 0.0)

    def test_an_empty_track_does_not_divide_by_zero(self) -> None:
        self.assertEqual(punctuation_rate([]), 0.0)


class GermanShareTest(unittest.TestCase):
    def test_german_prose_reads_as_german(self) -> None:
        self.assertGreater(german_share(lines(GERMAN_PROSE, repeat=4)), GERMAN)

    def test_english_instruction_does_not(self) -> None:
        self.assertLess(german_share(lines(ENGLISH_PROSE, repeat=4)), GERMAN)

    def test_it_reads_the_whole_track_not_the_opening(self) -> None:
        """A video that opens in German and then runs in English is English.

        `get_transcript` detects the language from the first twenty snippets,
        which is exactly what this channel defeats: the presenter greets you
        in German and teaches in English. Detection over windows counts the
        body rather than the greeting.
        """
        mostly_english = lines(GERMAN_PROSE) + lines(ENGLISH_PROSE, repeat=6)
        self.assertLess(german_share(mostly_english), GERMAN)

    def test_it_is_the_same_answer_every_time(self) -> None:
        """langdetect is probabilistic, and the gate seeds it.

        Unseeded, the same track gets different verdicts in different
        processes — a gate over hundreds of videos that nobody can reproduce.
        """
        track = lines(GERMAN_PROSE + ENGLISH_PROSE, repeat=3)
        self.assertEqual({german_share(track) for _ in range(5)},
                         {german_share(track)})


class JudgeTest(unittest.TestCase):
    def test_clean_german_prose_is_kept(self) -> None:
        verdict = judge(lines(GERMAN_PROSE, repeat=6))
        self.assertEqual(verdict.verdict, "ok")
        self.assertTrue(verdict.ok)

    def test_a_track_with_no_punctuation_is_refused(self) -> None:
        verdict = judge(lines(unpunctuated(GERMAN_PROSE), repeat=6))
        self.assertEqual(verdict.verdict, "unpunctuated")
        self.assertFalse(verdict.ok)

    def test_english_instruction_is_refused_though_it_punctuates(self) -> None:
        track = lines(ENGLISH_PROSE, repeat=6)
        self.assertGreater(punctuation_rate(track), PUNCTUATED)
        self.assertEqual(judge(track).verdict, "not-german")

    def test_a_title_card_is_too_short(self) -> None:
        self.assertEqual(judge(lines(GERMAN_PROSE[:2])).verdict, "too-short")

    def test_length_is_tested_before_language(self) -> None:
        """Cheapest first, and the reason is the report rather than the cost.

        A two-line track refused as `not-german` sends someone looking for a
        language problem in a video that simply has no captions worth having.
        """
        self.assertEqual(judge(lines(ENGLISH_PROSE[:1])).verdict, "too-short")

    def test_every_refusal_says_which_test_it_failed(self) -> None:
        for track, expected in ((lines(GERMAN_PROSE[:2]), "too-short"),
                                (lines(unpunctuated(GERMAN_PROSE), repeat=6),
                                 "unpunctuated"),
                                (lines(ENGLISH_PROSE, repeat=6), "not-german")):
            verdict = judge(track)
            self.assertEqual(verdict.verdict, expected)
            self.assertTrue(verdict.why())
            self.assertNotEqual(verdict.why(), expected)

    def test_the_numbers_behind_a_verdict_come_back_with_it(self) -> None:
        verdict = judge(lines(GERMAN_PROSE, repeat=6))
        self.assertEqual(verdict.lines, len(GERMAN_PROSE) * 6)
        self.assertGreater(verdict.punctuation, PUNCTUATED)
        self.assertGreater(verdict.german, GERMAN)


class JudgementTest(unittest.TestCase):
    def test_ok_reports_the_numbers_rather_than_a_complaint(self) -> None:
        said = Judgement("ok", 120, 0.15, 1.0).why()
        self.assertIn("120 lines", said)
        self.assertIn("15%", said)


class OutcomeTest(unittest.TestCase):
    """Which refusals the attempt log may settle on, and which it may not."""

    def test_a_gate_verdict_carries_its_own_name(self) -> None:
        self.assertEqual(Refused("no", "auto-unpunctuated").outcome,
                         "auto-unpunctuated")

    def test_a_failed_fetch_is_recorded_as_unfetchable(self) -> None:
        self.assertEqual(Unfetchable("throttled").outcome, "unfetchable")

    def test_both_are_systemexit_so_the_ingest_path_catches_them(self) -> None:
        for error in (Refused("no", "auto-no-track"), Unfetchable("later")):
            self.assertIsInstance(error, SystemExit)


if __name__ == "__main__":
    unittest.main()
