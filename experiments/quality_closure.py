"""Experiment 2 — what does insisting on good examples cost in coverage?

The walk can only teach a unit through a sentence where it is the single
unknown. Restricting it to well-formed sentences shrinks that pool, so some
units become unreachable. This measures how many.

Read alongside experiment 1: a loss here only matters for the units that had
no well-formed candidate at all. A unit taught from a poor sentence in the
unrestricted walk may simply be taught later, from a better one, in the
restricted walk — the same word, differently placed.
"""
from __future__ import annotations

from roadmap import CorpusIndex, KnownSet, RoadmapBuilder

from corpus.quality import well_formed


def run(app, source: str = "subtitle"):
    everything = app.corpus(source, list_only=True)
    good = [s for s in everything if well_formed(s.text)]
    goals = frozenset(app.goal_units)
    known = app.known_set().units
    out = {}
    for label, pool in (("all sentences", everything),
                        ("well-formed only", good)):
        index = CorpusIndex(pool, KnownSet(known))
        plan = RoadmapBuilder(index, app.priority(),
                              app.settings.priority_weight, goals).build()
        out[label] = {
            "sentences": len(pool),
            "steps": len(plan),
            "reached": len(index.known - known),
        }
    out["present_units"] = len({u for s in everything for u in s.units})
    return out
