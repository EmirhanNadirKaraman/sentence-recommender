"""Listing every video a channel has published.

language-app's scraper already knows how to walk a channel — two backends,
one scraping the web page and one through yt-dlp, with a fallback between
them. This wraps that rather than writing a third.

Nothing here fetches subtitles. Listing is cheap and adding is not, so the
two are kept apart: a caller can see what a channel holds, and how much of
it is already catalogued, before committing to hours of fetching.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SCRAPER = Path("/Users/emir/Documents/GitHub/language-app/subtitle-scraper")

# A channel is named three ways in the wild: the opaque id, an @handle, or a
# URL containing either.
CHANNEL_ID = re.compile(r"(UC[A-Za-z0-9_-]{22})")
HANDLE = re.compile(r"@([A-Za-z0-9_.-]+)")


class ChannelLister:
    """Every video id a channel has, in the order the backend yields them."""

    def __init__(self) -> None:
        self._pipeline = None

    @property
    def pipeline(self):
        if self._pipeline is None:
            if str(SCRAPER) not in sys.path:
                sys.path.insert(0, str(SCRAPER))
            import pipeline                    # noqa: PLC0415 — heavy, deferred
            self._pipeline = pipeline
        return self._pipeline

    @staticmethod
    def identify(given: str) -> str:
        """The channel as the lister wants it: an id, or an @handle.

        A bare handle is returned with its `@`, because that is what yt-dlp
        resolves; an id is returned as-is.
        """
        given = given.strip()
        found = CHANNEL_ID.search(given)
        if found:
            return found.group(1)
        handle = HANDLE.search(given)
        if handle:
            return f"@{handle.group(1)}"
        if given and "/" not in given:
            return given if given.startswith("@") else f"@{given}"
        raise SystemExit(
            f"{given!r} is not a channel. Give a UC… id, an @handle, or a "
            "URL containing one."
        )

    def videos(self, channel: str, limit: int = 0) -> list[str]:
        """Video ids for `channel`; `limit` of 0 means every one of them."""
        out: list[str] = []
        for candidate in self.pipeline.list_channel_videos(channel, lister="auto"):
            video_id = (candidate or {}).get("video_id")
            if not video_id:
                continue
            out.append(video_id)
            if limit and len(out) >= limit:
                break
        return out
