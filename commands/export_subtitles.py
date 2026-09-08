"""`export-subtitles` — write the corrected subtitles back out as WebVTT.

The point of aligning is to be able to put the repaired text back over the
video it came from. One `.vtt` per video, which browsers play through
`<track>` and which ffmpeg, mpv and VLC all read.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from alignment import WebVTTWriter


class ExportSubtitlesCommand:
    def run(self, app, out_dir: Path, builds: tuple[str, ...] = (),
            translation: bool = False) -> None:
        sentences = app.corpus(*(builds or ("subtitle",)))
        if not sentences:
            raise SystemExit(
                "no cached subtitle corpus — run `build-corpus subtitle` first"
            )

        by_video: dict[str, list] = defaultdict(list)
        untimed = 0
        for sentence in sentences:
            if sentence.timing is None:
                untimed += 1
                continue
            by_video[sentence.timing.video_id].append(sentence)

        if not by_video:
            raise SystemExit(
                f"none of the {len(sentences)} sentences carry timing — this "
                "build predates alignment; rebuild it with `build-corpus subtitle`"
            )

        writer = WebVTTWriter(include_translation=translation)
        for video_id, group in sorted(by_video.items()):
            path = writer.write(out_dir, video_id, group)
            print(f"  {path}  ({len(group)} cues)")

        print(f"{len(by_video)} videos written to {out_dir}")
        if untimed:
            print(f"  {untimed} sentences had no timing and were left out")
