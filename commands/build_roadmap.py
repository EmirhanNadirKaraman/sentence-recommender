"""`build-roadmap` — run the greedy i+1 walk over the cached corpus.

Two modes. Without `--goals` the walk goes wherever the corpus is easiest,
making as many sentences readable as it can. With `--goals` it has a
destination: teach the list in `data/final_result.txt`, taking ordinary steps
only when they are needed to unblock the next goal.
"""
from __future__ import annotations

from datetime import datetime

from corpus.quality import well_formed
from roadmap import CorpusIndex, RoadmapBuilder, RoadmapStore
from roadmap.store import ALL, current_stamp


class BuildRoadmapCommand:
    """Produces the ordered sequence and an SRS card for every step."""

    @staticmethod
    def _report(steps: int, readable: int) -> None:
        """Say where the walk has got to.

        A walk over the larger corpora runs for minutes with nothing on the
        screen, which makes a slow one look like a hung one. Flushed, because
        this is usually being read through a pipe or a log.
        """
        print(f"  … {steps:,} steps · {readable:,} sentences readable",
              flush=True)

    def run(self, app, steps: int | None = None, builds: tuple[str, ...] = (),
            goals: bool = False, list_only: bool = False,
            quality_only: bool = False, strict: bool = False) -> None:
        settings = app.settings
        # Strict counting only makes sense aimed at the list: it leaves the
        # words the list will never teach in the sentences, and the walk has
        # to know which units it is allowed to take.
        if strict:
            goals = True
        sentences = app.corpus(*builds, list_only=list_only, strict=strict)
        if quality_only:
            # Teach only from sentences worth reading. Costs coverage —
            # a word said once, badly, becomes unreachable — so the
            # blocked list is the price and `hunt --quality` is how it
            # gets paid down.
            before = len(sentences)
            sentences = [s for s in sentences if well_formed(s.text)]
            print(f'well-formed only: {len(sentences):,} of {before:,} sentences')
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
                                 settings.priority_weight, targets,
                                 only_goals=strict,
                                 video_minutes=app.video_minutes)

        plan = builder.build(max_steps=steps, on_progress=self._report)
        label = "+".join(sorted(builds)) if builds else ALL
        if quality_only:
            label = f"{label}:good"
        if strict:
            label = f"{label}:strict"
        elif list_only:
            label = f"{label}:list"
        if goals:
            label = f"{label}:goals"
        # Stamped with what built it, so the reading page can tell whether
        # the decks stored with these steps still describe a corpus that
        # exists — they name their sentences by text alone.
        RoadmapStore(settings.state_path).save(plan, label, current_stamp(),
                                              len(sentences))

        now = datetime.now()
        app.card_store.add_many(
            [app.scheduler.new_card(step.unit, now) for step in plan])

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
