"""Why a video came back without subtitles, and whether it can say so.

`_why_empty` exists to tell a verdict from weather: a video with no
hand-written track is settled and never asked about again, while one that
could not be inspected is tried later, because a throttled burst is
indistinguishable from a refusal.

It spent a long time unable to tell either. It was decorated `@staticmethod`
while its body read `self._settings`, so every call raised `NameError`, was
swallowed by its own `except Exception`, and returned the one message that
means "I could not look" — which is never settled. So the log filled with
654 videos it had in fact inspected perfectly well, and every channel import
re-fetched all of them.

It no longer looks at all. It reads the track list `add` already holds, so
there is no second request to fail, and a refused first one is `Throttled`
before it gets here — see `tests/test_captions.py`.
"""
from __future__ import annotations

import unittest

from ingest.attempts import SETTLED, AttemptLog
from ingest.captions import Track, Tracks
from ingest.video import VideoIngestor


def offered(*tracks: tuple[str, bool]) -> Tracks:
    return Tracks(video_id="vid", tracks=tuple(
        Track(language=code, machine=machine, url=f"https://yt.test/{code}")
        for code, machine in tracks))


class WhyEmptyTest(unittest.TestCase):
    def _answer(self, *tracks: tuple[str, bool]) -> str:
        return VideoIngestor._why_empty(offered(*tracks), "de")

    def test_an_auto_only_video_is_settled(self) -> None:
        answer = self._answer(("de", True))
        self.assertIn("auto-generated", answer)
        self.assertIn(AttemptLog.classify(answer), SETTLED)

    def test_a_video_with_other_languages_says_which(self) -> None:
        answer = self._answer(("en", False), ("fr", False), ("en", True))
        self.assertIn("en, fr", answer)
        self.assertIn(AttemptLog.classify(answer), SETTLED)

    def test_machine_german_is_named_before_other_languages(self) -> None:
        """The German is there, only not typed by anyone — the more useful
        thing to be told, and the reason `--auto` exists."""
        answer = self._answer(("en", False), ("de", True))
        self.assertIn("auto-generated", answer)

    def test_a_video_with_nothing_at_all_is_settled(self) -> None:
        answer = self._answer()
        self.assertIn("at all", answer)
        self.assertIn(AttemptLog.classify(answer), SETTLED)

    def test_a_hand_written_track_with_no_lines_is_settled(self) -> None:
        """A track that parses and says nothing will say nothing tomorrow.
        An answer that did not parse is weather, and never reaches here."""
        answer = self._answer(("de-DE", False))
        self.assertIn("hold no lines", answer)
        self.assertIn(AttemptLog.classify(answer), SETTLED)


if __name__ == "__main__":
    unittest.main()
