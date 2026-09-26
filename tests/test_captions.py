"""The caption transport, and the choice of track it leaves to its callers.

The transport is youtube-caption-extractor's, and its choice of track is
the part that was not taken: asked for German, it reads `a.de` — the
machine track — before a hand-written track filed under `de-DE`, and falls
back to the first track in any language. Measured on eS0hOVaiYY4, which is
catalogued on its hand-written `de-DE`: the library returned "hallo leute
ich bin daniel neuer", lowercase and unpunctuated. The fixtures below are
the track lists the player actually gave, with the URLs made up — real ones
are signed, and carry the address that asked.

No network. `http` answers for YouTube, and every refusal the endpoint is
known to give — a 429, a bot check, an interstitial served with a 200, an
empty body — is one of its answers.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

import requests

from config import Settings
from ingest.attempts import AUTO_SETTLED, SETTLED, AttemptLog
from ingest.auto_captions import Refused, Unfetchable
from ingest.captions import (
    CLIENTS, DOWNLOAD_TRIES, LAST_CUE, Throttled, Track, Tracks, _payload,
    lines, list_tracks, snippets,
)
from ingest.video import MIN_LINES, VideoIngestor

# eS0hOVaiYY4's list as the iOS client gave it, in its order: hand-written
# translations, the machine track, and the German someone typed.
LIKE_GERMANS = [
    (".sq", "sq", None), (".ar", "ar", None), (".en", "en", None),
    (".fr", "fr", None), ("a.de", "de", "asr"), (".de-DE", "de-DE", None),
    (".el", "el", None),
]
# w_dwDAC_nXE: MrWissen2go with nothing typed, only speech recognition.
MACHINE_ONLY = [("a.de", "de", "asr")]
# English speech with hand-written English and French.
ENGLISH = [(".en", "en", None), (".fr", "fr", None), ("a.en", "en", "asr")]


def player(tracks, status: str = "OK", reason: str = "",
           length: str = "658") -> dict:
    """A player answer, holding only what the transport reads."""
    answer = {"playabilityStatus": {"status": status},
              "videoDetails": {"title": "Markus, wach auf!",
                               "lengthSeconds": length}}
    if reason:
        answer["playabilityStatus"]["reason"] = reason
    if tracks:
        answer["captions"] = {"playerCaptionsTracklistRenderer": {
            "captionTracks": [
                {"baseUrl": f"https://yt.test/timedtext?v=vid&lang={code}"
                            + (f"&kind={kind}" if kind else "") + "&fmt=srv3",
                 "vssId": vss, "languageCode": code,
                 **({"kind": kind} if kind else {})}
                for vss, code, kind in tracks]}}
    return answer


def track_list(tracks, length: float | None = 658.0) -> Tracks:
    return Tracks(video_id="vid", length=length, tracks=tuple(
        Track(language=code, machine=kind == "asr", label=vss,
              url=f"https://yt.test/{vss}")
        for vss, code, kind in tracks))


class Answer:
    """What `requests` hands back, as far as the transport looks."""

    def __init__(self, body=None, status: int = 200, text: str | None = None):
        self.status_code = status
        self.text = text if text is not None else json.dumps(body)

    def json(self):
        return json.loads(self.text)


class YouTube:
    """Answers each request with the next canned answer, and keeps a log."""

    def __init__(self, posts=(), gets=()) -> None:
        self.posts, self.gets = list(posts), list(gets)
        self.asked: list[tuple[str, str, dict, dict | None]] = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.asked.append(("post", url, headers, json))
        return self._next(self.posts)

    def get(self, url, headers=None, timeout=None):
        self.asked.append(("get", url, headers, None))
        return self._next(self.gets)

    @staticmethod
    def _next(queue):
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class TrackChoiceTest(unittest.TestCase):
    """Which track counts as the German, and which never does."""

    def test_the_hand_written_track_beats_the_machine_one(self) -> None:
        """The library's mistake on this exact list. `a.de` is an exact
        code match and `de-DE` is not, and exactness is not the question —
        who wrote it is."""
        offered = track_list(LIKE_GERMANS)
        self.assertEqual(offered.manual("de").label, ".de-DE")
        self.assertEqual(offered.machine("de").label, "a.de")

    def test_the_plain_code_is_preferred_to_a_regional_one(self) -> None:
        """language-app's order, `de` before `de-DE` before `de-AT`, so what
        counts as German did not move when the fetch did."""
        offered = track_list([(".de-AT", "de-AT", None), (".de", "de", None)])
        self.assertEqual(offered.manual("de").label, ".de")

    def test_a_video_with_no_german_offers_nothing_in_its_place(self) -> None:
        """The library falls back to `tracks[0]`. Nothing downstream of
        `add` checks the language again, so English would be catalogued as
        German and taught."""
        offered = track_list(ENGLISH)
        self.assertIsNone(offered.manual("de"))
        self.assertIsNone(offered.machine("de"))

    def test_a_machine_track_alone_is_not_a_hand_written_one(self) -> None:
        offered = track_list(MACHINE_ONLY)
        self.assertIsNone(offered.manual("de"))
        self.assertEqual(offered.machine("de").label, "a.de")

    def test_a_prefix_is_a_region_not_a_longer_code(self) -> None:
        """`de-` and not `de`: a language whose code begins with the same
        letters is another language."""
        offered = track_list([(".dem", "dem", None)])
        self.assertIsNone(offered.manual("de"))

    def test_the_languages_someone_wrote_in(self) -> None:
        self.assertEqual(track_list(ENGLISH).hand_written(), ["en", "fr"])
        self.assertEqual(track_list(MACHINE_ONLY).hand_written(), [])


class ListTracksTest(unittest.TestCase):
    def test_the_first_client_with_tracks_is_the_answer(self) -> None:
        youtube = YouTube(posts=[Answer(player(LIKE_GERMANS))])
        offered = list_tracks("eS0hOVaiYY4", youtube)
        self.assertEqual(len(youtube.asked), 1)
        self.assertEqual(offered.manual("de").language, "de-DE")
        self.assertEqual(offered.length, 658.0)
        self.assertEqual(offered.title, "Markus, wach auf!")

    def test_it_asks_as_the_client_it_claims_to_be(self) -> None:
        youtube = YouTube(posts=[Answer(player(MACHINE_ONLY))])
        list_tracks("w_dwDAC_nXE", youtube)
        _, _, headers, body = youtube.asked[0]
        self.assertEqual(body["videoId"], "w_dwDAC_nXE")
        self.assertEqual(body["context"]["client"]["clientName"], "IOS")
        self.assertEqual(headers["User-Agent"], CLIENTS[0].agent)
        self.assertEqual(headers["X-YouTube-Client-Name"], CLIENTS[0].header)

    def test_the_track_is_fetched_as_the_client_that_listed_it(self) -> None:
        """A URL issued to one app and fetched as another is the mismatch
        that drew a 429 on the forty-seventh video of a survey."""
        youtube = YouTube(posts=[Answer(status=429), Answer(player(ENGLISH))])
        offered = list_tracks("vid", youtube)
        self.assertEqual(offered.agent, CLIENTS[1].agent)

    def test_none_is_only_believed_once_every_client_is_asked(self) -> None:
        """W6iihWRahKg, as it answered: the iOS client plays it and lists
        nothing, the other two refuse. No captions is what yt-dlp found
        too — so the first answer that played is the verdict."""
        youtube = YouTube(posts=[
            Answer(player([])),
            Answer(player([], "LOGIN_REQUIRED",
                          "Sign in to confirm you’re not a bot")),
            Answer(player([], "UNPLAYABLE", "The page needs to be reloaded.")),
        ])
        offered = list_tracks("W6iihWRahKg", youtube)
        self.assertEqual(len(youtube.asked), 3)
        self.assertEqual(offered.tracks, ())

    def test_a_later_client_with_tracks_beats_an_earlier_one_without(self) -> None:
        youtube = YouTube(posts=[Answer(player([])),
                                 Answer(player(LIKE_GERMANS))])
        self.assertEqual(list_tracks("vid", youtube).manual("de").label,
                         ".de-DE")

    def test_every_client_refused_is_weather(self) -> None:
        """And said without the reason beside it. "This video is
        unavailable" is what the player tells an outdated client about a
        good video, and `classify` would settle that sentence forever."""
        youtube = YouTube(posts=[
            Answer(player([], "ERROR", "This video is unavailable"))] * 3)
        with self.assertRaises(Throttled) as caught:
            list_tracks("vid", youtube)
        said = f"Throttled: {caught.exception}"
        self.assertNotIn("unavailable", said.lower())
        self.assertNotIn(AttemptLog.classify(said), SETTLED)
        self.assertNotIn(AttemptLog.classify(said), AUTO_SETTLED)
        self.assertIn("ios ERROR", said)

    def test_a_429_says_429_so_a_run_can_stop_on_it(self) -> None:
        """`add-videos` stops after five in a row, and it counts them by
        reading "429" in the exception."""
        youtube = YouTube(posts=[Answer(status=429)] * 3)
        with self.assertRaises(Throttled) as caught:
            list_tracks("vid", youtube)
        self.assertEqual(
            AttemptLog.classify(f"Throttled: {caught.exception}"), "throttled")

    def test_a_connection_that_fails_is_a_refusal_like_any_other(self) -> None:
        youtube = YouTube(posts=[requests.ConnectionError("reset"),
                                 Answer(text="<html>Sorry...</html>"),
                                 Answer(["not", "an", "answer"])])
        with self.assertRaises(Throttled) as caught:
            list_tracks("vid", youtube)
        self.assertIn("ConnectionError", str(caught.exception))
        self.assertIn("not JSON", str(caught.exception))


class DownloadTest(unittest.TestCase):
    """A throttled caption request is not a bad caption track.

    Parsing a 429's "Sorry..." page as JSON raises `JSONDecodeError:
    Expecting value: line 1 column 1` — a message about the parser, not the
    video. A survey at one video every 1.5s drew 429 from this endpoint on
    the forty-seventh.
    """

    def fetch(self, answers, slept: list | None = None):
        """Run the download against canned answers, sleeping instantly.

        `slept` has to be the caller's own list rather than one defaulted
        with `or`, which is always false for an empty list — so every
        interval went into a throwaway and the retries looked like they had
        not happened.
        """
        youtube = YouTube(gets=answers)
        waited = slept if slept is not None else []
        with mock.patch("time.sleep", waited.append):
            return _payload("https://yt.test/t?lang=de&fmt=srv3", "agent",
                            youtube), youtube

    def test_a_good_answer_is_returned_as_json3(self) -> None:
        got, youtube = self.fetch([Answer({"events": []})])
        self.assertEqual(got, {"events": []})
        url = youtube.asked[0][1]
        self.assertTrue(url.endswith("&fmt=json3"))
        self.assertNotIn("srv3", url)

    def test_a_429_is_retried_and_then_reported_as_weather(self) -> None:
        slept: list = []
        with self.assertRaises(Throttled) as caught:
            self.fetch([Answer(status=429)] * DOWNLOAD_TRIES, slept)
        self.assertIn("says nothing about the video", str(caught.exception))
        self.assertEqual(len(slept), DOWNLOAD_TRIES - 1)
        self.assertEqual(
            AttemptLog.classify(f"Throttled: {caught.exception}"), "throttled")

    def test_it_recovers_when_the_retry_is_answered(self) -> None:
        got, _ = self.fetch([Answer(status=429), Answer({"events": []})])
        self.assertEqual(got, {"events": []})

    def test_an_interstitial_with_a_200_is_also_weather(self) -> None:
        """An interstitial is served with a 200 as readily as with a 429."""
        with self.assertRaises(Throttled) as caught:
            self.fetch([Answer(text="<html>Sorry...</html>")] * DOWNLOAD_TRIES)
        said = f"Throttled: {caught.exception}"
        self.assertEqual(AttemptLog.classify(said), "unfetchable")

    def test_an_empty_answer_is_weather_and_not_an_empty_track(self) -> None:
        """What the endpoint gives a URL it will not serve. A track that
        parses and holds nothing is a different answer, and a verdict."""
        with self.assertRaises(Throttled):
            self.fetch([Answer(text="")] * DOWNLOAD_TRIES)

    def test_json_that_is_not_a_track_is_weather(self) -> None:
        with self.assertRaises(Throttled):
            self.fetch([Answer([1, 2, 3])] * DOWNLOAD_TRIES)

    def test_it_is_not_a_systemexit(self) -> None:
        """`caption-check` skips one bad video with `except Exception`.

        `SystemExit` is a `BaseException`, so raising one here would end that
        command on the first throttled video rather than the video.
        """
        self.assertTrue(issubclass(Throttled, Exception))
        self.assertFalse(issubclass(Throttled, SystemExit))


def event(start_ms, text, duration_ms=None):
    out = {"tStartMs": start_ms, "segs": [{"utf8": text}]}
    if duration_ms is not None:
        out["dDurationMs"] = duration_ms
    return out


class LinesTest(unittest.TestCase):
    """json3 as caption lines, parsed the way language-app always has.

    Measured, not assumed: thirty catalogued videos fetched this way came
    back identical to language-app's cached tracks in text, start and
    duration, line for line.
    """

    def test_segments_are_joined_and_nothing_else_is_done_to_them(self) -> None:
        """The library strips tags and decodes entities; language-app never
        did, and the 2,889 videos in the catalogue were parsed by it."""
        got = lines({"events": [{"tStartMs": 0, "dDurationMs": 1000,
                                 "segs": [{"utf8": " Hallo, "},
                                          {"utf8": "<Musik> & Co. "}]}]},
                    "vid")
        self.assertEqual(got[0].content, "Hallo, <Musik> & Co.")

    def test_snippets_are_what_populate_writes(self) -> None:
        got = snippets(lines({"events": [event(1500, "Hallo", 2000)]}, "vid"))
        self.assertEqual(got, [{"text": "Hallo", "start": 1.5,
                                "duration": 2.0}])


class CueLengthTest(unittest.TestCase):
    """A caption line that does not say how long it lasts.

    Manual json3 always says — forty cached tracks, not one missing value —
    and ASR json3 is a different shape and need not. A zero is not a
    cosmetic default: `RawLine.duration` is what `SubtitleAligner` matches
    against, and it reaches `video.duration`, which feeds `watchability` and
    the `i+1/min` column.
    """

    def track(self, events, whole=None):
        return lines({"events": events}, "vid", whole)

    def test_a_stated_length_is_used(self) -> None:
        got = self.track([event(0, "eins", 2500), event(3000, "zwei", 1500)])
        self.assertEqual([line.duration for line in got], [2.5, 1.5])

    def test_a_missing_one_runs_to_the_next_line(self) -> None:
        got = self.track([event(0, "eins"), event(3000, "zwei", 1500)])
        self.assertEqual(got[0].duration, 3.0)

    def test_the_last_line_takes_what_is_left_of_the_video(self) -> None:
        got = self.track([event(0, "eins", 1000), event(5000, "zwei")],
                         whole=8.0)
        self.assertEqual(got[1].duration, 3.0)

    def test_with_no_video_length_the_last_line_still_has_one(self) -> None:
        """Zero would give the final sentence a zero-length span."""
        got = self.track([event(0, "eins", 1000), event(5000, "zwei")])
        self.assertEqual(got[1].duration, LAST_CUE)

    def test_no_line_ever_lasts_no_time(self) -> None:
        got = self.track([event(0, "eins"), event(2000, "zwei"),
                          event(4000, "drei")], whole=6.0)
        for line in got:
            self.assertGreater(line.duration, 0.0)

    def test_empty_events_are_skipped_without_shifting_the_rest(self) -> None:
        """A blank event must not become the neighbour a length is read from."""
        got = self.track([event(0, "eins"),
                          {"tStartMs": 1000, "segs": [{"utf8": "  "}]},
                          event(3000, "zwei", 1000)])
        self.assertEqual([line.content for line in got], ["eins", "zwei"])
        self.assertEqual(got[0].duration, 3.0)


class _Pipeline:
    """language-app's scraper, as far as `add` reaches before writing."""

    @staticmethod
    def fetch_video_metadata(video_id):
        return {"title": "Markus, wach auf!", "thumbnail_url": "",
                "channel_id": "", "channel_name": ""}


def spoken(count: int, text: str = "Das ist ein Satz.") -> dict:
    return {"events": [event(n * 3000, text, 2500) for n in range(count)]}


class IngestTest(unittest.TestCase):
    """What `add` does with the list, stopped before the write.

    `wanted` a word no track says makes `add` refuse "off target" at the
    last moment before the catalogue is touched — by then it has chosen and
    read its track, which is the thing under test.
    """

    def add(self, tracks, served: dict, **kwargs):
        ingestor = VideoIngestor(Settings(), None)
        ingestor._pipeline = _Pipeline()
        read: list[str] = []

        def payload(url, agent, http=None):
            read.append(url)
            return served[url]

        with mock.patch("ingest.video.list_tracks",
                        lambda _video: track_list(tracks)), \
                mock.patch("ingest.captions._payload", payload):
            try:
                ingestor.add("vid", "de", **kwargs)
            except SystemExit as refused:
                return refused, read
        self.fail("add wrote to the catalogue")

    def test_the_hand_written_track_is_read_and_the_machine_one_is_not(self) -> None:
        refused, read = self.add(
            LIKE_GERMANS, {"https://yt.test/.de-DE": spoken(MIN_LINES)},
            wanted=("Zauberwort",), accept_auto=True)
        self.assertEqual(read, ["https://yt.test/.de-DE"])
        self.assertIn("off target", str(refused))

    def test_without_auto_a_machine_track_is_a_reason_and_never_read(self) -> None:
        refused, read = self.add(MACHINE_ONLY, {})
        self.assertEqual(read, [])
        self.assertIn("auto-generated", str(refused))
        self.assertIn(AttemptLog.classify(str(refused)), SETTLED)

    def test_with_auto_the_machine_track_meets_the_gate(self) -> None:
        refused, read = self.add(
            MACHINE_ONLY,
            {"https://yt.test/a.de": spoken(MIN_LINES, "das ist ein satz")},
            accept_auto=True)
        self.assertEqual(read, ["https://yt.test/a.de"])
        self.assertIsInstance(refused, Refused)
        self.assertEqual(refused.outcome, "auto-unpunctuated")

    def test_english_speech_gives_no_machine_track_to_judge(self) -> None:
        refused, read = self.add(ENGLISH, {}, accept_auto=True)
        self.assertEqual(read, [])
        self.assertEqual(refused.outcome, "auto-no-track")

    def test_a_title_card_is_refused_on_the_hand_written_path(self) -> None:
        refused, _ = self.add(
            [(".de", "de", None)], {"https://yt.test/.de": spoken(3)})
        self.assertIn("only 3 caption lines", str(refused))

    def test_a_refused_list_is_weather_and_not_a_reason(self) -> None:
        """It propagates as `Throttled`, a plain exception, which is how
        `add-videos` met the 429s this replaces — classified from its text,
        and counted towards stopping the run."""
        ingestor = VideoIngestor(Settings(), None)
        ingestor._pipeline = _Pipeline()

        def refuse(_video):
            raise Throttled("HTTP 429 Too Many Requests — YouTube's player "
                            "refused every client (ios HTTP 429).")

        with mock.patch("ingest.video.list_tracks", refuse):
            with self.assertRaises(Throttled) as caught:
                ingestor.add("vid", "de")
        self.assertEqual(
            AttemptLog.classify(f"Throttled: {caught.exception}"), "throttled")

    def test_a_refused_download_on_the_auto_path_is_unfetchable(self) -> None:
        """The dry-run survey catches `SystemExit` and nothing else."""
        ingestor = VideoIngestor(Settings(), None)

        def refuse(url, agent, http=None):
            raise Throttled("the caption track could not be downloaded")

        with mock.patch("ingest.captions._payload", refuse):
            with self.assertRaises(Unfetchable):
                ingestor.machine_transcript("vid", "de",
                                            track_list(MACHINE_ONLY))


if __name__ == "__main__":
    unittest.main()
