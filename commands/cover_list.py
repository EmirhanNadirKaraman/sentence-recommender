"""`cover` — the fewest minutes of video that teach a saved list.

A roadmap says what order to learn in. This says what to watch: the cheapest
set of videos in which every word on a list has enough sentences where it is
the only unknown.

Only worth asking of a list someone built by hand. For the 4,007-unit default
study list the answer is most of the catalogue with a price on it, which is
true and useless — see TODO 10.
"""
from __future__ import annotations

from db import Database
from roadmap import CorpusIndex
from roadmap.cover import DEPTH, VideoCoverStore, audit, solve, supply
from roadmap.store import current_stamp


class CoverListCommand:
    def run(self, app, source: tuple[str, ...] = (), depth: int = DEPTH,
            floor: int | None = None, dry_run: bool = False) -> None:
        settings = app.settings
        builds = tuple(source) or ("subtitle",)
        build = "+".join(builds)
        goals = frozenset(app.goal_units)
        if not goals:
            raise SystemExit("no goals — name a list with --goals-list or "
                             "--goals-file")

        print(f"loading {build}…", flush=True)
        sentences = app.corpus(*builds, strict=True)
        if not sentences:
            raise SystemExit(f"nothing cached for {build}")
        index = CorpusIndex(sentences, app.known_set())
        minutes = app.video_minutes
        print(f"  {len(sentences):,} sentences · {len(goals):,} goals · "
              f"{len(minutes):,} videos timed", flush=True)

        kwargs = {} if floor is None else {"floor": floor}
        held = supply(index, sentences, goals, minutes, **kwargs)
        cover = solve(index, sentences, goals, minutes, depth=depth, **kwargs)

        # The solver says the model was satisfied. This says the answer is
        # right, by counting the chosen videos again without asking it.
        wrong = audit(cover, held, depth)
        if wrong:
            raise SystemExit(
                f"the cover does not hold: {len(wrong)} words short, "
                f"first {wrong[0]}")

        with Database(settings.own) as db:
            titles = dict(db.rows("SELECT video_id, title FROM video"))

        print(f"\ncover [{settings.goal_words.stem} · {build}]: "
              f"{len(cover.videos)} videos, {cover.minutes:,.0f} minutes "
              f"({cover.hours:.1f} hours)")
        print(f"  {cover.status} in {cover.seconds:.1f}s, "
              f"{len(cover.taught):,} of {len(goals):,} goals covered")
        if cover.short:
            print(f"  {len(cover.short)} the corpus cannot teach {depth} deep:")
            for unit, (want, _) in sorted(cover.short.items(),
                                          key=lambda kv: kv[0].key)[:8]:
                print(f"      {unit.key:<30} only {want}")
        if cover.unreachable:
            print(f"  {len(cover.unreachable)} with no timed video at all:")
            for unit in cover.unreachable[:8]:
                print(f"      {unit.key}")

        for position, video in enumerate(cover.videos[:12], start=1):
            teaches = sum(1 for vs in cover.taught.values() if video in vs)
            print(f"  {position:>3}. {minutes[video]:>5.0f}m  {teaches:>3} words"
                  f"  {(titles.get(video) or video)[:44]}")
        if len(cover.videos) > 12:
            print(f"       … and {len(cover.videos) - 12} more")

        if dry_run:
            print("\n  (dry run — nothing stored)")
            return
        VideoCoverStore(settings.state_path).save(
            cover, settings.goal_words.stem, build, current_stamp(), depth)
        print(f"\n  stored against {settings.goal_words.stem} · {build}")
