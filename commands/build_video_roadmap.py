"""`build-video-roadmap` — what order to watch them in."""
from __future__ import annotations

from collections import defaultdict

from db import Database
from fingerprint import analyser_fingerprint
from roadmap.videos import VideoRoadmapStore, VideoWalk
from vocab.channel_taste import ChannelTaste
from watchability import taste_weight


class BuildVideoRoadmapCommand:
    @staticmethod
    def _report(steps: int, known: int) -> None:
        print(f"  … {steps} videos · {known:,} units known", flush=True)

    def run(self, app, source: str = "subtitle",
            floor: int = 40, steps: int | None = None) -> None:
        settings = app.settings
        grouped: dict[str, list] = defaultdict(list)
        for sentence in app.corpus(source, strict=True):
            if sentence.timing:
                grouped[sentence.timing.video_id].append(sentence)
        if not grouped:
            raise SystemExit(
                f"no aligned subtitles in '{source}' — run `build-corpus` first")

        # Length and title come from the catalogue rather than the score cache,
        # because this is a build-time command and the cache may be empty or
        # stale; the walk needs a length for every video it ranks.
        with Database(settings.own) as db:
            minutes = {v: secs / 60 for v, secs in db.rows(
                "SELECT video_id, duration FROM video WHERE duration IS NOT NULL")}
            titles = dict(db.rows("SELECT video_id, title FROM video"))
            # Which channel each video came from, so what the reader has said
            # about a channel can settle two videos that teach the same.
            channel = dict(db.rows(
                "SELECT v.video_id, c.youtube_channel_id FROM video v"
                " JOIN channel c ON c.id = v.channel_id"
                " WHERE c.youtube_channel_id IS NOT NULL"))

        said = ChannelTaste(settings.state_path).all()
        taste = {video: taste_weight(said.get(channel.get(video)))
                 for video in grouped}
        chosen = sum(1 for w in taste.values() if w != 1.0)

        known = frozenset(app.known_set().units)
        print(f"{len(grouped)} videos · {len(known):,} units known", flush=True)

        if chosen:
            print(f"  {chosen:,} of them are on a channel you have an opinion "
                  f"about, out of {len(said):,} channels", flush=True)
        walk = VideoWalk(grouped, known, minutes, titles, floor=floor,
                         taste=taste)
        plan = walk.build(max_steps=steps, on_progress=self._report)
        if not plan:
            raise SystemExit("nothing here teaches anything — every video's "
                             "sentences need two or more new words")

        VideoRoadmapStore(settings.state_path).save(
            plan, source, analyser_fingerprint())

        taught = len(walk.known) - len(known)
        print(f"\nvideo roadmap [{source}]: {len(plan)} videos in order")
        print(f"  {plan[0].readable_after:,} sentences readable after the first,"
              f" {plan[-1].readable_after:,} after the last")
        print(f"  {taught:,} words it expects to teach along the way")
        print(f"  {len(grouped) - len(plan):,} videos teach nothing and are "
              "left out")
        for step in plan[:10]:
            length = f"{step.minutes:.0f}m" if step.minutes else "  ?"
            print(f"  * {step.position:>3}. {length:>4} {step.teaches:>4} "
                  f"sentences  {step.rate:>4.1f}/min  "
                  f"{(step.title or step.video)[:44]}")
