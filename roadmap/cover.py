"""The fewest minutes of video that teach a whole list.

A roadmap is an order; this is a set. Given a list of words, choose the
videos in which every one of them has enough sentences where it is the only
unknown — and spend as few minutes doing it as possible.

Why videos and not sentences. An i+1 sentence has exactly one unknown, so it
covers one word and no other: the sets are disjoint and "cover" is just
`examples.rank` five deep, nothing to solve. Videos overlap, because one
video holds sole-unknown sentences for many words at once, so the set really
is a set and the answer is worth minutes.

The model is language-app's `ilp/optimal_set_finder.py` with `file` read as
`video`: a binary per video, cost its length, one constraint per word. Two
things differ and both matter.

  * The constraint counts *sentences*, not videos. One video may supply all
    five, so a video's coefficient is how many sole-unknown sentences it
    holds for that word, not one. Reading it as five videos a word solves a
    different and far more expensive problem.
  * A word with fewer sentences than asked for is asked for what exists.
    Demanding five where three are possible makes the whole model infeasible
    and returns nothing — where what is wanted is the cover plus a list of
    what fell short.

`gapRel` is 0.0, not the 0.08 the source model used. That number came from a
much larger problem; here twenty words over 157 videos solve exactly in a
tenth of a second, and 0.08, 0.02 and 0.0 all return the same 41 videos. An
inherited tolerance that is never binding is just a number nobody can
account for later.

The solver earns its place narrowly. Against a greedy pick by words-per-
minute it saves 7% — 41 videos and 1,180 minutes against 48 and 1,264 — so
it is worth a dependency whose wheel carries its own solver, and would not
be worth much more than that.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from vocab.entry import Unit

# Below this a video is a clip, not a lesson. Minimising minutes rewards the
# shortest thing that says the word, so without a floor a cover is forty
# ninety-second videos — the same reason `VideoWalk` carries one.
ENOUGH_LINES = 40
DEPTH = 5


@dataclass(frozen=True)
class Cover:
    """Which videos to watch, and what the list gets out of them."""

    videos: tuple[str, ...] = ()
    minutes: float = 0.0
    # unit -> the video ids that teach it, best supply first
    taught: dict[Unit, tuple[str, ...]] = field(default_factory=dict)
    # unit -> (asked for, available) where the corpus could not supply DEPTH
    short: dict[Unit, tuple[int, int]] = field(default_factory=dict)
    # No sole-unknown sentence in any timed video at all.
    unreachable: tuple[Unit, ...] = ()
    status: str = ""
    gap: float = 0.0
    seconds: float = 0.0

    @property
    def hours(self) -> float:
        return self.minutes / 60


def supply(index, sentences, goals, minutes,
           floor: int = ENOUGH_LINES) -> dict[Unit, dict[str, int]]:
    """unit -> video -> how many distinct sentences teach it there.

    Counting texts rather than positions because a corpus holds a few
    repeats, and five copies of one line is not five sentences.

    `candidates()` hands back the index's own sets and drops entries as they
    empty, so this snapshots what it needs rather than holding them.
    """
    lines: dict[str, int] = {}
    for sentence in sentences:
        if sentence.timing:
            lines[sentence.timing.video_id] = lines.get(
                sentence.timing.video_id, 0) + 1

    out: dict[Unit, dict[str, int]] = {}
    for unit, positions in index.candidates().items():
        if unit not in goals:
            continue
        seen: dict[str, set[str]] = {}
        for position in list(positions):
            sentence = sentences[position]
            # No timing means no video: the transcript build cannot be in a
            # cover, and an untimed subtitle line cannot be pointed at.
            if not sentence.timing:
                continue
            video = sentence.timing.video_id
            if lines.get(video, 0) < floor or video not in minutes:
                continue
            seen.setdefault(video, set()).add(sentence.text)
        if seen:
            out[unit] = {v: len(texts) for v, texts in seen.items()}
    return out


def solve(index, sentences, goals: frozenset[Unit], minutes: dict[str, float],
          depth: int = DEPTH, floor: int = ENOUGH_LINES,
          gap: float = 0.0, say=print) -> Cover:
    """The cheapest set of videos that teaches the list `depth` deep."""
    import pulp                                   # noqa: PLC0415 — heavy

    held = supply(index, sentences, goals, minutes, floor)
    unreachable = tuple(sorted((u for u in goals if u not in held),
                               key=lambda u: (u.kind, u.key)))
    if not held:
        return Cover(unreachable=unreachable, status="nothing to cover")

    videos = sorted({v for supplies in held.values() for v in supplies})
    say(f"  {len(held):,} of {len(goals):,} goals have a video; "
        f"{len(videos):,} videos hold them")

    problem = pulp.LpProblem("cover", pulp.LpMinimize)
    pick = {v: pulp.LpVariable(f"v_{i}", cat="Binary")
            for i, v in enumerate(videos)}
    problem += pulp.lpSum(minutes[v] * pick[v] for v in videos)

    short: dict[Unit, tuple[int, int]] = {}
    for unit, supplies in held.items():
        available = sum(supplies.values())
        want = min(depth, available)
        if want < depth:
            short[unit] = (want, available)
        # The coefficient is how many sentences this video brings, so one
        # video can satisfy the whole requirement on its own.
        problem += pulp.lpSum(n * pick[v] for v, n in supplies.items()) >= want

    started = time.perf_counter()
    problem.solve(pulp.PULP_CBC_CMD(msg=False, gapRel=gap))
    seconds = time.perf_counter() - started
    status = pulp.LpStatus[problem.status]

    chosen = tuple(v for v in videos if pick[v].value() and pick[v].value() > 0.5)
    taught = {
        unit: tuple(sorted((v for v in chosen if v in supplies),
                           key=lambda v: -supplies[v]))
        for unit, supplies in held.items()
    }
    return Cover(
        videos=chosen,
        minutes=sum(minutes[v] for v in chosen),
        taught=taught,
        short=short,
        unreachable=unreachable,
        status=status,
        gap=gap,
        seconds=seconds,
    )


def audit(cover: Cover, held: dict[Unit, dict[str, int]],
          depth: int = DEPTH) -> list[tuple[Unit, int, int]]:
    """Re-count the cover against the pool, without asking the solver.

    A solver reporting `Optimal` proves the model was satisfied, not that the
    model was right — and the coefficient is exactly the sort of thing that
    produces a confidently optimal wrong answer. Returns whatever falls
    short: (unit, got, wanted).
    """
    picked = set(cover.videos)
    bad = []
    for unit, supplies in held.items():
        got = sum(n for v, n in supplies.items() if v in picked)
        wanted = min(depth, sum(supplies.values()))
        if got < wanted:
            bad.append((unit, got, wanted))
    return bad


SCHEMA = """
CREATE TABLE IF NOT EXISTS video_cover (
    list     TEXT NOT NULL,
    build    TEXT NOT NULL,
    position INTEGER NOT NULL,
    video_id TEXT NOT NULL,
    minutes  REAL,
    PRIMARY KEY (list, build, position)
);
CREATE TABLE IF NOT EXISTS video_cover_meta (
    list        TEXT NOT NULL,
    build       TEXT NOT NULL,
    stamp       TEXT NOT NULL,
    made_at     TEXT NOT NULL,
    depth       INTEGER NOT NULL,
    minutes     REAL NOT NULL,
    covered     INTEGER NOT NULL,
    short       INTEGER NOT NULL,
    unreachable INTEGER NOT NULL,
    PRIMARY KEY (list, build)
);
"""


class VideoCoverStore:
    """Covers, kept by which list and which build made them.

    Both halves of the key, because a cover of `subtitle` and a cover of
    `subtitle+transcript` are different answers to the same question and a
    name that said only the list would have one silently delete the other.

    Beside `VideoRoadmapStore` rather than inside it: a roadmap is an order
    over everything, this is a set aimed at a list, and the only thing they
    share is being about videos.

    The stamp is stored but never used to refuse an answer. A cover is a
    snapshot of one known set and the reader's grows daily, so every stored
    cover is slightly stale by design — the page is meant to say how stale,
    not to throw it away and make someone wait.
    """

    def __init__(self, path) -> None:
        from state import open_state                   # noqa: PLC0415
        self._path = path
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)

    def save(self, cover: Cover, wordlist: str, build: str, stamp: str,
             depth: int = DEPTH) -> None:
        from datetime import datetime                  # noqa: PLC0415
        from state import open_state                   # noqa: PLC0415
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM video_cover WHERE list = ? AND build = ?",
                         (wordlist, build))
            conn.executemany(
                "INSERT INTO video_cover (list, build, position, video_id,"
                " minutes) VALUES (?, ?, ?, ?, ?)",
                [(wordlist, build, i, v, None)
                 for i, v in enumerate(cover.videos)])
            conn.execute(
                "INSERT OR REPLACE INTO video_cover_meta (list, build, stamp,"
                " made_at, depth, minutes, covered, short, unreachable)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (wordlist, build, stamp,
                 datetime.now().isoformat(timespec="seconds"), depth,
                 cover.minutes, len(cover.taught), len(cover.short),
                 len(cover.unreachable)))

    def videos(self, wordlist: str, build: str) -> tuple[str, ...]:
        from state import open_state                   # noqa: PLC0415
        with open_state(self._path) as conn:
            return tuple(r[0] for r in conn.execute(
                "SELECT video_id FROM video_cover WHERE list = ? AND build = ?"
                " ORDER BY position", (wordlist, build)))

    def about(self, wordlist: str, build: str) -> dict | None:
        """What was stored, and when — or None if nothing was."""
        from state import open_state                   # noqa: PLC0415
        with open_state(self._path) as conn:
            row = conn.execute(
                "SELECT stamp, made_at, depth, minutes, covered, short,"
                " unreachable FROM video_cover_meta WHERE list = ? AND build = ?",
                (wordlist, build)).fetchone()
        if not row:
            return None
        keys = ("stamp", "made_at", "depth", "minutes", "covered", "short",
                "unreachable")
        return dict(zip(keys, row))
