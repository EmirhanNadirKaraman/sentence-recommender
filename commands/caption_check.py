"""`caption-check` — what auto-generated captions would cost, measured.

Ingest accepts only hand-written subtitles, because ASR mangles exactly the
endings a learner is studying. That policy has never been tested, and manual
tracks are the scarce thing: most of what `hunt` finds is thrown away for
lacking one.

The ground truth is free. Every video in the catalogue already has a manual
track, and most also carry a machine one. Fetch the machine track, run it
through the same corrector and analyser, and compare the *unit sets* — units
are what the roadmap consumes, so a caption that loses one is a caption that
cannot teach it.

Which track counts as "the machine one" matters. YouTube offers auto
captions in 150-odd languages for a popular video, and all but one are
machine translations of the ASR. `de-orig` is the original-language
transcript; a bare `de` beside a hundred others is a translation into
German, and measuring that would answer a question nobody asked. So
`de-orig` wins where it exists, and a bare `de` is accepted only when the
video's own audio is German.
"""
from __future__ import annotations

import time

from alignment import SubtitleAligner
from corpus import MergeCorrector
from corpus.sentence import RawLine
from db import Database

PAUSE = 1.5
ORIGINAL = ("de-orig", "de-DE", "de")


def _options() -> dict:
    """Cookieless, like language-app's fetcher tries first.

    It uses a client that needs no n-challenge. Attaching cookies without
    `js_runtimes` and `remote_components` answers every video with "The page
    needs to be reloaded", which this project's own attempt log already
    records as throttling wearing a verdict's clothes.
    """
    return {"quiet": True, "no_warnings": True, "skip_download": True}


def machine_track(video_id: str) -> tuple[str, list[RawLine]] | tuple[None, None]:
    """The ASR track for one video, as raw lines — or nothing."""
    import requests                              # noqa: PLC0415
    import yt_dlp                                # noqa: PLC0415

    with yt_dlp.YoutubeDL(_options()) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False)
    autos = info.get("automatic_captions") or {}
    audio = (info.get("language") or "").lower()

    chosen = None
    for key in ORIGINAL:
        if key not in autos:
            continue
        # A bare `de` among many languages is the translation pipeline.
        if key == "de" and "de-orig" not in autos and not audio.startswith("de"):
            continue
        chosen = key
        break
    if not chosen:
        return None, None

    entry = next((e for e in autos[chosen] if e.get("ext") == "json3"), None)
    if not entry:
        return None, None
    payload = requests.get(entry["url"], timeout=60).json()

    lines: list[RawLine] = []
    for number, event in enumerate(payload.get("events") or []):
        segments = event.get("segs") or []
        text = "".join(s.get("utf8", "") for s in segments).strip()
        if not text:
            continue
        start = (event.get("tStartMs") or 0) / 1000
        lines.append(RawLine(
            sentence_id=-(number + 1),          # negative: never a real row
            video_id=video_id,
            start_time=start,
            duration=(event.get("dDurationMs") or 0) / 1000,
            content=text,
            # Empty: the column exists because `sentence` has one, and
            # neither the corrector nor the aligner reads it.
            tokens=(),
        ))
    return chosen, lines


class CaptionCheckCommand:
    def run(self, app, limit: int = 20, source: str = "subtitle",
            pause: float = PAUSE) -> None:
        settings = app.settings
        by_video: dict[str, list] = {}
        for sentence in app.corpus(source, strict=True):
            if sentence.timing:
                by_video.setdefault(sentence.timing.video_id, []).append(sentence)
        if not by_video:
            raise SystemExit(f"no aligned corpus for {source!r}")

        with Database(settings.own) as db:
            titles = dict(db.rows("SELECT video_id, title FROM video"))

        wanted = sorted(by_video, key=lambda v: -len(by_video[v]))[:limit]
        print(f"{len(wanted)} videos, manual track already held\n", flush=True)

        corrector, aligner = MergeCorrector(), SubtitleAligner()
        rows = []
        for number, video in enumerate(wanted, start=1):
            head = f"  [{number}/{len(wanted)}] {video}"
            try:
                track, lines = machine_track(video)
            except Exception as error:            # noqa: BLE001 — one bad video
                print(f"{head}  failed: {type(error).__name__}", flush=True)
                time.sleep(pause)
                continue
            if not lines:
                print(f"{head}  no original-language auto track", flush=True)
                time.sleep(pause)
                continue

            auto = aligner.align(lines, corrector.correct(lines))
            auto = app.analyzer.analyze_all(auto)
            mine = {u for s in by_video[video] for u in s.units}
            theirs = {u for s in auto for u in s.units}
            kept = len(mine & theirs) / len(mine) if mine else 0.0
            rows.append((video, track, len(mine), len(theirs), kept))
            print(f"{head}  {track:<8} manual {len(mine):>5} units · "
                  f"auto {len(theirs):>5} · keeps {100 * kept:>5.1f}%  "
                  f"{(titles.get(video) or '')[:26]}", flush=True)
            time.sleep(pause)

        if not rows:
            raise SystemExit("nothing to compare")
        kept = sum(r[4] for r in rows) / len(rows)
        gained = sum(r[3] for r in rows) / sum(r[2] for r in rows)
        print(f"\n{len(rows)} videos compared")
        print(f"  the machine track keeps {100 * kept:.1f}% of the units the "
              "hand-written one yields")
        print(f"  and yields {gained:.2f} units for every one of theirs")
        print("  units, not words: a unit the roadmap never sees is a unit it "
              "cannot teach.")
