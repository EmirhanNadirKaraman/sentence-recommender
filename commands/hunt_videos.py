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

from config import Settings
from corpus import CorpusUpdater
from ingest import VideoHunter, VideoIngestor
from ingest.attempts import AttemptLog
from ingest.searches import SearchLog
from corpus.quality import well_formed
from roadmap import (CorpusIndex, RoadmapBuilder, RoadmapRefresher,
                     RoadmapStore)
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
        # The book `add-videos` has always kept, and the hunt never opened.
        log = AttemptLog(app.settings.state_path)
        searches = SearchLog(app.settings.state_path)
        hunter = VideoHunter(ingestor, log)
        if rounds > 1:
            settled = len(log.settled())
            if settled:
                print(f"{settled:,} videos settled by an earlier run "
                      "will not be offered again")

        known = app.known_set()
        carried = None
        for round_number in range(1, rounds + 1):
            print(f"\n── round {round_number} of {rounds} " + "─" * 30)
            # The previous round worked this out already, from the same corpus
            # against the same known set. Asking again was a second exhaustive
            # walk per round for an answer that could not have changed.
            stuck = carried if carried is not None else self._stranded(
                app, source, known, quality_only)
            carried = None
            if absent_only:
                stuck = self._never_said(app, source, stuck)
            if not stuck:
                print("  nothing is stranded — the roadmap reaches everything.")
                return
            print(f"  {len(stuck):,} things this corpus cannot teach; "
                  f"looking for video that says the most common of them")

            # A word that has been looked for and not found steps aside
            # so the next one gets a turn. Ten rounds once searched the same
            # six terms while fifty-five other stranded words were never
            # looked for at all, because `gather` stops as soon as it has
            # enough candidates and the list is always in the same order.
            turn, waiting = searches.rota(stuck)
            if waiting:
                print(f"  {waiting:,} already looked for without luck are "
                      "waiting their turn again")
            hunt = hunter.gather([u for u, _ in turn[:batch * 3]], batch)
            searches.record(hunt.tried)
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

            self._corpus_changed()     # new video, so the cache is stale
            caught = CorpusUpdater(app).catch_up(source)
            print(f"  {caught.report()}")
            for label, steps in sorted(
                RoadmapRefresher(app).refresh(touching=source).items()
            ):
                print(f"  roadmap [{label}]: {steps} steps")
            after = self._stranded(app, source, known, quality_only)
            if absent_only:
                # The same filter, or the round compares the absent list it
                # chased against the whole stranded set and reports a rout.
                after = [(u, n) for u, n in after
                         if not app.corpus_store.unit_counts(source)
                         .get((u.kind, u.key), 0)]
            carried = after            # the next round starts from here
            closed = len(stuck) - len(after)
            print(f"  stranded: {len(stuck):,} → {len(after):,} "
                  f"({closed:,} fewer)" if closed >= 0
                  else f"  stranded: {len(stuck):,} → {len(after):,} "
                       f"({-closed:,} more)")

    _corpus: tuple[str, list] | None = None

    @classmethod
    def _cached_corpus(cls, app, source: str) -> list:
        """The corpus, loaded once per run rather than once per question.

        Measured: of the 105 seconds an answer took, 36 were this and under
        two were everything else — the index, the stored plan, the walk. The
        walk was 0.0s, which is worth writing down because it is where the
        obvious optimisation goes and it would have bought nothing.

        Dropped when a round adds video, since that is the only thing that
        changes what is here.
        """
        if cls._corpus is None or cls._corpus[0] != source:
            cls._corpus = (source, app.corpus(source, list_only=True))
        return cls._corpus[1]

    @classmethod
    def _corpus_changed(cls) -> None:
        cls._corpus = None

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
    def _stranded(app, source: str, known=None, quality_only: bool = False,
                  counting: str = "list", unblock: bool = False
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

        Two things keep it from being the slowest part of a round, both
        borrowed from the page that asks the same question. A stored plan is
        replayed rather than re-derived — roadmaps are built to exhaustion, so
        the walk below usually has nothing left to do. And the walk is held to
        goals: left to itself it spends its time learning words nobody asked
        for and then reports them as reachable, which is two minutes an answer
        for a worse answer.
        """
        sentences = HuntVideosCommand._cached_corpus(app, source)
        if not sentences:
            raise SystemExit(f"no cached corpus for {source!r}")
        if quality_only:
            sentences = [s for s in sentences if well_formed(s.text)]
        spare = CorpusIndex(sentences, known or app.known_set())
        goals = frozenset(app.goal_units)
        store = RoadmapStore(app.settings.state_path)
        stored = store.sources()
        # Named for the list this process is aimed at, like every other
        # reader of a stored plan. It composed the label from the source
        # alone until now, so a run aimed at another list replayed the
        # default list's plan. Measured both ways before changing it: the
        # answers were identical, because the walk below runs to exhaustion
        # and what a corpus can reach does not depend on the head start it
        # was given. Corrected because it is wrong, not because it moved.
        named = app.settings.goal_words.stem
        tail = "" if named == Settings().goal_words.stem else f":{named}"
        here = "list" if counting == "list" else "strict"
        wanted = [f"{source}:good:{here}:goals{tail}",
                  f"{source}:{here}:goals{tail}"]
        if unblock:
            wanted = [f"{name}:unblock" for name in wanted] + wanted
        for label in wanted:
            if label in stored:
                for step in store.load(label):
                    spare.learn(step.unit)
                break
        RoadmapBuilder(spare, app.priority(), app.settings.priority_weight,
                       goals=goals, only_goals=True).build(max_steps=WALK_LIMIT)
        reached = spare.known

        # Goals only, said out loud. Narrowed counting gave this for free
        # by discarding every non-goal before the index was built, so the
        # intersection read as redundant — but under strict counting the
        # sentences keep every word, and without it this reports the whole
        # unknown corpus: 25,137 entries led by `äh`, `ähm` and `'n`.
        appearances: Counter = Counter()
        for sentence in sentences:
            for unit in (sentence.units - reached) & goals:
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
