"""`unblock` — the smallest vocabulary that gets the roadmap moving again.

The walk halts when no sentence has exactly one unknown left. Everything
still unknown is stranded, and the question this answers is: what is the
shortest list of words you could learn from somewhere else — a dictionary, a
teacher, anywhere but this corpus — to make the rest of it reachable?

The reachable set is a monotone closure: learning something never destroys an
opportunity, so what matters is only the seed, never the order. Finding the
smallest seed is minimum target set selection, which is NP-hard, so this
approximates it the way the structure invites.

When the walk stops, its cheapest unlocks are sentences with exactly TWO
unknowns: learn either one and the other becomes i+1. Treat those as a graph
— a node per stranded unit, an edge per two-unknown sentence — and any vertex
cover unblocks all of them at once. Greedy highest-degree cover is the
standard approximation. Unblocking cascades, so the closure is recomputed and
the whole thing repeats until nothing moves.

The answer is an upper bound on the true minimum, not the minimum itself.
"""
from __future__ import annotations

from collections import Counter

from corpus.quality import well_formed
from roadmap import CorpusIndex, KnownSet, RoadmapBuilder
from vocab.entry import Unit

MAX_PASSES = 12


class UnblockCommand:
    """Approximates the minimal seed vocabulary."""

    def run(self, app, source: str = "subtitle", list_only: bool = True,
            limit: int = 40, quality_only: bool = False) -> None:
        sentences = app.corpus(source, list_only=list_only)
        if not sentences:
            raise SystemExit(f"no cached corpus for {source!r}")
        if quality_only:
            # The question changes with the pool. Over every sentence there
            # are no deadlocks at all, so the answer is always "nothing" —
            # the walk reaches whatever the corpus says. Restricted to
            # sentences worth learning from, some words are only ever spoken
            # alongside another unknown, andthat is a seed worth asking about.
            sentences = [s for s in sentences if well_formed(s.text)]
            print(f"  restricted to {len(sentences):,} well-formed sentences")
        goals = frozenset(app.goal_units)
        known = set(app.known_set().units)
        # Only what this pool can teach at all. A goal said nowhere in it is
        # not blocked, it is absent, and no amount of seeding reaches it.
        target = {u for s in sentences for u in s.units}
        seed: list[Unit] = []

        for pass_no in range(1, MAX_PASSES + 1):
            reached = self._closure(sentences, known, app)
            stranded = target - reached
            if not stranded:
                print(f"\n  nothing is stranded after {pass_no - 1} additions")
                break
            cover = self._cover(sentences, reached)
            if not cover:
                print(f"\n  pass {pass_no}: {len(stranded):,} still stranded, but no "
                      "sentence has exactly two unknowns — nothing left to unlock")
                break
            print(f"  pass {pass_no}: {len(reached):,} reachable, {len(stranded):,} "
                  f"stranded; adding {len(cover)} word(s)")
            seed.extend(cover)
            known |= set(cover)

        print(f"\n  seed vocabulary: {len(seed)} words\n")
        for unit in seed[:limit]:
            mark = " *" if unit in goals else "  "
            print(f"   {mark}{unit.kind:7} {unit.key}")
        if len(seed) > limit:
            print(f"   … and {len(seed) - limit} more")
        print(f"\n   * = already on your study list "
              f"({sum(1 for u in seed if u in goals)} of {len(seed)})")

    @staticmethod
    def _closure(sentences, known, app) -> frozenset[Unit]:
        """Everything the walk reaches from `known`, order being irrelevant."""
        index = CorpusIndex(sentences, KnownSet(frozenset(known)))
        RoadmapBuilder(index, app.priority(),
                       app.settings.priority_weight).build()
        return index.known

    @staticmethod
    def _cover(sentences, reached) -> list[Unit]:
        """A greedy vertex cover of the two-unknown graph.

        Each such sentence is an edge between its two unknowns; covering it
        makes the sentence teach whichever one is left. Highest degree first,
        which is the usual approximation and here also picks the word that
        appears in the most stuck sentences.
        """
        edges = []
        for sentence in sentences:
            missing = sentence.units - reached
            if len(missing) == 2:
                edges.append(tuple(missing))
        if not edges:
            return []
        degree = Counter(u for edge in edges for u in edge)
        cover: list[Unit] = []
        remaining = set(edges)
        while remaining:
            best = max(degree, key=lambda u: (degree[u], u.key))
            cover.append(best)
            remaining = {e for e in remaining if best not in e}
            degree = Counter(u for e in remaining for u in e)
            if not degree:
                break
        return cover
