"""Which caption tracks a video has, and what one of them says.

Asked of YouTube's player API directly, the way its iOS app asks: one POST
for the list of tracks, one GET for the track chosen. The transport is
youtube-caption-extractor's (github.com/devhims/youtube-caption-extractor,
1.10.2) — its client profiles, its endpoint and its order of fallbacks —
ported rather than installed, because it is a Node package and nothing else
here is.

Its choice of track is deliberately not ported. `getSubtitles` takes `.de`,
then `a.de`, which is the machine track, then anything whose language is
`de`, then the first track in any language at all — and what it returns
does not say which one it read. Asked for German on eS0hOVaiYY4, whose
hand-written German is filed under `de-DE`, it returned the ASR; asked about
a video with no German, it returns whatever comes first. Nothing downstream
could have caught either. So this hands back the whole list and says what
each track is, and the choosing stays this project's: a hand-written track
in the language asked for, a machine one only where a caller asks for that,
and otherwise nothing.

The list is also cleaner than yt-dlp's. yt-dlp files the machine track under
`de-orig` and again under a bare `de`, and a bare `de` beside a hundred other
languages is a machine *translation* of someone else's speech — which is why
`ORIGINAL` had to exist. The player lists no translations, which are a
parameter on a track's URL rather than tracks, so a machine track in German
is YouTube transcribing what it took for German. Six of an even spread of
twenty-four lingoni lessons speak English and list only `a.en`, where yt-dlp
offered them a bare `de`. What it takes for German is not always German: two
more of the same spread list `a.de` over lessons 40% and 54% German, which is
why the gate still reads the whole track.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

import requests

from corpus.sentence import RawLine

ENDPOINT = ("https://youtubei.googleapis.com/youtubei/v1/player"
            "?prettyPrint=false")


@dataclass(frozen=True)
class Client:
    """One of the apps the player API is asked as."""

    name: str
    client_name: str
    version: str
    header: str
    """`X-YouTube-Client-Name`: the same client, as a number."""
    agent: str
    context: dict = field(default_factory=dict)


# youtube-caption-extractor 1.10.2's profiles, in its order: tried until one
# answers with caption tracks. These strings rot. When every client starts
# refusing, the library's own advice is to bump the versions to whatever
# yt-dlp's recent commits use — and its nightly canary opens an issue when
# its hosted copy stops getting answers, so its latest release is usually
# the fix already made.
CLIENTS = (
    Client("ios", "IOS", "20.10.4", "5",
           "com.google.ios.youtube/20.10.4 (iPhone16,2; U; CPU iOS 18_3_2 "
           "like Mac OS X;)",
           {"deviceMake": "Apple", "deviceModel": "iPhone16,2",
            "platform": "MOBILE", "osName": "iOS",
            "osVersion": "18.3.2.22D82"}),
    Client("android_vr", "ANDROID_VR", "1.62.20", "28",
           "com.google.android.apps.youtube.vr.oculus/1.62.20 (Linux; U; "
           "Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip",
           {"deviceMake": "Oculus", "deviceModel": "Quest 3",
            "platform": "MOBILE", "osName": "Android", "osVersion": "12L",
            "androidSdkVersion": 32}),
    Client("mweb", "MWEB", "2.20251209.01.00", "2",
           "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) "
           "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
           "Mobile/15E148 Safari/604.1",
           {"platform": "MOBILE", "osName": "iOS", "osVersion": "17.5.1"}),
)

# Seconds before a request is given up on. `requests` waits forever without
# one, and a channel run that hangs on its fortieth video has not failed —
# it has stopped, with nothing to say so.
TIMEOUT = 20.0

# The caption endpoint throttles separately from the player one, and harder.
# A survey at one video every 1.5s drew HTTP 429 from it on the
# forty-seventh while the metadata requests beside it were still answered.
DOWNLOAD_TRIES = 3
DOWNLOAD_BACKOFF = 5.0

# A cue with no length of its own, and no next cue to borrow one from.
LAST_CUE = 2.0


class Throttled(RuntimeError):
    """YouTube refused the request. Weather, and never a verdict.

    An ordinary exception rather than one of the `Outcome` family, because
    this has callers that are not ingesting anything. `caption-check` skips
    a bad video with `except Exception`, and `SystemExit` is a
    `BaseException` — raising one from here would end that command on the
    first throttled video instead of the video. Whoever is writing to the
    catalogue decides what it is recorded as.

    The wording is read. `add-videos` classifies a plain exception by its
    text, and stops a whole run after five 429s in a row, so a 429 says
    "HTTP 429" and nothing else here says anything `AttemptLog.classify`
    would settle — no "unavailable", no "subtitles".
    """


@dataclass(frozen=True)
class Track:
    """One caption track, and what kind it is."""

    language: str
    """YouTube's `languageCode`: `de`, `de-DE`, `de-AT`."""

    machine: bool
    """Speech recognition's, rather than someone's who typed it."""

    url: str
    label: str = ""
    """YouTube's `vssId` — `.de-DE`, `a.de` — for saying which one it was."""


