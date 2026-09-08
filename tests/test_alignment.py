"""Putting corrected sentences back on the video's clock.

Line-level provenance is not enough for an overlay: a subtitle row routinely
holds the end of one sentence and the start of the next, so two sentences
would claim the same cue. Alignment therefore works word by word.
"""
from __future__ import annotations

import unittest

from alignment import SubtitleAligner, Timing, WebVTTWriter
from corpus.sentence import RawLine, Sentence


def line(sentence_id: int, content: str, start: float, duration: float) -> RawLine:
    return RawLine(sentence_id=sentence_id, video_id="vid", start_time=start,
                   duration=duration, content=content, tokens=tuple(content.split()))


class SubtitleAlignerTest(unittest.TestCase):
    def setUp(self) -> None:
        # Two rows; the second holds the tail of one sentence and the head of
        # the next — the shape that makes row-level timing unusable.
        self.lines = [
            line(1, "Wir haben heute Namen dabei,", start=0.0, duration=4.0),
            line(2, "die man kennen sollte. Ich habe sie mir", start=4.0, duration=6.0),
        ]

    def align(self, *texts: str) -> list[Sentence]:
        return SubtitleAligner().align(
            self.lines, [Sentence(text=t) for t in texts]
        )

    def test_two_sentences_sharing_a_row_do_not_share_its_cue(self) -> None:
        first, second = self.align(
            "Wir haben heute Namen dabei, die man kennen sollte.",
            "Ich habe sie mir.",
        )
        self.assertLess(first.timing.end, second.timing.end)
        self.assertGreater(second.timing.start, self.lines[1].start_time)
        self.assertLessEqual(second.timing.end, 10.0)

    def test_timing_stays_inside_the_original_span(self) -> None:
        for sentence in self.align("Wir haben heute Namen dabei.",
                                   "Ich habe sie mir."):
            self.assertGreaterEqual(sentence.timing.start, 0.0)
            self.assertLessEqual(sentence.timing.end, 10.0)
            self.assertLess(sentence.timing.start, sentence.timing.end)

    def test_survives_the_words_the_model_changed(self) -> None:
        """Correction rewrites words; the surviving ones still anchor it."""
        aligned = self.align("Wir hatten heute viele Namen dabei!")
        self.assertIsNotNone(aligned[0].timing)
        self.assertLess(aligned[0].timing.start, 4.0)

    def test_falls_back_to_declared_rows_when_nothing_matches(self) -> None:
        sentence = Sentence(text="Völlig anderer Text.", source_ids=(2,))
        aligned = SubtitleAligner().align(self.lines, [sentence])
        self.assertEqual(aligned[0].timing.start, 4.0)
        self.assertEqual(aligned[0].timing.end, 10.0)

    def test_no_timing_when_there_is_nothing_to_go_on(self) -> None:
        aligned = SubtitleAligner().align(self.lines, [Sentence(text="Xyz qqq.")])
        self.assertIsNone(aligned[0].timing)

    def test_empty_input_is_not_an_error(self) -> None:
        self.assertEqual(SubtitleAligner().align([], []), [])


class TimingTest(unittest.TestCase):
    def test_formats_a_webvtt_cue(self) -> None:
        self.assertEqual(
            Timing("v", 3661.5, 3662.25).cue(),
            "01:01:01.500 --> 01:01:02.250",
        )

    def test_sub_second_precision_survives(self) -> None:
        self.assertEqual(Timing("v", 0.32, 6.44).cue(),
                         "00:00:00.320 --> 00:00:06.440")


class WebVTTWriterTest(unittest.TestCase):
    def timed(self, text: str, start: float, end: float) -> Sentence:
        return Sentence(text=text).with_timing(Timing("vid", start, end))

    def test_writes_cues_in_playback_order(self) -> None:
        output = WebVTTWriter().render([
            self.timed("Zweiter.", 5.0, 7.0), self.timed("Erster.", 1.0, 3.0),
        ])
        self.assertTrue(output.startswith("WEBVTT"))
        self.assertLess(output.index("Erster."), output.index("Zweiter."))
        self.assertIn("00:00:01.000 --> 00:00:03.000", output)

    def test_skips_untimed_sentences_rather_than_guessing(self) -> None:
        writer = WebVTTWriter()
        output = writer.render([self.timed("Da.", 1.0, 2.0), Sentence(text="Ohne Zeit.")])
        self.assertNotIn("Ohne Zeit.", output)
        self.assertEqual(writer.skipped, 1)

    def test_trims_overlapping_cues(self) -> None:
        output = WebVTTWriter().render([
            self.timed("Erster.", 1.0, 5.0), self.timed("Zweiter.", 3.0, 7.0),
        ])
        self.assertIn("00:00:05.000 --> 00:00:07.000", output)

    def test_drops_a_cue_wholly_covered_by_the_previous_one(self) -> None:
        output = WebVTTWriter().render([
            self.timed("Erster.", 1.0, 9.0), self.timed("Verschluckt.", 3.0, 5.0),
        ])
        self.assertNotIn("Verschluckt.", output)

    def test_can_carry_the_translation(self) -> None:
        sentence = Sentence(text="Da.", translation="There.").with_timing(
            Timing("vid", 1.0, 2.0)
        )
        self.assertIn("There.", WebVTTWriter(include_translation=True).render([sentence]))


if __name__ == "__main__":
    unittest.main()


class ContextSentenceTest(unittest.TestCase):
    """Sentences the learning filter drops are still part of the overlay."""

    def test_a_context_sentence_is_marked_not_teachable(self) -> None:
        sentence = Sentence(text="Zu lang für den Kurs.").as_context()
        self.assertFalse(sentence.teachable)
        self.assertTrue(Sentence(text="Normal.").teachable)

    def test_the_filter_hands_back_both_halves(self) -> None:
        from corpus import SentenceFilter
        kept, dropped = SentenceFilter(4, 6).split([
            Sentence(text="Das ist ein guter Satz."),
            Sentence(text="Kurz."),
        ])
        self.assertEqual([s.text for s in kept], ["Das ist ein guter Satz."])
        self.assertEqual([s.text for s in dropped], ["Kurz."])

    def test_context_sentences_close_the_gaps_in_an_export(self) -> None:
        cues = WebVTTWriter().render([
            Sentence(text="Erster.").with_timing(Timing("v", 0.0, 2.0)),
            Sentence(text="Ausgefiltert.").with_timing(Timing("v", 2.0, 4.0)).as_context(),
            Sentence(text="Dritter.").with_timing(Timing("v", 4.0, 6.0)),
        ])
        self.assertIn("Ausgefiltert.", cues)
