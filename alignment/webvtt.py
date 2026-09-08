"""Writing aligned sentences out as subtitles a player can overlay.

WebVTT rather than SRT: browsers play it natively through `<track>`, and
`ffmpeg`/`mpv`/VLC all read it, so the corrected subtitles can go straight
back over the video they came from.
"""
from __future__ import annotations

from pathlib import Path

from corpus.sentence import Sentence


class WebVTTWriter:
    """One `.vtt` file per video, cues in playback order.

    Sentences with no timing are skipped rather than guessed at — a cue in the
    wrong place is worse than a missing one — and the count is reported so a
    bad alignment is visible instead of silent.
    """

    def __init__(self, include_translation: bool = False) -> None:
        self._include_translation = include_translation
        self.skipped = 0

    def render(self, sentences: list[Sentence]) -> str:
        timed = sorted(
            (s for s in sentences if s.timing is not None),
            key=lambda s: s.timing.start,
        )
        self.skipped += len(sentences) - len(timed)

        blocks = ["WEBVTT", ""]
        for index, sentence in enumerate(self._without_overlap(timed), start=1):
            blocks.append(str(index))
            blocks.append(sentence.timing.cue())
            blocks.append(sentence.text)
            if self._include_translation and sentence.translation:
                blocks.append(sentence.translation)
            blocks.append("")
        return "\n".join(blocks)

    def write(self, directory: Path, video_id: str, sentences: list[Sentence]) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{video_id}.vtt"
        path.write_text(self.render(sentences), encoding="utf-8")
        return path

    @staticmethod
    def _without_overlap(sentences: list[Sentence]) -> list[Sentence]:
        """Trim any cue that starts before the previous one ended.

        Word-level alignment can hand two sentences overlapping spans when the
        matcher anchors on a repeated word. Players show overlapping cues
        stacked, which reads as a glitch, so the earlier cue gives way.
        """
        out: list[Sentence] = []
        previous_end = 0.0
        for sentence in sentences:
            timing = sentence.timing
            start = max(timing.start, previous_end)
            if timing.end <= start:
                continue
            if start != timing.start:
                from alignment.timing import Timing
                sentence = sentence.with_timing(
                    Timing(timing.video_id, start, timing.end)
                )
            out.append(sentence)
            previous_end = sentence.timing.end
        return out
