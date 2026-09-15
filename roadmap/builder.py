"""The greedy i+1 walk.

At every step the builder looks at the units that are the single unknown in
some sentence, and picks the one worth teaching next:

    score = gain + priority_weight * priority   (+ a bonus, if it is a goal)

`gain` counts sentences the step moves forward — those it makes fully readable
now, plus those it brings down to one unknown (the lookahead).  `priority`
comes from UnitPriority and breaks the many ties: corpus gains are small, so
without it the walk would wander into rare vocabulary that happens to unlock
one more sentence.

With a goal list the walk has a destination instead of just a direction. A
goal outscores anything that is not one, so the walk teaches goals whenever a
goal is i+1, and falls back to ordinary steps only to unblock the next one.
"""
from __future__ import annotations

from heapq import nsmallest

from corpus.quality import score as quality, variety
from corpus.sentence import Sentence
from roadmap.examples import DECK_SIZE, gaps_by_video, rank
from roadmap.index import CorpusIndex
from roadmap.priority import UnitPriority
from roadmap.step import RoadmapStep
from vocab.entry import Unit

# Large enough that no combination of gain and priority can outweigh it: gains
# run to a few dozen and priority contributes at most `priority_weight`. A
# goal that is reachable is always taken before a step that is not a goal.
GOAL_BONUS = 10_000.0


