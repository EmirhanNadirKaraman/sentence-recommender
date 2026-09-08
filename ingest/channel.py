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
        """Video ids for `channel`; `limit` of 0 means every one of them.

        Handles go straight to yt-dlp. The default backend tries scrapetube
        first, which only understands a `UC…` id and raises on an `@handle`
        rather than returning nothing — so the fallback that was supposed to
        cover this never runs.
        """
        if channel.startswith("@"):
            return self._by_handle(channel, limit)
        try:
            return self._walk(channel, "auto", limit)
        except Exception:                        # noqa: BLE001 — try the other
            return self._walk(channel, "yt-dlp", limit)

    def _by_handle(self, handle: str, limit: int) -> list[str]:
        """List a channel named by @handle.

        Done here rather than through the shared lister, which builds
        `youtube.com/channel/<id>/videos` — right for an opaque id and a 400
        for a handle, whose URL has no `/channel/` in it. Upstream is not
        wrong, it simply only takes ids.
        """
        import yt_dlp                            # noqa: PLC0415 — heavy

        options = {"quiet": True, "no_warnings": True, "skip_download": True,
                   "extract_flat": "in_playlist"}
        if limit:
            options["playlist_items"] = f"1:{limit}"
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                found = ydl.extract_info(
                    f"https://www.youtube.com/{handle}/videos", download=False)
        except Exception as error:               # noqa: BLE001 — say which
            raise SystemExit(
                f"{handle}: could not list that channel — {type(error).__name__}"
            ) from error
        return [entry["id"] for entry in (found or {}).get("entries", [])
                if entry and entry.get("id")]

    def _walk(self, channel: str, backend: str, limit: int) -> list[str]:
        out: list[str] = []
        for candidate in self.pipeline.list_channel_videos(channel, lister=backend):
            video_id = (candidate or {}).get("video_id")
            if not video_id:
                continue
            out.append(video_id)
            if limit and len(out) >= limit:
                break
        return out
