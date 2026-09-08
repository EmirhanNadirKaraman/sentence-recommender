"""`build-roadmap` — run the greedy i+1 walk over the cached corpus.

Two modes. Without `--goals` the walk goes wherever the corpus is easiest,
making as many sentences readable as it can. With `--goals` it has a
destination: teach the list in `data/final_result.txt`, taking ordinary steps
only when they are needed to unblock the next goal.
"""
from __future__ import annotations

from datetime import datetime

from roadmap import CorpusIndex, RoadmapBuilder, RoadmapStore
from roadmap.store import ALL


class BuildRoadmapCommand:
    """Produces the ordered sequence and an SRS card for every step."""

    def run(self, app, steps: int | None = None,
            builds: tuple[str, ...] = (), goals: bool = False) -> None:
        settings = app.settings
        sentences = app.corpus(*builds)
        if not sentences:
            raise SystemExit(
                "no cached corpus for "
                + (", ".join(builds) if builds else "any build")
                + " — run `build-corpus` first"
            )

        known = app.known_set()
        targets = frozenset(app.goal_units) if goals else frozenset()
        print(f"corpus {len(sentences)} sentences · known set {len(known)} units"
              + (f" · aiming at {len(targets):,} goals" if goals else ""))

        index = CorpusIndex(sentences, known)
        builder = RoadmapBuilder(index, app.priority(),
                                 settings.priority_weight, targets)

        plan = builder.build(max_steps=steps)
        label = "+".join(sorted(builds)) if builds else ALL
        if goals:
            label = f"{label}:goals"
        RoadmapStore(settings.state_path).save(plan, label)

        now = datetime.now()
        for step in plan:
            app.card_store.add(app.scheduler.new_card(step.unit, now))

        print(f"roadmap [{label}]: {len(plan)} steps · {index.readable} sentences "
              f"fully readable at the end · {len(plan)} cards ready")
        if goals:
            reached = sum(1 for s in plan if s.unit in targets)
            print(f"  {reached} of them are goals; {len(plan) - reached} are "
                  "steps taken to unblock one")
            print(f"  {len(targets & known.units):,} goals were already known; "
                  f"{len(targets) - len(targets & known.units) - reached:,} "
                  "remain out of reach in this corpus")
        for step in plan[:10]:
            mark = " *" if goals and step.unit in targets else "  "
            print(f" {mark}{step.describe()}   {step.sentence.text}")
