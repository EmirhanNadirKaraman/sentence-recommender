"""Machine-generated captions, and whether one track is worth keeping.

Ingest takes hand-written subtitles only, and for the corpus at large that
policy is right: `caption-check` measured thirty videos holding both kinds
and every machine track was worse than its hand-written counterpart — 31%
fewer teachable sentences, because ASR over-segments.

That measurement compared a machine track against a manual one. It says
nothing about a channel that has no manual track at all, where the
comparison is against zero, and TODO item 7 recorded the same conclusion in
its own words: auto captions are "usable where nothing else exists". This is
the path for those, and the gate below is what decides "usable".

language-app's fetcher reads hand-written tracks only and never the machine
one — upstream product policy, and not ours to quietly invert from the
outside. Nothing here goes through it any more: `ingest.captions` lists a
video's tracks and says which are machine ones, and a machine track reaches
the catalogue only past this gate and marked `transcript_source='auto'`.
"""
from __future__ import annotations

from dataclasses import dataclass

# A machine track is usable only if it punctuates. `MergeCorrector` finds
# sentence boundaries by punctuation, so a track without any becomes one
# enormous sentence: excellent vocabulary, and nothing a word can be the only
# unknown in. The rate is bimodal, and measured twice: 18-56% across the
# thirty videos `caption-check` compared, 11-29% across lingoni's, and
# nothing at all in between those and zero. So the threshold only has to
# separate "some" from "none", and sits in clear air wherever it is put.
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
