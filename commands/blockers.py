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

Two questions, then, and the second is the one that acts. The first half of
this report is one hop: what stands immediately in front of each stranded
goal. The second is cumulative -- buy off-list words one at a time, most
useful first, and watch what each one sets loose. Freeing a goal frees
whatever that goal was blocking, so the price of the tenth word is nothing
like the price of the first, and a list of immediate blockers cannot show it.

That cumulative list is a worklist rather than a reading: every word on it is
a word the corpus forces you to learn only because no sentence teaches the
goal without it. Write a sentence that does, and the word comes off the list.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from corpus.quality import well_formed
from roadmap import CorpusIndex, KnownSet
from roadmap.builder import RoadmapBuilder
from roadmap.reach import reachable
from vocab.entry import Unit


class BlockersCommand:
    def run(self, app, source: str = "subtitle", limit: int = 15,
            quality_only: bool = True, budget: int = 150) -> None:
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
        index = CorpusIndex(sentences, known, app.compounds)
        RoadmapBuilder(index, app.priority(), app.settings.priority_weight,
                       goals=goals, only_goals=True).build()
        # Not named `reachable`: that is the imported closure, and shadowing
        # it inside this method leaves `_price` working only because it is a
        # separate function resolving the module-level name.
        walked = index.known
        stranded = sorted(goals - walked, key=lambda u: u.key)
        print(f"  {len(walked) - len(known.units):,} reached by the walk · "
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
                missing = frozenset(s.units - walked - {goal})
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
        self._price(sentences, known, goals, reachable_now=walked,
                    budget=budget, limit=limit, compounds=app.compounds)

    @staticmethod
    def _price(sentences, known, goals, reachable_now, budget: int,
               limit: int, compounds=None) -> None:
        """What the unblocked roadmap costs, word by word, in order.

        Run once at the full budget rather than once per budget value: the
        closure is monotone, so a single pass buying `budget` words passes
        through every smaller answer on its way and can report each as it
        goes. Asking the question again for each ceiling would redo the whole
        closure every time for the same numbers.

        The ceiling is here because the curve has no natural end -- given
        enough words the walk clears almost anything, and the tail is
        thousands of words that each free one goal. What is worth reading is
        the head, where one word frees many.
        """
        bought: list[tuple[Unit, frozenset[Unit]]] = []
        reached = reachable(
            sentences, known.units, goals, budget=budget,
            compounds=compounds,
            on_buy=lambda unit, _n, freed: bought.append((unit, freed)))
        if not bought:
            print("\n  nothing off the list is needed — the walk reaches "
                  "every goal it can on its own")
            return

        free_now = len(goals & reachable_now)
        gained = len(goals & reached) - free_now
        useful = [(u, f) for u, f in bought if f]
        print(f"\n  buying up to {budget} words from outside the list:")
        print(f"  {len(bought):,} bought · {gained:,} more goals reached "
              f"({free_now:,} → {len(goals & reached):,} of {len(goals):,})")
        if useful:
            per = gained / len(useful)
            print(f"  {len(useful):,} of them freed anything at all, "
                  f"{per:.1f} goals each; the other "
                  f"{len(bought) - len(useful):,} freed nothing yet")

        print(f"\n  {'#':>3}  {'word':<26} {'frees':>5}  {'running':>7}  "
              "the goals it frees")
        running = 0
        for position, (unit, freed) in enumerate(useful[:limit], start=1):
            running += len(freed)
            names = ", ".join(sorted(g.key for g in freed)[:3])
            if len(freed) > 3:
                names += f", +{len(freed) - 3}"
            print(f"  {position:>3}. {unit.key[:24]:<26} {len(freed):>5}  "
                  f"{running:>7}  {names[:44]}")
        if len(useful) > limit:
            rest = sum(len(f) for _, f in useful[limit:])
            print(f"       … and {len(useful) - limit:,} more words "
                  f"freeing {rest:,} goals between them")
        print("\n  Each line is a sentence worth writing: teach that goal "
              "without that word\n  and the word comes off the list.")
