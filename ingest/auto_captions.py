"""Machine-generated captions, and whether one track is worth keeping.

Ingest takes hand-written subtitles only, and for the corpus at large that
policy is right: `caption-check` measured thirty videos holding both kinds
and every machine track was worse than its hand-written counterpart —  31%
fewer teachable sentences, because ASR over-segments.

That measurement compared a machine track against a manual one. It says
nothing about a channel that has no manual track at all, where the
comparison is against zero, and TODO item 7 recorded the same conclusion in
its own words: auto captions are "usable where nothing else exists". This is
the path for those, and the gate below is what decides "usable".

Nothing here reaches `transcript_fetcher.fetch_with_retries`. That function
reads `info["subtitles"]` and deliberately never looks at
`info["automatic_captions"]` — upstream product policy, and not ours to
quietly invert from the outside. So the machine track is fetched here, in
the open, and marked `transcript_source='auto'` wherever it lands.
"""
from __future__ import annotations

from dataclasses import dataclass

from corpus.sentence import RawLine

# Which caption track counts as "the machine one". YouTube offers auto
# captions in 150-odd languages for a popular video and all but one are
# machine translations of the ASR — `de-orig` is the original transcript, and
# a bare `de` beside a hundred others is a translation into German. Measuring
# a translation would answer a question nobody asked.
ORIGINAL = ("de-orig", "de-DE", "de")

# A machine track is usable only if it punctuates. `MergeCorrector` finds
# sentence boundaries by punctuation, so a track without any becomes one
# enormous sentence: excellent vocabulary, and nothing a word can be the only
# unknown in. The rate is bimodal — a track punctuates about a fifth of its
# lines or none at all — so the threshold only has to separate "some" from
# "none".
PUNCTUATED = 0.05

# Below this a caption track is a title card or a burned-in credit, not
# speech. The same floor the manual path uses, for the same reason.
MIN_LINES = 20

# How much of the track has to actually be German.
#
# This gate does not exist for a normal German channel, and it was not in the
# first design. It exists because a German-*teaching* channel explains German
# in English: two of the four cleanly-punctuated lingoni tracks in the first
# sample are English instruction with German examples dropped in, and
# YouTube reports `language: de` for both — the audio tag cannot tell them
# apart. An English track admitted here does not merely add nothing, it puts
# English sentences in a German corpus, where the parser will lemmatise them
# into units and the roadmap will teach them.
GERMAN = 0.6

# Language is judged over windows of about this many characters. Not per
# line — a caption line is three or four words and detection on that is
# noise — and not over the whole track at once, which returns one arbitrary
# verdict for a video that is half English. A window is the smallest unit
# that carries enough text to be called.
WINDOW = 200


class Outcome(SystemExit):
    """A refusal that names the attempt-log outcome it should be recorded as.

    A `SystemExit` like every other refusal in the ingest path, so nothing
    that catches those has to learn a new exception — but it carries the
    verdict as a field rather than leaving `AttemptLog.classify` to recover
    it from the wording. Classification by string is how a throttled request
    once got recorded as "this video has no subtitles" and settled nine
    videos nobody had checked.
    """

    def __init__(self, message: str, outcome: str) -> None:
        super().__init__(message)
        self.outcome = outcome


class Refused(Outcome):
    """A machine track the gate read and would not keep.

    A verdict: the track exists, it was judged, and judging it again
    tomorrow gives the same answer.
    """


