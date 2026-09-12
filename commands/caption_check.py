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
from corpus.quality import well_formed
from db import Database
# One implementation of "which track is the machine one, and does it
# punctuate". It lives beside the ingest path that acts on the answer; this
# command only measures.
from ingest.auto_captions import (             # noqa: F401 — re-exported
    ORIGINAL, PUNCTUATED, machine_track, punctuation_rate,
)

PAUSE = 1.5


class CaptionCheckCommand:
    @staticmethod
    def _known(app):
        return app.known_set().units

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
            # Sentences, not only units. ASR writes no punctuation, and the
            # corrector finds boundaries by punctuation, so a machine track
            # collapses into one enormous "sentence" whose vocabulary looks
            # excellent and which teaches nothing. Counting units alone hid
            # that completely.
            ended = sum(1 for line in lines
                        if line.content.rstrip().endswith((".", "!", "?")))
            # The only count that decides anything: sentences a reader could
            # actually be shown. Raw totals flatter the machine by half again
            # and the bar takes it all back, because ASR over-segments.
            known = frozenset(self._known(app))
            usable_mine = sum(1 for s in by_video[video]
                              if len(s.units - known) == 1 and well_formed(s.text))
            usable_auto = sum(1 for s in auto
                              if len(s.units - known) == 1 and well_formed(s.text))
            rows.append((video, track, len(mine), len(theirs), kept,
                         len(by_video[video]), len(auto), len(lines), ended,
                         usable_mine, usable_auto))
            print(f"{head}  {track:<8} punct {100 * ended / max(len(lines), 1):>3.0f}%"
                  f"  sentences {len(by_video[video]):>4}→{len(auto):<5}"
                  f"  teachable {usable_mine:>4}→{usable_auto:<5}"
                  f"  {'' if usable_auto >= usable_mine else 'worse'}",
                  flush=True)
            time.sleep(pause)

        if not rows:
            raise SystemExit("nothing to compare")
        kept = sum(r[4] for r in rows) / len(rows)
        gained = sum(r[3] for r in rows) / sum(r[2] for r in rows)
        usable_mine = sum(r[9] for r in rows)
        usable_auto = sum(r[10] for r in rows)
        manual_sentences = sum(r[5] for r in rows)
        auto_sentences = sum(r[6] for r in rows)
        punctuated = sum(r[8] for r in rows)
        all_lines = sum(r[7] for r in rows)
        print(f"\n{len(rows)} videos compared")
        print(f"  units:     keeps {100 * kept:.1f}% of the hand-written "
              f"track's, and yields {gained:.2f} for each")
        print(f"  sentences: {manual_sentences:,} by hand → "
              f"{auto_sentences:,} by machine")
        print(f"  of {all_lines:,} machine lines, {punctuated:,} end in "
              "punctuation")
        print(f"  teachable: {usable_mine:,} by hand → {usable_auto:,} by "
              f"machine  ({100 * usable_auto / max(usable_mine, 1) - 100:+.0f}%)")
        print("  teachable = i+1 and well-formed, which is what a page shows.")
        flat = [r for r in rows if r[8] == 0]
        if flat:
            print(f"\n  {len(flat)} of {len(rows)} machine tracks carry no "
                  "punctuation at all and collapse to one sentence:")
            for r in flat:
                print(f"      {r[0]}")
        if auto_sentences < manual_sentences / 10:
            print("\n  The machine track has no punctuation, and the corrector"
                  "\n  finds sentence boundaries by punctuation — so it becomes"
                  "\n  one enormous sentence. Its vocabulary is excellent and"
                  "\n  it teaches nothing: there is no sentence for a word to"
                  "\n  be the only unknown in. Restoring boundaries, not"
                  "\n  endings, is what `--corrector llm` has to do.")
