"""`add-videos` — scrape a list of YouTube videos into the catalogue.

The same work as `add-video`, done for many. Ids come from a file, from
standard input, or from another database on this server that happens to hold
a list of them.

Each video is attempted independently: one with no German subtitles, or one
YouTube has withdrawn, is reported and skipped rather than stopping the run.
The corpus is analysed once at the end rather than after each, since the
incremental update finds every new video in one pass.

`--auto` widens what counts as subtitles: where a video has no hand-written
track, a machine one is taken if it passes the gate in
`ingest.auto_captions`. It lands in its own build, `subtitle:auto`, so
nothing that studies the hand-written corpus picks it up by accident, and
`--dry-run` beside it fetches and judges without writing — which is how to
find out what a channel would give before giving the catalogue anything.
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

# Which build a video feeds, by who wrote its subtitles. The catalogue column
# holds `manual` or `auto`; `corpus.source.BUILD_SOURCES` is the same mapping
# read the other way, and the two have to agree.
BUILD_OF = {"manual": "subtitle", "auto": "subtitle:auto"}


class AddVideosCommand:
    def run(self, app, source: str, language: str | None = None,
            dry_run: bool = False, limit: int = 0,
            accept_auto: bool = False) -> None:
        ids = self._collect(app, source, limit)
        ingestor = VideoIngestor(app.settings, app.analyzer)
        log = AttemptLog(app.settings.state_path)
        # Two reasons to pass a video over: it is already in the catalogue, or
        # it was tried and settled. Without the second, every run re-listed
        # the channel and re-fetched the metadata of the same refusals — most
        # of the work, and the reason an interrupted import had to start its
        # channel again rather than carry on.
        #
        # Which refusals settle depends on which path this is. `no-subtitles`
        # means "no hand-written track", and that is what the machine-caption
        # path is *for* — asking it to skip those would skip everything.
        done = log.settled(accept_auto)
        # De-duplicated, keeping the first mention. A list pasted together
        # from several searches repeats itself — the same video says more
        # than one word — and a repeat costs a metadata fetch to discover
        # that the second copy is already in the catalogue.
        wanted: dict[str, None] = {}
        for video in ids:
            if not ingestor.already_have(video) and video not in done:
                wanted.setdefault(video, None)
        fresh = list(wanted)
        if len(ids) != len(set(ids)):
            print(f"  {len(ids) - len(set(ids))} repeated id"
                  f"{'s' if len(ids) - len(set(ids)) != 1 else ''} in the list")
        if done:
            print(f"  {len(done):,} videos settled by an earlier run "
                  "are being skipped")

        print(f"{len(ids)} ids, {len(fresh)} not yet in the catalogue")
        if dry_run and not accept_auto:
            print("  (dry run — nothing will be fetched or written)")
            for video_id in fresh:
                print(f"    {video_id}")
            return
        if not fresh:
            return
        if dry_run:
            # A different dry run, because a different question. Which ids are
            # new is not what anyone wants to know before pointing this at a
            # channel of several hundred — what they want is how many would
            # survive the gate, and that cannot be answered without fetching
            # the track. So this one fetches and judges, and writes nothing.
            return self._survey(app, ingestor, fresh, language)

        added, refused = [], []
        for index, video_id in enumerate(fresh, start=1):
            print(f"  [{index}/{len(fresh)}] {video_id} … ", end="", flush=True)
            try:
                landed = ingestor.add(video_id, language,
                                      accept_auto=accept_auto)
            except SystemExit as why:
                refused.append((video_id, str(why)))
                # The gate says which test a track failed and carries it on
                # the exception; everything else is read back out of the
                # wording, which is all `classify` has ever had.
                log.record(video_id,
                           getattr(why, "outcome", "") or AttemptLog.classify(str(why)),
                           str(why))
                print("skipped")
                continue
            except Exception as error:          # noqa: BLE001 — one bad video
                refused.append((video_id, f"{type(error).__name__}: {error}"))
                log.record(video_id, "error", f"{type(error).__name__}: {error}")
                print("failed")
                continue
            log.record(video_id, "added")
            added.append(landed)
            print(f"{landed.lines} lines, {landed.language}, {landed.source}")
            if index % 25 == 0:
                kept = sum(1 for a in added if a.source == "auto")
                print(f"    … {index} of {len(fresh)} attempted: "
                      f"{len(added)} added ({kept} from machine captions), "
                      f"{len(refused)} skipped", flush=True)

        print(f"\n{len(added)} added, {len(refused)} skipped")
        settled = log.counts()
        if settled:
            print("  attempts on record: " + ", ".join(
                f"{k} {v:,}" for k, v in sorted(settled.items())))
        for video_id, why in refused:
            print(f"  {video_id}: {why.splitlines()[0]}")

        if added:
            print("\nanalysing the new videos…", flush=True)
            # Which builds to catch up is read off what actually landed, not
            # off the flag. `--auto` prefers a hand-written track wherever
            # there is one, so a run with it on can feed both builds, and
            # catching up only the one named by the flag would leave the
            # other's videos analysed by nobody.
            for build in sorted({BUILD_OF.get(landed.source, 'subtitle')
                                 for landed in added}):
                caught = CorpusUpdater(app).catch_up(build)
                print(f"  {build}: {caught.report()}")
                for label, steps in sorted(
                    RoadmapRefresher(app).refresh(touching=build).items()
                ):
                    print(f"  roadmap [{label}]: {steps} steps")

    @staticmethod
    def _survey(app, ingestor, fresh: list[str], language: str | None) -> None:
        """Judge every track without writing anything.

        The gate's verdicts, counted. Reported as a tally rather than a rate,
        because the rate is the thing that has been wrong here before: a
        listing is newest-first, and a channel's newest uploads are not its
        typical ones. Six lingoni videos off the head said half the channel
        was usable; an even spread of twenty-four said one in twenty-four.

        It judges the machine track and only that. A video with a
        hand-written track would be taken on that instead and never reach the
        gate, so a run against a channel that has some will understate what
        it would get — checking would double the requests to answer a
        question `sample-channel` already answers for a tenth of them.
        """
        from collections import Counter          # noqa: PLC0415
        import time                              # noqa: PLC0415

        tally: Counter = Counter()
        for index, video_id in enumerate(fresh, start=1):
            try:
                snippets, _, _, _ = ingestor.machine_transcript(
                    video_id, language or app.settings.language)
            except SystemExit as why:
                verdict = getattr(why, "outcome", "") or "unfetchable"
                tally[verdict] += 1
                print(f"  [{index}/{len(fresh)}] {video_id}  {verdict}",
                      flush=True)
            else:
                tally["ok"] += 1
                print(f"  [{index}/{len(fresh)}] {video_id}  ok, "
                      f"{len(snippets)} lines", flush=True)
            if index % 25 == 0:
                print(f"    … {index} of {len(fresh)}: {dict(tally)}",
                      flush=True)
            time.sleep(1.0)

        print(f"\n{sum(tally.values())} judged, nothing written")
        for verdict, count in tally.most_common():
            print(f"  {verdict:<18} {count:>5}")
        if tally["ok"]:
            print(f"\n  {tally['ok']} would be added. Run again without "
                  "--dry-run to take them.")

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
