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

These tests stub `yt_dlp`, so they assert the reasoning rather than YouTube.
"""
from __future__ import annotations

import sys
import types
import unittest

from config import Settings
from ingest.attempts import SETTLED, AttemptLog
from ingest.video import VideoIngestor


class _FakeYDL:
    def __init__(self, info: dict) -> None:
        self._info = info

    def __enter__(self) -> "_FakeYDL":
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    def extract_info(self, url: str, download: bool = False) -> dict:
        return self._info


class WhyEmptyTest(unittest.TestCase):
    def _answer(self, info: dict) -> str:
        """What `_why_empty` says when YouTube reports `info`."""
        fake = types.ModuleType("yt_dlp")
        fake.YoutubeDL = lambda _opts: _FakeYDL(info)   # type: ignore[attr-defined]
        original = sys.modules.get("yt_dlp")
        sys.modules["yt_dlp"] = fake
        self.addCleanup(
            lambda: sys.modules.__setitem__("yt_dlp", original)
            if original is not None else sys.modules.pop("yt_dlp", None))
        return VideoIngestor(Settings(), None)._why_empty("vid", "de")

    def test_it_can_reach_its_own_settings(self) -> None:
        """The regression. A `@staticmethod` reading `self` raised NameError
        into its own `except`, so this returned "could not be inspected" for
        every video ever asked about."""
        answer = self._answer({"subtitles": {}, "automatic_captions": {}})
        self.assertNotIn("could not be inspected", answer)

    def test_an_auto_only_video_is_settled(self) -> None:
        answer = self._answer(
            {"subtitles": {}, "automatic_captions": {"de": [{}]}})
        self.assertIn("auto-generated", answer)
        self.assertIn(AttemptLog.classify(answer), SETTLED)

    def test_a_video_with_other_languages_says_which(self) -> None:
        answer = self._answer(
            {"subtitles": {"en": [{}], "fr": [{}]}, "automatic_captions": {}})
        self.assertIn("en", answer)
        self.assertIn(AttemptLog.classify(answer), SETTLED)

    def test_a_video_with_nothing_at_all_is_settled(self) -> None:
        answer = self._answer({"subtitles": {}, "automatic_captions": {}})
        self.assertIn(AttemptLog.classify(answer), SETTLED)

    def test_a_failure_to_inspect_is_not_settled(self) -> None:
        """Still the right answer when the look genuinely throws — that is
        the case the message was written for."""
        fake = types.ModuleType("yt_dlp")

        def boom(_opts):
            raise RuntimeError("The page needs to be reloaded")

        fake.YoutubeDL = boom                      # type: ignore[attr-defined]
        original = sys.modules.get("yt_dlp")
        sys.modules["yt_dlp"] = fake
        self.addCleanup(
            lambda: sys.modules.__setitem__("yt_dlp", original)
            if original is not None else sys.modules.pop("yt_dlp", None))
        answer = VideoIngestor(Settings(), None)._why_empty("vid", "de")
        self.assertIn("could not be inspected", answer)
        self.assertNotIn(AttemptLog.classify(answer), SETTLED)


if __name__ == "__main__":
    unittest.main()
