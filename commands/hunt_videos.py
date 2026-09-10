"""`hunt` — find and add video for the words the corpus cannot teach.

One round: work out what is stranded, search for video that says the most
frequent of those words, add what has German subtitles, analyse only the new
material, rebuild the roadmaps, and report whether the stranded set shrank.

Repeating it is the whole point, so `--rounds` does that, and every round
prints its own numbers rather than only a total.
"""
from __future__ import annotations

import re

from collections import Counter

from corpus import CorpusUpdater
from ingest import VideoHunter, VideoIngestor
from corpus.quality import well_formed
from roadmap import CorpusIndex, RoadmapBuilder, RoadmapRefresher
from vocab.entry import Unit

# Ceiling on the walk behind the stranded set, so a huge corpus cannot stall
# a round before it starts.
WALK_LIMIT = 20_000


# The slot markers a blueprint is built from; none of them is the word.
_SLOTS = frozenset({"jdm.", "jdn.", "etw.", "sich", "etw./jdn.", "jdn./etw.",
                    "jdm./etw.", "jds./etw.", "an", "auf", "in", "mit", "zu",
                    "für", "über", "um", "bei", "aus", "von", "/", "als", "nach"})


def _search_terms(unit) -> list[str]:
    """Every word a goal could be found by — `Gläubiger`, not `der Gläubiger`.

    Articles and case markers are dropped and the last word kept, which for a
    verb blueprint is the verb and for an article-noun pair the noun.

    A list, not one word, because an entry may name alternatives: `gucken,
    kucken`, `heraus, raus`. The corpus saying either one satisfies the goal,
    so all of them have to be checked. Taking only the last sent the hunt
    after `kucken` — which nobody writes — in every round of a five-round
    run, while `gucken` was in the corpus the whole time.
    """
    out = []
    for part in unit.key.split(","):
        key = re.sub(r"^\s*(der|die|das)\s+", "", part.strip())
        key = re.sub(r"\s*\([^)]*\)\s*", " ", key)
        words = [w for w in key.split() if w not in _SLOTS]
        if words:
            out.append(words[-1])
    return out or [unit.key]


class HuntVideosCommand:
    def run(self, app, batch: int = 10, rounds: int = 1,
            source: str = "subtitle", dry_run: bool = False,
            quality_only: bool = False, absent_only: bool = False) -> None:
        ingestor = VideoIngestor(app.settings, app.analyzer)
        hunter = VideoHunter(ingestor)

        known = app.known_set()
        for round_number in range(1, rounds + 1):
            print(f"\n── round {round_number} of {rounds} " + "─" * 30)
            stuck = self._stranded(app, source, known, quality_only)
            if absent_only:
                stuck = self._never_said(app, source, stuck)
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
            after = self._stranded(app, source, known, quality_only)
            closed = len(stuck) - len(after)
            print(f"  stranded: {len(stuck):,} → {len(after):,} "
                  f"({closed:,} fewer)" if closed >= 0
                  else f"  stranded: {len(stuck):,} → {len(after):,} "
                       f"({-closed:,} more)")

    @staticmethod
    def _never_said(app, source: str, stuck: list) -> list:
        """Only the goals the corpus does not contain at all.

        `_stranded` returns two kinds and puts the present ones first, on the
        argument that a video isolating a word already in play pays off at
        once. That is sound in principle and was wrong in the case that sent
        us here: the top of the queue was `nennen`, said 264 times and never
        alone, and the reason was not scarcity but that the study list named
        the verb twice. Ten downloads would have bought nothing.

        A word never said at all is different. There is no sentence to fix, so
        a video that says it creates the first one. Whether that sentence is
        i+1 is another matter — but it cannot be, today, and after it exists
        it can.
        """
        counts = app.corpus_store.unit_counts(source)
        absent = [(u, n) for u, n in stuck
                  if not counts.get((u.kind, u.key), 0)]
        print(f"  {len(stuck):,} stranded, of which {len(absent):,} are never "
              "said here at all — chasing only those")
        return absent

    @staticmethod
    def _stranded(app, source: str, known=None, quality_only: bool = False
                  ) -> list[tuple[Unit, int]]:
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
        if quality_only:
            sentences = [s for s in sentences if well_formed(s.text)]
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
        #
        # Skipping the ones whose word is already here. A goal can be
        # unreachable for two quite different reasons, and only one of them
        # is a shortage of material: `das Pro` is stranded because *Pro* only
        # ever turns up as the preposition or inside `Pro-Account`, and `das
        # stimmt` because the matcher sees the verb. No video fixes either,
        # yet the hunt ranked `das Pro` first and spent a round fetching a
        # CapCut tutorial. Twenty-three of the hundred and seven are like
        # this. Full word boundaries, and case kept: *Bär* must not be
        # satisfied by *Bären*.
        # Presence only disqualifies a word when the pool is every sentence.
        # Under the quality restriction a word can be said a hundred times and
        # still be unreachable, because none of those sentences was worth
        # learning from — and that is precisely what a new video can fix.
        said = "" if quality_only else "\n".join(
            s.text for s in app.corpus(source, list_only=False))
        priority = app.priority()
        missing = sorted(
            (u for u in app.goal_units
             if u not in reached and u not in appearances
             and not any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", said)
                         for w in _search_terms(u))),
            key=lambda u: -priority.of(u),
        )
        return present + [(unit, 0) for unit in missing]
