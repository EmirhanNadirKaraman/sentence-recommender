"""The greedy walk, over videos instead of words.

The Videos tab can rank by teaching rate — how many sentences in a video are
one word away, per minute — but that is a ranking against what you know *now*.
It answers "what should I watch next" and then gives the same answer again,
because watching does not change it.

A roadmap answers the harder question: watch these in this order, and each one
is worth more than it would have been, because the ones before it taught you
the words. Same shape as the word-level walk — take the best step, learn what
it teaches, re-score what is left — with a video as the step.

What "learning a video" means here is deliberately optimistic: every word that
was the *only* unknown in one of its sentences. Those are the ones the video
can actually teach, since the rest of the sentence carries them. It will
overstate what one viewing achieves. The ordering is what this is for, and the
ordering only needs the relative sizes to be right.

Re-scoring is incremental for the same reason the word walk is. Learning a
word can only change a video that says it, so the unit-to-videos index decides
what to recompute, and everything else keeps the score it had. Without that
this is 893 videos re-scored 893 times over 115,000 sentences, which is not a
walk anyone waits for.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from corpus.sentence import Sentence
from state import open_state
from vocab.entry import Unit

# Below this a video is not a lesson, it is a clip. The reel already refuses
# to offer thin videos; the same floor keeps them out of the plan.
ENOUGH_LINES = 40


@dataclass(frozen=True)
class VideoStep:
    """One video to watch, and what watching it is expected to buy."""

    position: int
    video: str
    title: str
    minutes: float | None
    lines: int
    teaches: int                     # sentences it makes readable
    gained: tuple[Unit, ...] = ()    # the words it was the sole unknown for
    readable_after: int = 0

    @property
    def rate(self) -> float:
        """Sentences taught per minute, which is what ordered the walk."""
        return self.teaches / self.minutes if self.minutes else 0.0


class VideoWalk:
    """Orders videos so each is worth the most, given the ones before it."""

    def __init__(self, grouped: dict[str, list[Sentence]],
                 known: frozenset[Unit],
                 minutes: dict[str, float],
                 titles: dict[str, str] | None = None,
                 floor: int = ENOUGH_LINES) -> None:
        self._by_video = {v: s for v, s in grouped.items() if len(s) >= floor}
        self._known = set(known)
        self._minutes = minutes
        self._titles = titles or {}
        # Which videos say a given unit. The whole reason a re-score is cheap.
        self._says: dict[Unit, set[str]] = {}
        for video, sentences in self._by_video.items():
            for s in sentences:
                for unit in s.units:
                    self._says.setdefault(unit, set()).add(video)
        self._score: dict[str, tuple[int, frozenset[Unit]]] = {}
        # Readable sentences per video, kept as a running tally. Counting them
        # across the corpus once per step is 115,000 sentences times nine
        # hundred steps, which is the sort of thing that turns a walk into an
        # afternoon.
        self._done: dict[str, int] = {}
        for video in self._by_video:
            self._rate(video)

    def _rate(self, video: str) -> None:
        """What this video teaches, and how much of it reads, as things stand."""
        teaches, done, gained = 0, 0, set()
        for s in self._by_video[video]:
            missing = s.units - self._known
            if not missing:
                done += 1
            elif len(missing) == 1:
                teaches += 1
                gained.add(next(iter(missing)))
        self._score[video] = (teaches, frozenset(gained))
        self._done[video] = done

    def _readable(self) -> int:
        return sum(self._done.values())

    def build(self, max_steps: int | None = None,
              on_progress=None, every: int = 25) -> list[VideoStep]:
        """The order, best first, until nothing left teaches anything."""
        steps: list[VideoStep] = []
        left = set(self._by_video)
        while left and (max_steps is None or len(steps) < max_steps):
            # Rate first, then raw count, then name — so the order is
            # reproducible and a long video never wins on bulk alone.
            best = max(left, key=lambda v: (
                self._score[v][0] / (self._minutes.get(v) or 1e9),
                self._score[v][0], v))
            teaches, gained = self._score[best]
            if not teaches:
                break                      # nothing left is one word away
            self._known |= gained
            left.discard(best)
            # Only what says one of those words can have changed. The chosen
            # video is re-rated too, though it is out of the running: its
            # sentences still count toward how much of the corpus reads.
            touched = {best}
            for unit in gained:
                touched |= self._says.get(unit, set())
            for video in touched:
                self._rate(video)
            steps.append(VideoStep(
                position=len(steps) + 1,
                video=best,
                title=self._titles.get(best, ""),
                minutes=self._minutes.get(best),
                lines=len(self._by_video[best]),
                teaches=teaches,
                gained=tuple(sorted(gained, key=lambda u: (u.kind, u.key))),
                readable_after=self._readable(),
            ))
            if on_progress and len(steps) % every == 0:
                on_progress(len(steps), len(self._known))
        return steps

    @property
    def known(self) -> frozenset[Unit]:
        """What the walk expects you to know once it has run."""
        return frozenset(self._known)


SCHEMA = """
CREATE TABLE IF NOT EXISTS video_roadmap (
    source     TEXT NOT NULL,
    position   INTEGER NOT NULL,
    video_id   TEXT NOT NULL,
    teaches    INTEGER NOT NULL,
    minutes    REAL,
    lines      INTEGER NOT NULL,
    readable   INTEGER NOT NULL,
    PRIMARY KEY (source, position)
);
CREATE TABLE IF NOT EXISTS video_roadmap_meta (
    source  TEXT PRIMARY KEY,
    stamp   TEXT NOT NULL,
    made_at TEXT NOT NULL
);
"""


class VideoRoadmapStore:
    """The order, written down.

    Stored rather than computed on demand for the same reason the word
    roadmap is: the walk is a corpus load and three minutes, and the answer
    only moves when the corpus does. The words each step teaches are *not*
    kept — they run to nineteen thousand and nothing reads them back; what
    the page wants is the order.
    """

    def __init__(self, path) -> None:
        self._path = path
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)

    def save(self, steps: list[VideoStep], source: str, stamp: str = "") -> None:
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM video_roadmap WHERE source = ?", (source,))
            conn.executemany(
                "INSERT INTO video_roadmap (source, position, video_id, teaches,"
                " minutes, lines, readable) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(source, s.position, s.video, s.teaches, s.minutes, s.lines,
                  s.readable_after) for s in steps])
            if stamp:
                conn.execute(
                    "INSERT OR REPLACE INTO video_roadmap_meta"
                    " (source, stamp, made_at) VALUES (?, ?, ?)",
                    (source, stamp,
                     datetime.now().isoformat(timespec="seconds")))

    def order(self, source: str) -> dict[str, int]:
        """Video id -> where it comes in the plan."""
        with open_state(self._path) as conn:
            return {v: n for v, n in conn.execute(
                "SELECT video_id, position FROM video_roadmap WHERE source = ?",
                (source,))}

    def stamp(self, source: str) -> str | None:
        with open_state(self._path) as conn:
            row = conn.execute(
                "SELECT stamp FROM video_roadmap_meta WHERE source = ?",
                (source,)).fetchone()
        return row[0] if row else None
