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

from roadmap.builder import RoadmapBuilder
from roadmap.index import CorpusIndex
from roadmap.store import ALL, RoadmapStore

GOALS = ":goals"
LIST = ":list"


def read_label(label: str) -> tuple[tuple[str, ...], bool, bool]:
    """A roadmap's name, back into the settings that made it."""
    goals = label.endswith(GOALS)
    if goals:
        label = label[: -len(GOALS)]
    list_only = label.endswith(LIST)
    if list_only:
        label = label[: -len(LIST)]
    builds = () if label == ALL else tuple(label.split("+"))
    return builds, list_only, goals


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

        for label in sorted(self._store.sources()):
            builds, list_only, goals = read_label(label)
            if touching and touching not in (builds or (ALL,)):
                continue
            sentences = self._app.corpus(*builds, list_only=list_only)
            if not sentences:
                continue
            index = CorpusIndex(sentences, known)

            done = [] if rebuild else self._store.load(label)
            for step in done:
                index.learn(step.unit)

            fresh = RoadmapBuilder(
                index, priority,
                self._app.settings.priority_weight,
                goal_units if goals else frozenset(),
            ).build(
                first_position=len(done) + 1,
                on_progress=(lambda n, readable, label=label:
                             progress(label, len(done) + n, readable))
                if progress else None,
            )

            if rebuild:
                self._store.save(fresh, label)
            else:
                self._store.append(fresh, label)
            out[label] = len(fresh)

            # Only the new steps mint cards: the rest already have theirs,
            # from whichever run first planned them.
            now = datetime.now()
            self._app.card_store.add_many([
                self._app.scheduler.new_card(step.unit, now)
                for step in fresh if step.unit not in known_units
            ])
        return out
