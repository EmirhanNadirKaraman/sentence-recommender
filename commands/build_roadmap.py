"""`build-roadmap` — run the greedy i+1 walk over the cached corpus."""
from __future__ import annotations

from datetime import datetime

from roadmap import CorpusIndex, RoadmapBuilder, RoadmapStore, UnitPriority
from roadmap.store import ALL


class BuildRoadmapCommand:
    """Produces the ordered sequence and an SRS card for every step."""

    def run(self, app, steps: int | None = None,
            builds: tuple[str, ...] = ()) -> None:
        settings = app.settings
        sentences = app.corpus(*builds)
        if not sentences:
            raise SystemExit(
                "no cached corpus for "
                + (", ".join(builds) if builds else "any build")
                + " — run `build-corpus` first"
            )

        known = app.known_set()
        print(f"corpus {len(sentences)} sentences · known set {len(known)} units")

        index = CorpusIndex(sentences, known)
        priority = UnitPriority.build(app.priority_surfaces(), sentences)
        builder = RoadmapBuilder(index, priority, settings.priority_weight)

        plan = builder.build(max_steps=steps)
        label = "+".join(sorted(builds)) if builds else ALL
        RoadmapStore(settings.state_path).save(plan, label)

        now = datetime.now()
        for step in plan:
            app.card_store.add(app.scheduler.new_card(step.unit, now))

        readable = index.readable
        print(f"roadmap [{label}]: {len(plan)} steps · {readable} sentences fully readable "
              f"at the end · {len(plan)} cards ready")
        for step in plan[:10]:
            print(f"  {step.describe()}   {step.sentence.text}")
