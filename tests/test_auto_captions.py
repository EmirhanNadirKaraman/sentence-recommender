"""The gate that decides whether a machine track is worth catalogueing.

Three tests stand between the ASR and the corpus, and each exists because of
something measured rather than something imagined:

- *punctuation*, because `MergeCorrector` finds sentence boundaries by it, so
  a track without any becomes one enormous sentence that teaches nothing;
- *German*, because a German-teaching channel explains German in English and
  YouTube reports the audio language as `de` either way;
- *length*, because a two-line track is a title card.

The track-choosing rule is tested too. A bare `de` beside a hundred other
languages is YouTube translating the speech rather than transcribing it, and
admitting one would put machine-translated German in a corpus of things
people actually said.
"""
from __future__ import annotations

import unittest

from corpus.sentence import RawLine
from ingest.auto_captions import (
    GERMAN, LAST_CUE, PUNCTUATED, Judgement, Refused, Throttled, Unfetchable,
    _payload, german_share, judge, punctuation_rate, track_from_info,
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
    """Caption rows, as `track_from_info` would have built them."""
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


def info(autos: dict, audio: str = "de") -> dict:
    """Metadata shaped like yt-dlp's, holding only what the chooser reads."""
    return {"automatic_captions": {
                key: [{"ext": "json3", "url": f"https://example/{key}"}]
                for key in autos},
            "language": audio}


class TrackChoiceTest(unittest.TestCase):
    """Which of YouTube's caption tracks counts as the machine transcript.

    No network: every case here is decided before the URL is fetched, and a
    case that would fetch is asserted on by the exception a fetch raises
    rather than by mocking one.
    """

    def chosen(self, info_: dict) -> str | None:
        """The track key the chooser settles on, without downloading it.

        The opener refuses to answer, so the test reads the choice off the
        URL it was asked for. Nothing here depends on what a caption payload
        looks like — that is the fetch's business, and this is the choice's.
        """
        from unittest import mock                             # noqa: PLC0415

        asked: list[str] = []

        class Opener:
            @staticmethod
            def urlopen(url):
                asked.append(url)
                raise LookupError("the payload is not what is under test")

        # The refusal is retried with a real backoff, and this test is not
        # about the backoff. Left unpatched it slept fifteen seconds per case.
        with mock.patch("time.sleep", lambda _: None):
            with self.assertRaises(Throttled):
                track_from_info(info_, "vid", Opener)
        return asked[0].rsplit("/", 1)[1] if asked else None

    def test_the_original_track_wins_over_a_translation(self) -> None:
        many = {"de-orig", "de", "en", "fr", "es", "it"}
        self.assertEqual(self.chosen(info(many)), "de-orig")

    def test_a_bare_de_is_taken_when_the_audio_is_german(self) -> None:
        self.assertEqual(self.chosen(info({"de"}, audio="de")), "de")

    def test_a_bare_de_among_many_on_english_audio_is_a_translation(self) -> None:
        """The English-taught lessons, which have `de` among 157 languages.

        Their German captions are YouTube translating English speech. Six of
        an even spread of twenty-four lingoni videos are this, and taking
        them would fill the corpus with sentences nobody said.
        """
        many = {"de", "en", "fr", "es", "it", "nl", "pl"}
        track, got = track_from_info(info(many, audio="en"), "vid", None)
        self.assertIsNone(track)
        self.assertIsNone(got)

    def test_no_german_track_at_all_is_nothing(self) -> None:
        track, got = track_from_info(info({"en", "fr"}, audio="en"), "vid",
                                     None)
        self.assertIsNone(track)
        self.assertIsNone(got)


class JudgementTest(unittest.TestCase):
    def test_ok_reports_the_numbers_rather_than_a_complaint(self) -> None:
        said = Judgement("ok", 120, 0.15, 1.0).why()
        self.assertIn("120 lines", said)
        self.assertIn("15%", said)


if __name__ == "__main__":
    unittest.main()


class _Body:
    """What `opener.urlopen(url).read()` gives back."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body


class _Refusal:
    """A request yt-dlp would not complete.

    It raises rather than returning a status, which is why `_payload` has no
    status check: there is nothing to check.
    """

    def read(self):
        raise OSError("HTTP Error 429: Too Many Requests")


class DownloadTest(unittest.TestCase):
    """A throttled caption request is not a bad caption track.

    `requests.get(...).json()` on a 429 raises `JSONDecodeError: Expecting
    value: line 1 column 1` — a message about the parser, not the video. A
    survey at one video every 1.5s drew 429 from this endpoint on the
    forty-seventh, with Google's "Sorry..." page in the body, while yt-dlp's
    own requests were still being answered.
    """

    def fetch(self, responses, slept: list | None = None):
        """Run the download against canned answers, sleeping instantly.

        `slept` collects the backoff intervals. It has to be the caller's own
        list rather than one defaulted with `or`, which was the first version
        and is always false for an empty list — so every interval went into a
        throwaway and the retries looked like they had not happened.
        """
        from unittest import mock                             # noqa: PLC0415

        served = list(responses)
        waited = slept if slept is not None else []

        class Opener:
            @staticmethod
            def urlopen(url):
                answer = served.pop(0)
                if isinstance(answer, Exception):
                    raise answer
                return answer

        with mock.patch("time.sleep", waited.append):
            return _payload("https://example/track", Opener)

    def test_a_good_answer_is_returned(self) -> None:
        self.assertEqual(self.fetch([_Body(b'{"events": []}')]), {"events": []})

    def test_a_429_is_retried_and_then_reported_as_weather(self) -> None:
        slept: list = []
        with self.assertRaises(Throttled) as caught:
            self.fetch([_Refusal()] * 3, slept)
        self.assertIn("says nothing about the video", str(caught.exception))
        self.assertEqual(len(slept), 2)          # tries - 1

    def test_it_recovers_when_the_retry_is_answered(self) -> None:
        got = self.fetch([_Refusal(), _Body(b'{"events": []}')])
        self.assertEqual(got, {"events": []})

    def test_an_answered_request_that_is_not_json_is_also_weather(self) -> None:
        """An interstitial is served with a 200 as readily as with a 429.

        yt-dlp raises on the 429 and returns the interstitial, so a status
        check would catch one and miss the other. Both are weather.
        """
        with self.assertRaises(Throttled):
            self.fetch([_Body(b"<html>Sorry...</html>")] * 3)

    def test_it_is_not_a_systemexit(self) -> None:
        """`caption-check` skips one bad video with `except Exception`.

        `SystemExit` is a `BaseException`, so raising one here would end that
        command on the first throttled video rather than the video.
        """
        self.assertTrue(issubclass(Throttled, Exception))
        self.assertFalse(issubclass(Throttled, SystemExit))


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


class CueLengthTest(unittest.TestCase):
    """A caption line that does not say how long it lasts.

    Manual json3 always says — forty cached tracks, not one missing value —
    and ASR json3 is a different shape and need not. A zero is not a
    cosmetic default: `RawLine.duration` is what `SubtitleAligner` matches
    against, and it reaches `video.duration`, which feeds `watchability` and
    the `i+1/min` column.
    """

    def track(self, events, whole=None):
        payload = {"events": events}
        info = {"automatic_captions": {"de-orig": [{"ext": "json3",
                                                    "url": "https://x/de"}]},
                "language": "de"}
        if whole is not None:
            info["duration"] = whole

        class Opener:
            @staticmethod
            def urlopen(url):
                import json                                   # noqa: PLC0415

                class Body:
                    @staticmethod
                    def read():
                        return json.dumps(payload).encode()
                return Body

        _, lines = track_from_info(info, "vid", Opener)
        return lines

    def event(self, start_ms, text, duration_ms=None):
        out = {"tStartMs": start_ms, "segs": [{"utf8": text}]}
        if duration_ms is not None:
            out["dDurationMs"] = duration_ms
        return out

    def test_a_stated_length_is_used(self) -> None:
        lines = self.track([self.event(0, "eins", 2500),
                            self.event(3000, "zwei", 1500)])
        self.assertEqual([l.duration for l in lines], [2.5, 1.5])

    def test_a_missing_one_runs_to_the_next_line(self) -> None:
        lines = self.track([self.event(0, "eins"),
                            self.event(3000, "zwei", 1500)])
        self.assertEqual(lines[0].duration, 3.0)

    def test_the_last_line_takes_what_is_left_of_the_video(self) -> None:
        lines = self.track([self.event(0, "eins", 1000),
                            self.event(5000, "zwei")], whole=8.0)
        self.assertEqual(lines[1].duration, 3.0)

    def test_with_no_video_length_the_last_line_still_has_one(self) -> None:
        """Zero would give the final sentence a zero-length span."""
        lines = self.track([self.event(0, "eins", 1000),
                            self.event(5000, "zwei")])
        self.assertEqual(lines[1].duration, LAST_CUE)

    def test_no_line_ever_lasts_no_time(self) -> None:
        lines = self.track([self.event(0, "eins"), self.event(2000, "zwei"),
                            self.event(4000, "drei")], whole=6.0)
        for line in lines:
            self.assertGreater(line.duration, 0.0)

    def test_empty_events_are_skipped_without_shifting_the_rest(self) -> None:
        """A blank event must not become the neighbour a length is read from."""
        lines = self.track([self.event(0, "eins"),
                            {"tStartMs": 1000, "segs": [{"utf8": "  "}]},
                            self.event(3000, "zwei", 1000)])
        self.assertEqual([l.content for l in lines], ["eins", "zwei"])
        self.assertEqual(lines[0].duration, 3.0)
