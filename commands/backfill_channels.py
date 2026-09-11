"""`backfill-channels` — say which channel each video came from.

`video.channel_id` was written as NULL until 8e7a146, so 1,117 of 1,382 rows
do not know where they came from — every one of them German, since the
non-German rows arrived from upstream with theirs already set. Nothing stored
can supply it: the channel was never written down, so each video needs one
metadata call to YouTube.

That call already returns what is needed. `fetch_video_metadata` hands back
`channel_id` and `channel_name` beside the title, and `upsert_channel` turns
them into a row id without disturbing a name already recorded.

The whole difficulty is pace. Five metadata calls five seconds apart drew
"The page needs to be reloaded" from YouTube on 2026-09-11, and cookies do
not help — they answer the sign-in wall, not burst throttling. So this is
built to be interrupted: each video is committed as it lands, nothing is
batched, and the work left is always `WHERE channel_id IS NULL` rather than a
position in a queue. Stopping it costs the video in flight and nothing else.

A failure is never recorded as an answer. The scraper returns None for every
failure alike, so a throttled request and a deleted video look identical from
here, and writing "this video has no channel" on that basis would be a
permanent verdict from a temporary refusal — the mistake that wrote off nine
videos this morning. Failures leave the row NULL, to be tried again.
"""
from __future__ import annotations

from time import perf_counter, sleep

from db import WritableDatabase
from ingest import ChannelLister

# Long enough that YouTube does not start refusing. Five seconds was not, so
# this is deliberately unhurried: the job is resumable and nobody is waiting
# on it, which makes a slow success worth more than a fast throttle.
DELAY = 15.0

# Consecutive failures that mean "stop asking". A throttle refuses everything
# while it lasts, so a run of failures is weather rather than a property of
# these particular videos, and continuing only deepens it.
GIVE_UP = 5


class BackfillChannelsCommand:
    def run(self, app, limit: int = 0, delay: float = DELAY,
            give_up: int = GIVE_UP, dry_run: bool = False) -> None:
        settings = app.settings
        with WritableDatabase(settings.own) as db:
            cur = db.cursor()
            cur.execute("SELECT count(*) FROM video WHERE channel_id IS NULL")
            outstanding = cur.fetchone()[0]
            cur.execute(
                "SELECT video_id, title FROM video WHERE channel_id IS NULL"
                " ORDER BY video_id" + (" LIMIT %s" if limit else ""),
                (limit,) if limit else None)
            todo = cur.fetchall()

            print(f"{outstanding:,} videos have no channel"
                  + (f"; taking {len(todo):,}" if limit else ""))
            if not todo:
                print("  nothing to do — every video knows its channel")
                return
            if dry_run:
                print(f"  (dry run — {delay:.0f}s apart would take"
                      f" {len(todo) * delay / 60:.0f} minutes)")
                for video_id, title in todo[:10]:
                    print(f"    {video_id}  {(title or '')[:56]}")
                return

            pipeline = ChannelLister().pipeline
            filled, failed, run_of_failures = 0, 0, 0
            started = perf_counter()

            for index, (video_id, title) in enumerate(todo, start=1):
                if index > 1:
                    sleep(delay)
                meta = pipeline.fetch_video_metadata(video_id)
                youtube_id = ((meta or {}).get("channel_id") or "").strip()
                if not youtube_id:
                    # Could be a deleted video, could be a refusal. The
                    # scraper cannot tell us which, so neither can we, and
                    # the row stays NULL for a later run.
                    failed += 1
                    run_of_failures += 1
                    print(f"  [{index}/{len(todo)}] {video_id} … no answer",
                          flush=True)
                    if run_of_failures >= give_up:
                        print(f"\n  {run_of_failures} refusals in a row — "
                              "stopping rather than pressing on.")
                        break
                    continue

                run_of_failures = 0
                channel_id = pipeline.upsert_channel(
                    cur, youtube_id, (meta.get("channel_name") or "").strip(),
                    None)
                cur.execute("UPDATE video SET channel_id = %s"
                            " WHERE video_id = %s", (channel_id, video_id))
                # Per video, so an interrupted run keeps what it earned.
                db.connection.commit()
                filled += 1
                print(f"  [{index}/{len(todo)}] {video_id} … "
                      f"{(meta.get('channel_name') or '?')[:40]}", flush=True)

            cur.execute("SELECT count(*) FROM video WHERE channel_id IS NULL")
            left = cur.fetchone()[0]
            spent = perf_counter() - started
            print(f"\n{filled:,} filled, {failed:,} unanswered,"
                  f" {left:,} still without a channel  ({spent / 60:.1f}m)")
            if left:
                print(f"  run it again to continue — the work left is"
                      f" whatever is still NULL, not a position in a queue.")
