"""Experiment 1 — are better examples already available, unused?

The roadmap picks one sentence to illustrate each step, from all the
sentences in which that unit is the only unknown at that moment. The picker
takes the shortest, which under study-list counting means the shortest above
the five-word floor.

The question this answers is whether that is a *choice* problem or a
*material* problem: if most steps have a well-formed sentence among their
candidates and the picker simply passed over it, then better examples cost
nothing but a better rule. If they do not, no ranking can help and the walk
itself would have to be restricted — which costs coverage.
"""
from __future__ import annotations

from roadmap import CorpusIndex, KnownSet, RoadmapBuilder

from corpus.quality import score, well_formed


class Recorder(RoadmapBuilder):
    """A walk that notes what it could have shown as well as what it did."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.rows: list[dict] = []

    def _example(self, positions):
        texts = [self._index.sentence(p).text for p in positions]
        chosen = super()._example(positions)
        best = max(texts, key=score) if texts else ""
        self.rows.append({
            "candidates": len(texts),
            "well_formed": sum(1 for t in texts if well_formed(t)),
            "chosen": chosen.text,
            "chosen_score": score(chosen.text),
            "best": best,
            "best_score": score(best) if best else 0.0,
        })
        return chosen


def run(app, source: str = "subtitle"):
    sentences = app.corpus(source, list_only=True)
    index = CorpusIndex(sentences, KnownSet(app.known_set().units))
    walk = Recorder(index, app.priority(), app.settings.priority_weight,
                    frozenset(app.goal_units))
    walk.build()
    return walk.rows