class Unfetchable(Outcome):
    """The track could not be read at all. Weather, and never a verdict.

    Kept apart from `Refused` because the two are opposite in the only way
    that matters to the attempt log — `unfetchable` is not in `AUTO_SETTLED`,
    so this is retried, and a refusal is not. Collapsing them is the specific
    mistake this project has already made once, writing off nine videos
    nobody had checked because a request that failed was recorded as an
    answer.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, "unfetchable")


class Throttled(RuntimeError):
    """The caption endpoint refused the request.

    An ordinary exception rather than one of the `Outcome` family, because
    this is raised by the download and the download has callers that are not
    ingesting anything. `caption-check` skips a bad video with `except
    Exception`, and `SystemExit` is a `BaseException` — raising one from here
    would end that command on the first throttled video instead of the video.
    Whoever is writing to the catalogue turns this into `Unfetchable`.
    """


@dataclass(frozen=True)
class Judgement:
    """What the gate made of one track, and the numbers behind it."""

    verdict: str
    """`ok`, or the short reason it was refused."""

    lines: int
    punctuation: float
    german: float

    @property
    def ok(self) -> bool:
        return self.verdict == "ok"

    def why(self) -> str:
        """One sentence for a person, saying which test it failed."""
        if self.verdict == "ok":
            return (f"{self.lines} lines, {self.punctuation:.0%} punctuated, "
                    f"{self.german:.0%} German")
        if self.verdict == "too-short":
            return (f"only {self.lines} caption lines — too little to be "
                    "worth keeping.")
        if self.verdict == "unpunctuated":
            return (f"machine captions with no punctuation "
                    f"({self.punctuation:.0%} of {self.lines} lines end in "
                    "one), which collapse into a single sentence that "
                    "teaches nothing.")
        if self.verdict == "not-german":
            return (f"machine captions only {self.german:.0%} German — this "
                    "is a video explaining German in another language.")
        return self.verdict


def punctuation_rate(lines) -> float:
    if not lines:
        return 0.0
    ended = sum(1 for line in lines
                if line.content.rstrip().endswith((".", "!", "?")))
    return ended / len(lines)


def german_share(lines, window: int = WINDOW) -> float:
    """The share of the track that reads as German.

    Detection is seeded. `langdetect` is probabilistic and picks its own seed
    per process otherwise, so an unseeded gate gives different answers to the
    same video on different runs — across a channel of 882 that is a gate
    nobody can reproduce.
    """
    from langdetect import DetectorFactory, detect   # noqa: PLC0415 — heavy
    from langdetect.lang_detect_exception import LangDetectException  # noqa: PLC0415

    DetectorFactory.seed = 0

    windows, current = [], ""
    for line in lines:
        current = f"{current} {line.content}".strip()
        if len(current) >= window:
            windows.append(current)
            current = ""
    # The tail joins the last full window rather than standing as a short one
    # of its own, which would be judged on less text than everything else.
    if current and windows:
        windows[-1] = f"{windows[-1]} {current}"
    elif current:
        windows.append(current)

    if not windows:
        return 0.0
    german = 0
    for text in windows:
        try:
            german += detect(text) == "de"
        except LangDetectException:
            # Too little to call — music cues, applause markers. Counted as
            # neither, by being counted in the denominator and not the
            # numerator, which is the conservative reading.
            continue
    return german / len(windows)


def judge(lines, floor: int = MIN_LINES) -> Judgement:
    """Whether this machine track is worth putting in the catalogue.

    Ordered cheapest test first, and each one is a separate verdict rather
    than a single boolean, because the reason is what the caller reports and
    what the attempt log settles on.
    """
    punctuation = punctuation_rate(lines)
    if len(lines) < floor:
        return Judgement("too-short", len(lines), punctuation, 0.0)
    if punctuation < PUNCTUATED:
        return Judgement("unpunctuated", len(lines), punctuation, 0.0)
    german = german_share(lines)
    if german < GERMAN:
        return Judgement("not-german", len(lines), punctuation, german)
    return Judgement("ok", len(lines), punctuation, german)


def machine_track(video_id: str, options: dict | None = None
                  ) -> tuple[str, list[RawLine]] | tuple[None, None]:
    """The ASR track for one video, as raw lines — or nothing.

    `options` are yt-dlp's. The default is cookieless, which is what
    `caption-check` wants: it uses a client that needs no n-challenge, and
    attaching cookies without `js_runtimes` and `remote_components` answers
    every video with "The page needs to be reloaded". A caller that has the
    full set — `ingest.options.scrape` builds it — passes it in.
    """
    import yt_dlp                                # noqa: PLC0415

    options = options or {"quiet": True, "no_warnings": True,
                          "skip_download": True}
    # The download happens inside the same `with`, on the same instance, so
    # the caption request carries the session the metadata request used.
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False)
        return track_from_info(info, video_id, ydl)


# The caption endpoint throttles separately from the metadata one, and
# harder. A survey at one video every 1.5s drew HTTP 429 from it on the
# forty-seventh while yt-dlp's own requests were still being answered, so the
# two cannot be paced together.
DOWNLOAD_TRIES = 3
DOWNLOAD_BACKOFF = 5.0


def _payload(url: str, opener) -> dict:
    """One caption track's json3, or an explanation that is not a verdict.

    `opener` is the `YoutubeDL` instance that fetched the metadata, and it
    has to be that one. This asked `requests.get` at first — an anonymous
    request with no cookie jar and a default user agent, which is the shape
    Google throttles hardest. A survey of one channel drew HTTP 429 from the
    caption endpoint on its forty-seventh video while yt-dlp's own requests
    were still being answered, and that is the whole story: the two are not
    the same client, and only one of them was signed in.
    `transcript_fetcher.py:242` reaches for the same handle for the same
    reason.

    Using the live instance rather than building a second one also avoids
    re-reading the browser's cookie database once per video, and keeps the
    gap small between a caption URL being issued and being used — they are
    signed and time-limited.

    A failure here is never a verdict. Parsing a throttle's HTML "Sorry..."
    page as JSON was the bug this replaces: it raised `JSONDecodeError:
    Expecting value: line 1 column 1`, a message about the parser's
    disappointment that says nothing about the video, and anything reading it
    as "this track is unusable" would write off a good video for having been
    asked about too quickly.
    """
    import json as jsonlib                       # noqa: PLC0415
    import time                                  # noqa: PLC0415

    last: Exception | None = None
    for attempt in range(DOWNLOAD_TRIES):
        try:
            body = opener.urlopen(url).read()
            if isinstance(body, bytes):
                body = body.decode("utf-8")
            return jsonlib.loads(body)
        except Exception as error:               # noqa: BLE001 — all weather
            # yt-dlp raises on an HTTP error rather than returning a status,
            # so there is no code to branch on — and an interstitial is
            # served with a 200 as readily as with a 429, so a status would
            # not settle it anyway. Upstream treats the whole class alike.
            last = error
            if attempt < DOWNLOAD_TRIES - 1:
                time.sleep(DOWNLOAD_BACKOFF * (2 ** attempt))
    raise Throttled(
        f"the caption track could not be downloaded after {DOWNLOAD_TRIES} "
        f"attempts ({type(last).__name__}) — the request is being refused, "
        "which says nothing about the video.") from last


def track_from_info(info: dict, video_id: str, opener
                    ) -> tuple[str, list[RawLine]] | tuple[None, None]:
    """The chosen track out of metadata already fetched.

    Split from `machine_track` so the ingest path, which needs the same
    metadata for the title and the channel, does not fetch it twice.
    `opener` is that fetch's own `YoutubeDL`; see `_payload`.
    """
    autos = info.get("automatic_captions") or {}
    audio = (info.get("language") or "").lower()

    chosen = None
    for key in ORIGINAL:
        if key not in autos:
            continue
        # A bare `de` among many languages is the translation pipeline.
        if key == "de" and "de-orig" not in autos and not audio.startswith("de"):
            continue
        chosen = key
        break
    if not chosen:
        return None, None

    entry = next((e for e in autos[chosen] if e.get("ext") == "json3"), None)
    if not entry:
        return None, None
    payload = _payload(entry["url"], opener)

    lines: list[RawLine] = []
    for number, event in enumerate(payload.get("events") or []):
        segments = event.get("segs") or []
        text = "".join(s.get("utf8", "") for s in segments).strip()
        if not text:
            continue
        start = (event.get("tStartMs") or 0) / 1000
        lines.append(RawLine(
            sentence_id=-(number + 1),          # negative: never a real row
            video_id=video_id,
            start_time=start,
            duration=(event.get("dDurationMs") or 0) / 1000,
            content=text,
            # Empty: the column exists because `sentence` has one, and
            # neither the corrector nor the aligner reads it.
            tokens=(),
        ))
    return chosen, lines
