"""`add-videos` — scrape a list of YouTube videos into the catalogue.

The same work as `add-video`, done for many. Ids come from a file, from
standard input, or from another database on this server that happens to hold
a list of them.

Each video is attempted independently: one with no German subtitles, or one
YouTube has withdrawn, is reported and skipped rather than stopping the run.
The corpus is analysed once at the end rather than after each, since the
incremental update finds every new video in one pass.
"""
from __future__ import annotations

import sys
from pathlib import Path

from commands.add_video import AddVideoCommand
from corpus import CorpusUpdater
from config import DatabaseConfig
from db import Database
from ingest import VideoIngestor
from ingest.attempts import AttemptLog
from ingest.channel import CHANNEL_ID
from roadmap import RoadmapRefresher


class AddVideosCommand:
    def run(self, app, source: str, language: str | None = None,
            dry_run: bool = False, limit: int = 0) -> None:
        ids = self._collect(app, source, limit)
        ingestor = VideoIngestor(app.settings, app.analyzer)
        log = AttemptLog(app.settings.state_path)
        # Two reasons to pass a video over: it is already in the catalogue, or
        # it was tried and settled. Without the second, every run re-listed
        # the channel and re-fetched the metadata of the same refusals — most
        # of the work, and the reason an interrupted import had to start its
        # channel again rather than carry on.
        done = log.settled()
        fresh = [v for v in ids
                 if not ingestor.already_have(v) and v not in done]
        if done:
            print(f"  {len(done):,} videos settled by an earlier run "
                  "are being skipped")

        print(f"{len(ids)} ids, {len(fresh)} not yet in the catalogue")
        if dry_run:
            print("  (dry run — nothing will be fetched or written)")
            for video_id in fresh:
                print(f"    {video_id}")
            return
        if not fresh:
            return

        added, refused = [], []
        for index, video_id in enumerate(fresh, start=1):
            print(f"  [{index}/{len(fresh)}] {video_id} … ", end="", flush=True)
            try:
                landed = ingestor.add(video_id, language)
            except SystemExit as why:
                refused.append((video_id, str(why)))
                log.record(video_id, AttemptLog.classify(str(why)), str(why))
                print("skipped")
                continue
            except Exception as error:          # noqa: BLE001 — one bad video
                refused.append((video_id, f"{type(error).__name__}: {error}"))
                log.record(video_id, "error", f"{type(error).__name__}: {error}")
                print("failed")
                continue
            log.record(video_id, "added")
            added.append(landed)
            print(f"{landed.lines} lines, {landed.language}")

        print(f"\n{len(added)} added, {len(refused)} skipped")
        settled = log.counts()
        if settled:
            print("  attempts on record: " + ", ".join(
                f"{k} {v:,}" for k, v in sorted(settled.items())))
        for video_id, why in refused:
            print(f"  {video_id}: {why.splitlines()[0]}")

        if added:
            print("\nanalysing the new videos…", flush=True)
            caught = CorpusUpdater(app).catch_up()
            print(f"  {caught.teachable} sentences to study from, "
                  f"{caught.context} more for the overlay")
            for label, steps in sorted(
                RoadmapRefresher(app).refresh(touching="subtitle").items()
            ):
                print(f"  roadmap [{label}]: {steps} steps")

    @staticmethod
    def _collect(app, source: str, limit: int = 0) -> list[str]:
        """Video ids from a channel, a file, standard input, or `lexy`."""
        # Matched, not merely contained: a file called UCLA-words.txt is a
        # file, and a bare word is a filename before it is a handle.
        if (source.startswith("@")
                or CHANNEL_ID.fullmatch(source)
                or "youtube.com/@" in source
                or "youtube.com/channel/" in source
                or "youtube.com/c/" in source):
            from ingest import ChannelLister    # noqa: PLC0415
            lister = ChannelLister()
            channel = lister.identify(source)
            print(f"listing {channel}…", flush=True)
            return lister.videos(channel, limit)
        if source == "lexy":
            # Another database on the same server keeps a list of ids. It has
            # no titles or languages, so anything not in German is found out
            # only by trying it.
            with Database(DatabaseConfig.named("lexy")) as db:
                return db.column("SELECT DISTINCT video_id FROM youtube_video"
                                 " WHERE video_id <> '' ORDER BY video_id")
        if source == "-":
            return [line.strip() for line in sys.stdin if line.strip()]
        path = Path(source)
        if not path.exists():
            raise SystemExit(f"no such file: {source} (or use 'lexy' or '-')")
        return [AddVideoCommand._identify(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")]
