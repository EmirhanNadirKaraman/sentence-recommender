"""`hunt` — find and add video for the words the corpus cannot teach.

One round: work out what is stranded, search for video that says the most
frequent of those words, add what has German subtitles, analyse only the new
material, rebuild the roadmaps, and report whether the stranded set shrank.

Repeating it is the whole point, so `--rounds` does that, and every round
prints its own numbers rather than only a total.
"""
from __future__ import annotations

from collections import Counter

from corpus import CorpusUpdater
from ingest import VideoHunter, VideoIngestor
from roadmap import CorpusIndex, RoadmapBuilder, RoadmapRefresher
from vocab.entry import Unit

# Ceiling on the walk behind the stranded set, so a huge corpus cannot stall
# a round before it starts.
WALK_LIMIT = 20_000


class HuntVideosCommand:
    def run(self, app, batch: int = 10, rounds: int = 1,
            source: str = "subtitle", dry_run: bool = False) -> None:
        ingestor = VideoIngestor(app.settings, app.analyzer)
        hunter = VideoHunter(ingestor)

        known = app.known_set()
        for round_number in range(1, rounds + 1):
            print(f"\n── round {round_number} of {rounds} " + "─" * 30)
            stuck = self._stranded(app, source, known)
            if not stuck:
                print("  nothing is stranded — the roadmap reaches everything.")
                return
            print(f"  {len(stuck):,} things this corpus cannot teach; "
                  f"looking for video that says the most common of them")

            hunt = hunter.gather([u for u, _ in stuck[:batch * 3]], batch)
            print(f"  searched {', '.join(hunt.searched[:6])}"
                  f"{' …' if len(hunt.searched) > 6 else ''}")
            print(f"  {len(hunt.candidates)} videos not already held")
            if dry_run:
                for video_id in hunt.candidates:
                    print(f"    {video_id}")
                return
            if not hunt.candidates:
                print("  nothing new found — try a larger batch.")
                return

            hunter.take(hunt, say=lambda *a, **k: print(*a, **k, flush=True))
            print(f"  {len(hunt.added)} added, {len(hunt.refused)} without "
                  "German subtitles")
            if not hunt.added:
                continue

            caught = CorpusUpdater(app).catch_up(source)
            print(f"  {caught.teachable} new sentences to study from")
            for label, steps in sorted(
                RoadmapRefresher(app).refresh(touching=source).items()
            ):
                print(f"  roadmap [{label}]: {steps} steps")
            after = self._stranded(app, source, known)
            closed = len(stuck) - len(after)
            print(f"  stranded: {len(stuck):,} → {len(after):,} "
                  f"({closed:,} fewer)" if closed >= 0
                  else f"  stranded: {len(stuck):,} → {len(after):,} "
                       f"({-closed:,} more)")

    @staticmethod
    def _stranded(app, source: str, known=None) -> list[tuple[Unit, int]]:
        """Every goal the roadmap cannot reach, most worth chasing first.

        Two kinds, and the second is much the larger. Some goals are in the
        corpus but never alone in a sentence; far more are simply never said
        here at all — 298 against 1,859 when this was written. Chasing only
        the first would leave the bulk of the list untouched, so both are
        returned, the present ones first because a video that isolates a word
        already in play pays off immediately.

        The walk runs on a throwaway index: taken to exhaustion it learns
        everything reachable, and that must not look like the reader knows it.
        """
        sentences = app.corpus(source, list_only=True)
        if not sentences:
            raise SystemExit(f"no cached corpus for {source!r}")
        spare = CorpusIndex(sentences, known or app.known_set())
        RoadmapBuilder(spare, app.priority(),
                       app.settings.priority_weight).build(max_steps=WALK_LIMIT)
        reached = spare.known

        appearances: Counter = Counter()
        for sentence in sentences:
            for unit in sentence.units - reached:
                appearances[unit] += 1
        present = appearances.most_common()

        # Goals the corpus never says. Ordered by the study list, which is
        # the only ranking they have — nothing here has seen them.
        priority = app.priority()
        # Only what material could actually fix. A goal the analyser has never
        # emitted anywhere cannot be taught by any video, and the study list
        # ranks several of those near the top — they would head this queue for
        # ever, sending the hunt after words that cannot be matched.
        producible = app.producible
        missing = sorted(
            (u for u in app.goal_units
             if u not in reached and u not in appearances and u in producible),
            key=lambda u: -priority.of(u),
        )
        return present + [(unit, 0) for unit in missing]
