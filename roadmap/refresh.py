"""Bringing the roadmaps that already exist up to date.

After the corpus grows, every stored roadmap over it is short: the new
sentences teach things the old walk never had material for. The ones already
there are extended under the same names and with the same settings they were
built with.

Extended, not rebuilt. A walk over ninety thousand subtitle sentences is
minutes, and almost all of it re-derives steps the reader has already worked
through — and worse, renumbers them, so the word that was step 400 yesterday
is somewhere else today. Replaying the stored plan into the index costs a
dictionary update per step and leaves the walk standing exactly where it
stopped, so only the tail is actually computed.

The trade is that the existing order is taken as settled. A new video can
make an early step cheaper, and extending will not go back and reshuffle for
it; `refresh(rebuild=True)` is there for when that is what you want.

Those settings live in the name: `subtitle:llm:list:goals` is the
`subtitle:llm` corpus, counting only the study list, aiming at it. The two
flags are only ever appended, so they can be read off the end without
confusing `:llm` for one of them.
"""
from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from corpus.quality import well_formed
from roadmap.builder import RoadmapBuilder
from roadmap.index import CorpusIndex
from config import Settings
from roadmap.store import ALL, RoadmapStore, current_stamp

GOALS = ":goals"
LIST = ":list"
GOOD = ":good"
STRICT = ":strict"


class Plan(NamedTuple):
    """The settings a roadmap's name carries.

    A NamedTuple because this has grown a field twice and read as a bare
    tuple both times — `builds, list_only, goals = read_label(...)` says
    nothing about what it dropped when a fourth arrived.
    """

    builds: tuple[str, ...]
    list_only: bool
    goals: bool
    quality_only: bool
    strict: bool
    # Which word list, when it is not the default. Last because a
    # NamedTuple will not take a defaulted field before an undefaulted one.
    goal_list: str = ""


def read_label(label: str) -> Plan:
    """A roadmap's name, back into the settings that made it.

    Read off the end in the reverse of the order they are appended, so
    `subtitle:good:list:goals` comes back as the `subtitle` corpus, counting
    only the study list, aiming at it, and taught from well-formed sentences
    alone.

    `:good` used to be left on the front half, which made the corpus name
    `subtitle:good` — a build that does not exist. Every refresh therefore
    loaded nothing for the quality roadmap and skipped it, silently, which is
    the one roadmap the reading page actually serves.
    """
    # A word list other than the default appends its name after `:goals`,
    # which has to come off before the suffixes are read — they are stripped
    # from the end in a fixed order, so a name left on the tail makes the very
    # first test fail and the whole chain go unparsed. That happened: a B1
    # plan was read as an unrestricted walk over a build named after the
    # entire label, and a refresh appended 23,957 steps to a 2,016-goal plan.
    goal_list = ""
    marker = GOALS + ":"
    if marker in label:
        label, _, goal_list = label.partition(marker)
        label += GOALS

    goals = label.endswith(GOALS)
    if goals:
        label = label[: -len(GOALS)]
    list_only = label.endswith(LIST)
    if list_only:
        label = label[: -len(LIST)]
    strict = label.endswith(STRICT)
    if strict:
        label = label[: -len(STRICT)]
    quality_only = label.endswith(GOOD)
    if quality_only:
        label = label[: -len(GOOD)]
    builds = () if label == ALL else tuple(label.split("+"))
    return Plan(builds, list_only, goals, quality_only, strict, goal_list)


class RoadmapRefresher:
    """Rebuilds stored roadmaps in place, each on its own terms."""

    def __init__(self, app) -> None:
        self._app = app
        self._store = RoadmapStore(app.settings.state_path)

    def refresh(self, touching: str | None = None, rebuild: bool = False,
                progress=None) -> dict[str, int]:
        """Extend every stored roadmap, or only those over `touching`.

        Returns name -> how many steps it grew by, so a caller can say what
        changed. `rebuild` discards each plan and walks again from the start,
        which is what to do when the analyser changed rather than the corpus.

        `progress(label, steps, readable)` is called as each walk advances.
        A walk over a large corpus runs for minutes saying nothing, which
        makes a slow one look exactly like a stuck one.
        """
        out: dict[str, int] = {}
        # Once, not once per roadmap: resolving the vocabulary runs the parser
        # over every word in the files. CorpusIndex takes a snapshot rather
        # than holding on to this, so one instance serves every walk.
        known = self._app.known_set()
        known_units = known.units
        goal_units = frozenset(self._app.goal_units)
        # Also once: ranking the goal list is seconds, and every roadmap
        # ranks it the same way.
        priority = self._app.priority()

        # Which list this process is aimed at, so plans built for another one
        # can be left alone. Refreshing them here would extend a plan with
        # goals it was never about.
        active = self._app.settings.goal_words.stem
        default = Settings().goal_words.stem
        for label in sorted(self._store.sources()):
            plan = read_label(label)
            wants = plan.goal_list or default
            if plan.goals and wants != active:
                continue
            builds, list_only = plan.builds, plan.list_only
            if touching and touching not in (builds or (ALL,)):
                continue
            sentences = self._app.corpus(*builds, list_only=list_only,
                                         strict=plan.strict)
            # Before the count below, not after: the length recorded with the
            # roadmap is the denominator the reading page shows progress
            # against, and it has to be the slice the walk was actually
            # given.
            if plan.quality_only:
                sentences = [s for s in sentences if well_formed(s.text)]
            if not sentences:
                continue
            index = CorpusIndex(sentences, known)

            done = [] if rebuild else self._store.load(label)
            for step in done:
                index.learn(step.unit)

            fresh = RoadmapBuilder(
                index, priority,
                self._app.settings.priority_weight,
                goal_units if plan.goals else frozenset(),
                only_goals=plan.strict,
                video_minutes=self._app.video_minutes,
            ).build(
                first_position=len(done) + 1,
                on_progress=(lambda n, readable, label=label:
                             progress(label, len(done) + n, readable))
                if progress else None,
            )

            # Stamped with what built it: the stored decks name their
            # sentences by text alone, so a roadmap outlives the corpus that
            # produced them without any outward sign.
            if rebuild:
                self._store.save(fresh, label, current_stamp(),
                                 len(sentences))
            else:
                self._store.append(fresh, label, current_stamp(),
                                   len(sentences))
            out[label] = len(fresh)

            # Only the new steps mint cards: the rest already have theirs,
            # from whichever run first planned them.
            now = datetime.now()
            self._app.card_store.add_many([
                self._app.scheduler.new_card(step.unit, now)
                for step in fresh if step.unit not in known_units
            ])
        return out
