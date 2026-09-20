"""`build-roadmap` — run the greedy i+1 walk over the cached corpus.

Two modes. Without `--goals` the walk goes wherever the corpus is easiest,
making as many sentences readable as it can. With `--goals` it has a
destination: teach the list in `data/final_result.txt`, taking ordinary steps
only when they are needed to unblock the next goal.
"""
from __future__ import annotations

from datetime import datetime

from config import Settings
from corpus.quality import well_formed
from roadmap import CorpusIndex, RoadmapBuilder, RoadmapStore
from roadmap.store import ALL, current_stamp


class BuildRoadmapCommand:
    """Produces the ordered sequence and an SRS card for every step."""

    @staticmethod
    def _report(steps: int, readable: int, last=None) -> None:
        """Say where the walk has got to, and what it just taught.

        A walk over the larger corpora runs for minutes with nothing on the
        screen, which makes a slow one look like a hung one. Flushed, because
        this is usually being read through a pipe or a log.

        The word and its sentence come too. A count says the walk is moving;
        it does not say whether it is moving somewhere sensible, and that is
        the thing a reader actually wants to know while waiting -- an opening
        full of oddities is visible immediately rather than after an hour.
        """
        head = f"  … {steps:>6,} steps · {readable:>7,} readable"
        if last is None:
            print(head, flush=True)
            return
        text = last.sentence.text if last.sentence else ""
        if len(text) > 62:
            text = text[:59] + "…"
        print(f"{head}   {last.unit.key:<26} {text}", flush=True)

    def run(self, app, steps: int | None = None, builds: tuple[str, ...] = (),
            goals: bool = False, list_only: bool = False,
            quality_only: bool = False, strict: bool = False,
            relax: bool = False, unblock: bool = False,
            beginner: bool = False) -> None:
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
        if beginner:
            # What someone opening this for the first time knows: the
            # function words and nothing else. The ordinary seed also carries
            # `known_words.txt` and whatever the reader has marked while
            # reading, which is this reader's vocabulary rather than a new
            # one's -- a plan built on it teaches nobody but them.
            #
            # Measured before it was offered: 86 units instead of 131, and it
            # costs one goal out of 4,002 (`belieben`). The plan is longer
            # because more has to be taught, which is the point.
            known = app.beginner_set()
        targets = frozenset(app.goal_units) if goals else frozenset()
        print(f"corpus {len(sentences)} sentences · known set {len(known)} units"
              + (f" · aiming at {len(targets):,} goals" if goals else ""))

        index = CorpusIndex(sentences, known, app.compounds)
        # Strict counting holds the walk to the list: it may only teach
        # goals, never an ordinary word that happens to stand in the way.
        # That is a real question — what can this list teach using nothing
        # but itself — but it is not the only one, and the page implies the
        # other when it prefers the strict plan. `--unblock` asks that one.
        builder = RoadmapBuilder(index, app.priority(),
                                 settings.priority_weight, targets,
                                 only_goals=strict and not unblock,
                                 relax=relax,
                                 video_minutes=app.video_minutes,
                                 verdicts=app.verdicts(),
                                 judged=app.judged)

        plan = builder.build(max_steps=steps, on_progress=self._report,
                             every=50)
        label = "+".join(sorted(builds)) if builds else ALL
        if quality_only:
            label = f"{label}:good"
        if strict:
            label = f"{label}:strict"
        elif list_only:
            label = f"{label}:list"
        if goals:
            label = f"{label}:goals"
            # Which list it aims at, when it is not the default one. Left off
            # for the default so every plan built before this stays findable
            # under the name it was stored with.
            named = settings.goal_words.stem
            if named != Settings().goal_words.stem:
                label = f"{label}:{named}"
        if beginner:
            label = f"{label}:beginner"
        if unblock:
            # Before `:relax` and after the list name, which is the order
            # `read_label` unwinds them in.
            label = f"{label}:unblock"
        if relax:
            # Last, because `read_label` strips suffixes off the end in the
            # reverse of the order they are appended and the list name is
            # already the tail. Without this a relaxed build stored under the
            # plain build's name, and `save` deletes what the name held — so
            # running the documented flag destroyed the plan it was meant to
            # improve on.
            label = f"{label}:relax"
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
        if index.granted:
            # Almost all of these are earned during the walk rather than at
            # the seed: a reader starting from function words alone knows
            # neither `krank` nor `Haus`, so `Krankenhaus` is free only once
            # the walk has taught both. Counted here because it is the whole
            # measure of the compound list -- steps that did not have to be
            # taken.
            print(f"  {len(index.granted):,} more words came free from their "
                  "parts, and cost no step")
        if goals:
            reached = sum(1 for s in plan if s.unit in targets)
            print(f"  {reached} of them are goals; {len(plan) - reached} are "
                  "steps taken to unblock one")
            # Measured against what the index knows at the *end*, not the
            # starting set. A goal covered by its own parts is neither a plan
            # step nor in the seed, so subtracting the two counted it as out
            # of reach -- reporting the compound work as a loss precisely
            # where it worked.
            free = targets & index.granted
            print(f"  {len(targets & known.units):,} goals were already known; "
                  f"{len(free):,} came free from their parts; "
                  f"{len(targets - index.known):,} "
                  "remain out of reach in this corpus")
        for step in plan[:10]:
            mark = " *" if goals and step.unit in targets else "  "
            print(f" {mark}{step.describe()}   {step.sentence.text}")
