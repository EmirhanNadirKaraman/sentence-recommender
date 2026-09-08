"""Rebuilding the roadmaps that already exist.

After the corpus grows, every stored roadmap over it is out of date. They are
cheap to redo — a subtitle walk is about a second — so rather than telling the
reader which command to run, the ones already there are rebuilt under the same
names and with the same settings they were built with.

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

    def refresh(self, touching: str | None = None) -> dict[str, int]:
        """Rebuild every stored roadmap, or only those over `touching`.

        Returns name -> new step count, so a caller can say what changed.
        """
        out: dict[str, int] = {}
        # Once, not once per roadmap: resolving the vocabulary runs the parser
        # over every word in the files. CorpusIndex takes a snapshot rather
        # than holding on to this, so one instance serves every walk.
        known = self._app.known_set()
        known_units = known.units
        goal_units = frozenset(self._app.goal_units)

        for label in sorted(self._store.sources()):
            builds, list_only, goals = read_label(label)
            if touching and touching not in (builds or (ALL,)):
                continue
            sentences = self._app.corpus(*builds, list_only=list_only)
            if not sentences:
                continue
            index = CorpusIndex(sentences, known)
            plan = RoadmapBuilder(
                index, self._app.priority(),
                self._app.settings.priority_weight,
                goal_units if goals else frozenset(),
            ).build()
            self._store.save(plan, label)
            out[label] = len(plan)

            now = datetime.now()
            for step in plan:
                if step.unit not in known_units:
                    self._app.card_store.add(
                        self._app.scheduler.new_card(step.unit, now))
        return out