@dataclass(frozen=True)
class Tracks:
    """Everything the player said a video has, in one client's answer."""

    video_id: str
    tracks: tuple[Track, ...]
    length: float | None = None
    """The video's length in seconds, for the last cue of a track."""
    title: str = ""
    agent: str = CLIENTS[0].agent
    """The user agent of the client that answered, which fetches the track.
    A caption URL issued to one app and fetched as another is the mismatch
    that drew the 429 on the forty-seventh video."""

    def manual(self, language: str) -> Track | None:
        """The hand-written track in `language`, if there is one.

        The rule language-app's fetcher has always used — the plain code
        first, then any regional one — so what counts as having German
        subtitles did not change when the fetch did. `de-DE` is German:
        eS0hOVaiYY4 is catalogued on exactly that track.
        """
        return self._pick(language, machine=False)

    def machine(self, language: str) -> Track | None:
        """The speech-recognition track in `language`, if there is one."""
        return self._pick(language, machine=True)

    def hand_written(self) -> list[str]:
        """The languages someone wrote subtitles in."""
        return sorted({t.language for t in self.tracks if not t.machine})

    def _pick(self, language: str, machine: bool) -> Track | None:
        kind = [t for t in self.tracks if t.machine == machine]
        return (next((t for t in kind if t.language == language), None)
                or next((t for t in kind
                         if t.language.startswith(f"{language}-")), None))

    def read(self, track: Track, http=requests) -> list[RawLine]:
        """What `track` says, as the caption lines the corrector reads."""
        payload = _payload(track.url, self.agent, http)
        return lines(payload, self.video_id, self.length)


def list_tracks(video_id: str, http=requests) -> Tracks:
    """Every caption track the player lists for `video_id`.

    Each client is asked in turn until one answers with tracks, and an
    answer with none is only believed when every client has been asked:
    different clients see different states of the same video, and the only
    signal that a video has no captions is that no client which answered
    found any. A video no client would play at all raises `Throttled` — the
    player uses the same status for "deleted" as for "this client is too
    old", so a refusal is weather here. In `add`, the metadata fetch before
    this one is what says whether a video exists.

    `http` is anything with `requests`' `post` and `get`, so tests can
    answer for YouTube.
    """
    answered: Tracks | None = None
    refusals: list[str] = []
    for client in CLIENTS:
        try:
            response = http.post(ENDPOINT, json=_ask(client, video_id),
                                 headers=_headers(client), timeout=TIMEOUT)
        except requests.RequestException as error:
            refusals.append(f"{client.name} {type(error).__name__}")
            continue
        if response.status_code != 200:
            refusals.append(f"{client.name} HTTP {response.status_code}")
            continue
        try:
            data = response.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            refusals.append(f"{client.name} not JSON")
            continue
        status = (data.get("playabilityStatus") or {}).get("status")
        if status and status != "OK":
            # The status and never the reason beside it. The reason is
            # prose, and "This video is unavailable" is what YouTube tells an
            # outdated client about a perfectly good video — prose that
            # `classify` would read as a verdict and settle forever.
            refusals.append(f"{client.name} {status}")
            continue
        found = _tracks(video_id, data, client)
        if found.tracks:
            return found
        answered = answered or found
    if answered is not None:
        return answered
    throttled = any(r.endswith("HTTP 429") for r in refusals)
    raise Throttled(
        ("HTTP 429 Too Many Requests — " if throttled else "")
        + f"YouTube's player refused every client ({', '.join(refusals)}),"
        " which is the asking and not the video.")


def lines(payload: dict, video_id: str,
          length: float | None = None) -> list[RawLine]:
    """A json3 caption track as raw lines.

    The text exactly as language-app's parser has always joined it — the
    segments concatenated and stripped, and nothing decoded or taken out —
    so a video fetched this way tokenises like the 2,889 already in the
    catalogue.
    """
    timed: list[tuple[float, float, str]] = []
    for event in payload.get("events") or []:
        segments = event.get("segs") or []
        text = "".join(s.get("utf8", "") for s in segments).strip()
        if not text:
            continue
        timed.append(((event.get("tStartMs") or 0) / 1000,
                      (event.get("dDurationMs") or 0) / 1000,
                      text))
    return [
        RawLine(
            sentence_id=-(number + 1),          # negative: never a real row
            video_id=video_id,
            start_time=start,
            duration=_cue_length(timed, number, duration, length),
            content=text,
            # Empty: the column exists because `sentence` has one, and
            # neither the corrector nor the aligner reads it.
            tokens=(),
        )
        for number, (start, duration, text) in enumerate(timed)
    ]