class RoadmapBuilder:
    def __init__(
        self,
        index: CorpusIndex,
        priority: UnitPriority,
        priority_weight: float = 3.0,
        goals: frozenset[Unit] = frozenset(),
        only_goals: bool = False,
        relax: bool = False,
        video_minutes: dict[str, float] | None = None,
        verdicts: dict[str, float] | None = None,
    ) -> None:
        self._index = index
        self._verdicts = verdicts
        self._priority = priority
        self._weight = priority_weight
        self._goals = goals
        # Strict counting leaves the words the list will never teach in the
        # sentences, so they turn up on the frontier like anything else. The
        # walk has to refuse them by name, or it starts teaching `Klausur`
        # to make a sentence readable that the reader never asked to read.
        self._only_goals = only_goals
        self._relax = relax
        # Video lengths, so a step opens on a clip you might actually watch
        # rather than eighty minutes into a film. A tie-break inside the deck
        # ranking; see `roadmap.examples.rank`.
        self._minutes = video_minutes
        # And how hard each video is around the sentence, which is the other
        # half of the same question: a sentence can be perfectly i+1 and sit
        # in a video where every other line is hopeless. Measured against the
        # vocabulary the walk starts from rather than re-measured per step —
        # it is banded to whole words, and no single step moves a video's
        # average by one.
        self._gaps = gaps_by_video(
            (index.sentence(p) for p in range(len(index))), index.known)

    @property
    def goals(self) -> frozenset[Unit]:
        return self._goals

    def build(self, max_steps: int | None = None, first_position: int = 1,
              on_progress=None, every: int = 500) -> list[RoadmapStep]:
        """The walk, from wherever the index currently stands.

        `first_position` numbers the steps for a walk that continues an
        existing roadmap rather than starting one, so the returned steps can
        be appended to it without renumbering what the reader has already
        worked through.

        `on_progress(steps, readable, last)` is called every `every` steps,
        `last` being the step just taken -- a count alone says the walk is
        moving but not what it is doing, and what it is doing is the
        interesting part. A walk
        over a large corpus runs for minutes with nothing to show for itself,
        which makes a slow one indistinguishable from a stuck one; this is
        the only way to tell from outside that it is still moving.
        """
        steps: list[RoadmapStep] = []
        while max_steps is None or len(steps) < max_steps:
            step = self._next_step(first_position + len(steps))
            if step is None and self._relax:
                # The wall, not a preference: nothing anywhere is one word
                # away. Only here does the walk take two from one sentence.
                step = self._relaxed_step(first_position + len(steps))
            if step is None:
                break
            steps.append(step)
            self._index.learn(step.unit)
            if step.beside is not None:
                self._index.learn(step.beside)
            if on_progress and len(steps) % every == 0:
                on_progress(len(steps), self._index.readable,
                            steps[-1])
        return steps

    def peek(self, position: int = 1, exclude: frozenset = frozenset(),
             kinds: frozenset = frozenset()) -> RoadmapStep | None:
        """The step the walk would take next, without taking it.

        Lets a reader be shown what is i+1 *right now* — recomputed against
        whatever they have marked known since — rather than a position in a
        sequence planned earlier.  `exclude` passes over units the reader has
        set aside without claiming to know them; `kinds`, when given, narrows
        to one sort of unit, since grammar and vocabulary are not always what
        you want on the same day.
        """
        return self._next_step(position, exclude, kinds)

    def _next_step(self, position: int, exclude: frozenset = frozenset(),
                   kinds: frozenset = frozenset()) -> RoadmapStep | None:
        # One pass, keeping the best rather than materialising every score:
        # the frontier runs to thousands of units and this is the innermost
        # loop of the whole walk. `key` still breaks ties reproducibly, and
        # `>` keeps the first of equals exactly as `max` did.
        best: tuple[Unit, set[int], int, float] | None = None
        for unit, positions in self._index.candidates().items():
            if not positions or unit in exclude:
                continue
            if self._only_goals and unit not in self._goals:
                continue
            if kinds and unit.kind not in kinds:
                continue
            gain, score = self._score(unit, positions)
            if best is None or (score, unit.key) > (best[3], best[0].key):
                best = (unit, positions, gain, score)
        if best is None:
            return None
        unit, sentences, gain, score = best
        return RoadmapStep(
            position=position,
            unit=unit,
            sentence=self._example(sentences),
            gain=gain,
            score=score,
            now_readable=len(sentences),
            examples=self._deck(unit, sentences),
            readable=self._index.readable,
            occurrences=len(self._index.containing(unit)),
        )

    def _deck(self, unit: Unit, positions: set[int]) -> tuple[Sentence, ...]:
        """The sentences a reader will be stepped through for this unit.

        Chosen during the walk rather than when the step is read, so the page
        can be served from the stored roadmap with no corpus in memory. The
        known set it ranks against is the walk's own at this step, which is
        exactly what a reader following the plan knows when they arrive — so
        the deck is the one they would have been given, not a stale one.

        Ordinarily it reaches past `positions` — the sentences where this unit
        is the only unknown — into the rest, because the median unit is the
        sole unknown in one or two sentences and a deck of one cannot be
        stepped through. The page says what else is new in each, so the i+1
        claim stays honest while there is still somewhere to go next.

        Strict counting is the case where that trade is the wrong way round.
        There, every word in a sentence counts, and the whole promise is that
        nothing in it is unknown but the step — so the deck stops at
        `positions`, however short that leaves it. Reaching further would
        offer exactly the sentences the mode exists to exclude.

        `nsmallest` rather than sorting: a common unit appears in a couple of
        thousand sentences and only the first two dozen are ever shown. Like
        `sorted`, it keeps the first of equals.
        """
        known = self._index.known
        found = positions if self._only_goals else self._index.containing(unit)
        return tuple(nsmallest(
            DECK_SIZE,
            (self._index.sentence(p) for p in found),
            # Verdicts too, or the deck stored with a step would be ranked
            # differently from the one the page rebuilds — see `rank`.
            key=rank(unit, known, self._minutes, self._gaps, self._verdicts),
        ))

    def _relaxed_step(self, position: int) -> RoadmapStep | None:
        """One step where no i+1 step exists — two new words from one sentence.

        The walk halts when nothing is the sole unknown anywhere, and what is
        left is stranded for good: 254 goals on this corpus, each said only in
        sentences that hold something else unknown too. Often that something
        is not on the study list at all, so no amount of progress reaches it
        and the chain simply ends.

        Relaxing breaks the deadlock by paying two words at once. It is the
        last resort and gated as one — this runs only when `_next_step`
        returns None, so the ordering stays i+1 for as long as the corpus
        allows and a relaxed step is never *preferred* to a plain one. The
        alternative, letting the scorer weigh two-word steps against one-word
        steps throughout, degrades the whole sequence to buy the same words.

        The pair is chosen by the same score as any other step, so the
        cheapest wall to climb is the one climbed first.
        """
        best: tuple[Unit, set[int], int, float] | None = None
        for unit, positions in self._index.pairs().items():
            if not positions:
                continue
            if self._only_goals and unit not in self._goals:
                continue
            gain, score = self._score(unit, positions)
            if best is None or (score, unit.key) > (best[3], best[0].key):
                best = (unit, positions, gain, score)
        if best is None:
            return None
        unit, positions, gain, score = best
        sentence = self._example(positions)
        # The other unknown in that sentence — what learning `unit` alone
        # would have left behind, and the reason this sentence was out of
        # reach.
        beside = next((u for u in sentence.units
                       if u != unit and u not in self._index.known), None)
        if beside is None:
            return None
        return RoadmapStep(
            position=position,
            unit=unit,
            sentence=sentence,
            gain=gain,
            score=score,
            now_readable=0,
            examples=self._deck(unit, positions),
            readable=self._index.readable,
            occurrences=len(self._index.containing(unit)),
            beside=beside,
        )

    def _score(self, unit: Unit, positions: set[int]) -> tuple[int, float]:
        gain = len(positions) + self._index.unlocks(unit)
        score = gain + self._weight * self._priority.of(unit)
        if unit in self._goals:
            score += GOAL_BONUS
        return gain, score

    def _example(self, positions: set[int]) -> Sentence:
        """The best sentence teaching this unit.

        It used to take the fewest units and then the shortest text, which
        under study-list counting is a tie on the first key and therefore
        "the shortest sentence above the five-word floor" — seventy percent
        of the roadmap came out at 5-7 words, much of it `Ja, gern.`

        Ranked by `corpus.quality` instead. Measured over the whole walk,
        seventy-six percent of steps had a better sentence already among
        their candidates, a median of twelve of them, so this changes what is
        shown without touching what is learned: the candidates are the same,
        so coverage cannot move.

        Ties break on word variety, then on the text itself. Not on length:
        that was the first attempt, and it quietly rebuilt the bias the score
        exists to remove — half the roadmap landed on the shortest length the
        score still called perfect.
        """
        return max(
            (self._index.sentence(p) for p in positions),
            key=lambda s: (quality(s.text), variety(s.text), s.text),
        )
