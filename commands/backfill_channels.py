"""`backfill-channels` — say which channel each video came from.

`video.channel_id` was written as NULL until 8e7a146, so most rows do not
know where they came from. Nothing stored can supply it: the channel was
never written down, so it has to be asked for.

Asked *per channel*, not per video. The obvious loop — one metadata call for
each video — pays a request for every row. But videos arrive here in clumps,
because they were scraped from channels a channel at a time, so one video's
channel usually accounts for many of the others. So: take an unattributed
video, ask which channel it belongs to, list that channel once, and attribute
every video of ours that appears in it.

Measured on three channels, 2026-09-11:

    Dinge Erklärt – Kurzgesagt   188 videos listed    25 of ours
    Deutsch mit Rieke            292 videos listed    12 of ours
    Like Germans                 300 videos listed   146 of ours

183 videos for six requests, against 183 requests one at a time. A listing
costs 10-45s where a metadata call costs 3, so it pays from the third video
a channel owns — and one of these owned a hundred and forty-six.

Built to be interrupted, because the pace is the difficulty: five requests
five seconds apart drew "The page needs to be reloaded" from YouTube on
2026-09-11, and cookies do not help — they answer the sign-in wall, not burst
throttling. Each channel commits as it lands, and the work left is always
`WHERE channel_id IS NULL` rather than a position in a queue.

A failure is never recorded as an answer. The scraper returns None for every
failure alike, so a deleted video and a throttled request are
indistinguishable here; writing "no channel" on that evidence would turn a
temporary refusal into a permanent verdict. Failures leave the row NULL.
"""
from __future__ import annotations

from time import perf_counter, sleep

from db import WritableDatabase
from ingest import ChannelLister

# Between channels, not between videos — there are far fewer of them now.
DELAY = 10.0

# Consecutive channels that told us nothing. A throttle refuses everything
# while it lasts, so a run of failures is weather rather than a property of
# these particular videos, and continuing only deepens it.
GIVE_UP = 4


class BackfillChannelsCommand:
    def run(self, app, limit: int = 0, delay: float = DELAY,
            give_up: int = GIVE_UP, dry_run: bool = False) -> None:
        with WritableDatabase(app.settings.own) as db:
            cur = db.cursor()
            cur.execute("SELECT video_id FROM video WHERE channel_id IS NULL"
                        " ORDER BY video_id")
            pending = [v for (v,) in cur.fetchall()]
            print(f"{len(pending):,} videos have no channel")
            if not pending:
                print("  nothing to do — every video knows its channel")
                return
            if dry_run:
                print(f"  (dry run — would probe {pending[0]} first, list its"
                      " channel, and attribute every video of ours in it)")
                return

            lister = ChannelLister()
            pipeline = lister.pipeline
            waiting = list(pending)
            filled = channels = refused = run_of_refusals = 0
            started = perf_counter()

            while waiting and (not limit or channels < limit):
                if channels:
                    sleep(delay)
                probe = waiting[0]
                meta = pipeline.fetch_video_metadata(probe)
                youtube_id = ((meta or {}).get("channel_id") or "").strip()
                if not youtube_id:
                    # Deleted, private, or refused — indistinguishable from
                    # here. Dropped from this run so the loop moves on, and
                    # left NULL so a later run tries it again.
                    waiting.pop(0)
                    refused += 1
                    run_of_refusals += 1
                    print(f"  {probe} … no answer", flush=True)
                    if run_of_refusals >= give_up:
                        print(f"\n  {run_of_refusals} refusals in a row — "
                              "stopping rather than pressing on.")
                        break
                    continue

                run_of_refusals = 0
                channels += 1
                name = (meta.get("channel_name") or "").strip()
                channel_id = pipeline.upsert_channel(cur, youtube_id, name, None)

                # The probe belongs to this channel whatever the listing says
                # — an unlisted video is absent from its own channel's page.
                mine = {probe}
                try:
                    mine |= set(waiting) & set(lister.videos(youtube_id, 0))
                except Exception as error:      # noqa: BLE001 — one channel
                    print(f"  {name[:34]}: listing failed"
                          f" ({type(error).__name__}); took the one video")
                cur.execute("UPDATE video SET channel_id = %s"
                            " WHERE video_id = ANY(%s)",
                            (channel_id, sorted(mine)))
                db.connection.commit()          # per channel, so a stop keeps it
                filled += len(mine)
                waiting = [v for v in waiting if v not in mine]
                print(f"  {name[:34]:<34} {len(mine):>4} videos"
                      f"   {len(waiting):,} left", flush=True)

            cur.execute("SELECT count(*) FROM video WHERE channel_id IS NULL")
            left = cur.fetchone()[0]
            spent = perf_counter() - started
            per = f", {filled / channels:.0f} per channel" if channels else ""
            print(f"\n{filled:,} videos attributed across {channels} channels"
                  f"{per}; {refused} unanswered, {left:,} still without one"
                  f"  ({spent / 60:.1f}m)")
            if left:
                print("  run it again to continue — the work left is whatever"
                      " is still NULL, not a position in a queue.")
