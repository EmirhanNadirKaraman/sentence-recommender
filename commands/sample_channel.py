"""`sample-channel` — what a channel would give, before taking it.

Ingest accepts only hand-written subtitles, and whether a channel has them
is the single fact that decides whether importing it is worth hours. Finding
out by importing costs one metadata fetch per video and, worse, records an
attempt against every one it touches — three of those settle a video for
good, so a throttled run can write off a channel it never actually read.

This asks the cheap question instead: list the channel, and probe a handful
for a manual track.

**Spread, never the head.** Kurzgesagt was sampled twice from the top of its
listing and both samples said 20-25%; the real rate was 85%. MrWissen2go was
the same error inverted — its newest videos run 68-84%, which is why the
catalogue holds 400 of them, while the 526 older ones have no manual track
at all. A listing is newest-first and a channel's newest uploads are not its
typical ones, so the sample is taken at even intervals across the whole
thing. A rate read off the head describes the head.

What it cannot tell you is how good the German is. That is `caption-check`
and `difficulty`, and they need the video in hand.
"""
from __future__ import annotations

import time

from ingest.attempts import AttemptLog
from ingest.options import scrape
from ingest.video import VideoIngestor

PAUSE = 1.0


def spread(items: list[str], count: int) -> list[str]:
    """`count` items at even intervals, ends included.

    The whole point of the command: `items[:count]` is the sampling that has
    been wrong twice.
    """
    if count >= len(items):
        return list(items)
    if count <= 1:
        return items[:1]
    return [items[round(i * (len(items) - 1) / (count - 1))]
            for i in range(count)]


class SampleChannelCommand:
    """Probe a channel's manual-subtitle rate without importing it."""

    def run(self, app, channel: str, sample: int = 12,
            language: str = "de", pause: float = PAUSE) -> None:
        import yt_dlp                            # noqa: PLC0415 — heavy

        from ingest import ChannelLister         # noqa: PLC0415

        lister = ChannelLister()
        found = lister.identify(channel)
        print(f"listing {found}…", flush=True)
        ids = lister.videos(found, 0)
        if not ids:
            raise SystemExit(f"{channel}: nothing listed — check the handle")

        ingestor = VideoIngestor(app.settings, app.analyzer)
        path = app.settings.state_path
        settled = AttemptLog(path).settled()
        tried = AttemptLog(path).attempted()
        held = [v for v in ids if ingestor.already_have(v)]
        rest = [v for v in ids if v not in held]
        # Three ways to be unheld, and collapsing them overstates the channel.
        # A video already tried and failed is not an opportunity: it is a
        # failure waiting to settle. Asked of MrWissen2go, the first version
        # of this called 527 videos "new" and estimated 66 usable ones, when
        # 526 of them had already been tried and refused and the 527th was a
        # single upload from that morning.
        done = [v for v in rest if v in settled]
        again = [v for v in rest if v not in settled and v in tried]
        fresh = [v for v in rest if v not in settled and v not in tried]

        print(f"{len(ids):,} listed · {len(held):,} already held · "
              f"{len(done):,} written off · {len(again):,} tried and failed · "
              f"{len(fresh):,} never tried")
        if not fresh and not again:
            print("  nothing left to ask about — this channel is exhausted")
            return

        # Prefer the never-tried pool: it is the only one that answers "what
        # would importing this give me". Fall back to the failures only when
        # there is nothing else, and say which pool the rate describes.
        pool, what = (fresh, "never tried") if fresh else (again, "already failed once")
        picks = spread(pool, sample)
        print(f"  probing {len(picks)} spread evenly across the {len(pool):,}"
              f" {what}\n", flush=True)

        opts = scrape(app.settings)
        opts.update(quiet=True, no_warnings=True)
        have, failed = 0, 0
        for index, video_id in enumerate(picks, start=1):
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(
                        f"https://www.youtube.com/watch?v={video_id}",
                        download=False)
            except Exception as error:           # noqa: BLE001 — one bad video
                failed += 1
                print(f"  {index:>3}. {video_id}  could not read: "
                      f"{type(error).__name__}")
                continue
            manual = sorted(info.get("subtitles") or {})
            wanted = [m for m in manual if m.startswith(language)]
            have += bool(wanted)
            mark = ",".join(wanted) if wanted else "—"
            print(f"  {index:>3}. {video_id}  {mark:<10} "
                  f"{(info.get('title') or '')[:46]}")
            if index < len(picks):
                time.sleep(pause)

        read = len(picks) - failed
        print()
        if not read:
            raise SystemExit(
                "every probe failed — that is the request being refused, not "
                "the channel being empty. Check cookies_browser and try again.")
        rate = have / read
        print(f"{have} of {read} probed have hand-written {language} "
              f"subtitles ({rate:.0%})")
        if failed:
            print(f"  {failed} could not be read and are not counted")
        print(f"  at that rate the {len(pool):,} {what} hold roughly "
              f"{round(rate * len(pool)):,} usable videos")
        if again and pool is fresh:
            print(f"  the {len(again):,} that already failed are not counted; "
                  "they will be retried until they settle")
        # A small sample of a lopsided channel is still a guess. Say so with
        # the number rather than leaving the reader to remember it.
        if read < 10:
            print("  — on fewer than ten probes, treat that as a hint")
