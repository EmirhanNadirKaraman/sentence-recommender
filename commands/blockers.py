"""`blockers` — what stands between the roadmap and the rest of the list.

The walk halts when nothing is one word away, and what is left is stranded.
The blocked page names each stranded goal and the word in its easiest
sentence; this asks the question behind that one — what would it *cost* to
free them, and is there a word that frees many.

No network. Every blocker is already in the corpus, which is the whole point:
hunting for video to discover what blocks a word pays a download for something
the cached sentences already say. Search is for the leaves this report finds,
not for walking the graph.

Cost is counted in strangers, not in hops. A blocker that is itself on the
study list will be taught anyway once it is reachable, so crossing it costs
nothing but ordering; a blocker that is not on the list is vocabulary you
never chose, and learning it is the actual price.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from corpus.quality import well_formed
from roadmap import CorpusIndex, KnownSet
from roadmap.builder import RoadmapBuilder
from vocab.entry import Unit


class BlockersCommand:
    def run(self, app, source: str = "subtitle", limit: int = 15,
            quality_only: bool = True) -> None:
        # Strict, not narrowed. `list_only` throws every non-goal away before
        # the index is built, which erases exactly what this report exists to
        # find: the first version used it and reported 250 goals as never said
        # when the corpus says 98 of them, because the strangers blocking the
        # rest had been narrowed out of existence.
        sentences = app.corpus(source, strict=True)
        if quality_only:
            sentences = [s for s in sentences if well_formed(s.text)]
        known = app.known_set()
        goals = frozenset(app.goal_units)
        print(f"corpus {len(sentences):,} sentences · {len(goals):,} goals")

        # What the ordinary walk reaches, on a throwaway index: run to
        # exhaustion and everything reachable is learned, which must not be
        # mistaken for what the reader knows.
        index = CorpusIndex(sentences, known)
        RoadmapBuilder(index, app.priority(), app.settings.priority_weight,
                       goals=goals, only_goals=True).build()
        reachable = index.known
        stranded = sorted(goals - reachable, key=lambda u: u.key)
        print(f"  {len(reachable) - len(known.units):,} reached by the walk · "
              f"{len(stranded):,} stranded\n")

        holding: dict[Unit, list] = defaultdict(list)
        for s in sentences:
            for u in s.units:
                holding[u].append(s)

        # For each stranded goal, the cheapest sentence to make teachable, and
        # what learning it would cost in words that are not on the list.
        need: dict[Unit, frozenset[Unit]] = {}
        silent: list[Unit] = []
        for goal in stranded:
            best: frozenset[Unit] | None = None
            for s in holding.get(goal, ()):
                missing = frozenset(s.units - reachable - {goal})
                if best is None or len(missing) < len(best):
                    best = missing
            if best is None:
                silent.append(goal)      # no sentence here says it at all
            else:
                need[goal] = best

        by_cost = Counter(len(v) for v in need.values())
        print(f"  {'extra words needed':<22} {'goals':>6}")
        for cost in sorted(by_cost):
            print(f"  {cost:<22} {by_cost[cost]:>6}")
        print(f"  {'not said here at all':<22} {len(silent):>6}   only video reaches these")
        if quality_only:
            print("  (well-formed sentences only — some of those are said in "
                  "sentences this filter drops)")

        # The leverage: one word that frees several.
        frees: dict[Unit, set[Unit]] = defaultdict(set)
        for goal, blockers in need.items():
            for b in blockers:
                frees[b].add(goal)
        ranked = sorted(frees.items(), key=lambda kv: -len(kv[1]))
        print(f"\n  words that appear in the most blocking sets:")
        print(f"  {'word':<34} {'frees':>5}  on the list?")
        for unit, freed in ranked[:limit]:
            if len(freed) < 2:
                break
            print(f"  {unit.key[:32]:<34} {len(freed):>5}  "
                  f"{'goal' if unit in goals else 'stranger'}")
        alone = sum(1 for _, f in ranked if len(f) == 1)
        print(f"\n  {alone:,} words each free exactly one goal — no leverage there")