def snippets(caption_lines: list[RawLine]) -> list[dict]:
    """Raw lines in the shape `pipeline.populate` writes."""
    return [{"text": line.content, "start": line.start_time,
             "duration": line.duration} for line in caption_lines]


def _ask(client: Client, video_id: str) -> dict:
    return {
        "context": {
            "client": {"clientName": client.client_name,
                       "clientVersion": client.version,
                       "hl": "en", "gl": "US", **client.context},
            "user": {"lockedSafetyMode": False},
            "request": {"useSsl": True},
        },
        "videoId": video_id,
        "contentCheckOk": True,
        "racyCheckOk": True,
    }


def _headers(client: Client) -> dict:
    return {"Content-Type": "application/json", "Accept": "*/*",
            "User-Agent": client.agent,
            "X-YouTube-Client-Name": client.header,
            "X-YouTube-Client-Version": client.version,
            "Origin": "https://www.youtube.com"}


def _tracks(video_id: str, data: dict, client: Client) -> Tracks:
    renderer = ((data.get("captions") or {})
                .get("playerCaptionsTracklistRenderer") or {})
    details = data.get("videoDetails") or {}
    seconds = details.get("lengthSeconds")
    return Tracks(
        video_id=video_id,
        tracks=tuple(
            Track(language=t.get("languageCode") or "",
                  machine=t.get("kind") == "asr",
                  url=t["baseUrl"], label=t.get("vssId") or "")
            for t in renderer.get("captionTracks") or []
            if t.get("baseUrl")),
        length=float(seconds) if seconds else None,
        title=details.get("title") or "",
        agent=client.agent)


def _payload(url: str, agent: str, http=requests) -> dict:
    """One caption track's json3, or an explanation that is not a verdict.

    A failure here is never a verdict. Parsing a throttle's HTML "Sorry..."
    page as JSON was a bug once: it raised `JSONDecodeError: Expecting value:
    line 1 column 1`, a message about the parser's disappointment that says
    nothing about the video, and anything reading it as "this track is
    unusable" would write off a good video for having been asked about too
    quickly. An empty answer is weather too — it is what the endpoint gives
    a URL it will not serve — whereas a track that parses and holds no
    lines is a verdict, and comes back as an empty list.
    """
    url = re.sub(r"&fmt=[^&]+", "", url) + "&fmt=json3"
    last = ""
    for attempt in range(DOWNLOAD_TRIES):
        try:
            response = http.get(url, headers={"User-Agent": agent},
                                timeout=TIMEOUT)
            if response.status_code != 200:
                last = f"HTTP {response.status_code}"
            elif not response.text.strip():
                last = "an empty answer"
            else:
                payload = json.loads(response.text)
                if isinstance(payload, dict):
                    return payload
                last = "not a caption track"
        except (requests.RequestException, ValueError) as error:
            last = type(error).__name__
        if attempt < DOWNLOAD_TRIES - 1:
            time.sleep(DOWNLOAD_BACKOFF * (2 ** attempt))
    raise Throttled(
        ("HTTP 429 Too Many Requests — " if last == "HTTP 429" else "")
        + f"the caption track could not be downloaded after {DOWNLOAD_TRIES}"
        f" attempts ({last}) — the request is being refused, which says"
        " nothing about the video.")


def _cue_length(timed: list, number: int, duration: float,
                whole: float | None) -> float:
    """How long one caption line lasts, when the track does not say.

    Manual json3 carries `dDurationMs` on every event — forty cached tracks,
    not one missing value. ASR json3 is a different shape and need not, and a
    zero here is not a cosmetic default: `RawLine.duration` is what
    `SubtitleAligner` matches sentences against, so a track of zero-length
    cues gives every sentence a zero-length span and the overlay and the clip
    links both point at an instant.

    It also reaches `video.duration`, which `pipeline.populate` computes as
    the last line's start plus its length — and that feeds both
    `watchability` and the `i+1/min` column, where understating a video's
    length makes it look denser than it is.

    So a missing length is taken from the start of the next line, which is
    what it means, and the last line falls back to what is left of the video.
    """
    if duration > 0:
        return duration
    if number + 1 < len(timed):
        return max(0.0, timed[number + 1][0] - timed[number][0])
    if whole:
        return max(0.0, whole - timed[number][0])
    return LAST_CUE
