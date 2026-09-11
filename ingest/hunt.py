"""Looking for video that says a word the corpus cannot teach.

The roadmap stops when nothing is i+1 any more, and what is left is stranded
not because it is hard but because no sentence here says it plainly enough.
The fix is material, and material can be searched for: take the words that
are stuck, ask YouTube for German video about each, keep what has German
subtitles.

Searching YouTube directly rather than a lookup site: the query is ours to
shape, results can be filtered on whether captions exist before anything is
written, and nothing is scraped from a service that offers no API for it.
"""
from __future__ import annotations

from ingest.options import scrape

import time
from dataclasses import dataclass, field

from vocab.entry import Unit

# YouTube refuses a client that asks too often — three videos in one run of
# twenty came back empty and were fine minutes later. A pause between
# searches costs little against a fetch that takes seconds anyway.
PAUSE = 1.5

# Enough results to find one with German captions, few enough to stay quick.
PER_WORD = 6


@dataclass
class Hunt:
    """What a round of searching turned up."""

    searched: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)


class VideoHunter:
    """Searches YouTube for video that says particular words."""

    def __init__(self, ingestor) -> None:
        self._ingestor = ingestor

    def search(self, word: str, limit: int = PER_WORD) -> list[str]:
        """Video ids for a German query about `word`, captioned ones only.

        Asked through YouTube's own Subtitles/CC filter — the `sp` token
        below — because a plain search is mostly video with no captions at
        all: an unfiltered run added four videos and threw away five. The
        filter does not promise *German* captions, so each video is still
        checked, but it stops most of the wasted fetches.
        """
        from urllib.parse import quote_plus      # noqa: PLC0415
        import yt_dlp                            # noqa: PLC0415 — heavy

        options = scrape(extract_flat="in_playlist", playlistend=limit)
        url = ("https://www.youtube.com/results?search_query="
               f"{quote_plus(word + ' deutsch')}&sp=EgIoAQ%253D%253D")
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                found = ydl.extract_info(url, download=False)
        except Exception:                        # noqa: BLE001 — a dud query
            return []
        return [entry["id"] for entry in (found or {}).get("entries", [])
                if entry and entry.get("id")][:limit]

    def gather(self, words: list[Unit], wanted: int) -> Hunt:
        """Search each word in turn until `wanted` new videos are found.

        Stops as soon as there are enough, so a round costs one search per
        word actually needed rather than one per word considered.
        """
        hunt = Hunt()
        seen: set[str] = set()
        for unit in words:
            if len(hunt.candidates) >= wanted:
                break
            term = unit.key.split()[-1] if unit.is_pattern else unit.key
            hunt.searched.append(term)
            for video_id in self.search(term):
                if video_id in seen or self._ingestor.already_have(video_id):
                    continue
                seen.add(video_id)
                hunt.candidates.append(video_id)
                if len(hunt.candidates) >= wanted:
                    break
            time.sleep(PAUSE)
        return hunt

    def take(self, hunt: Hunt, language: str | None = None,
             say=print) -> Hunt:
        """Try each candidate, keeping the ones that have German subtitles."""
        for index, video_id in enumerate(hunt.candidates, start=1):
            say(f"    [{index}/{len(hunt.candidates)}] {video_id} … ", end="")
            try:
                landed = self._ingestor.add(video_id, language)
            except SystemExit as why:
                hunt.refused.append((video_id, str(why).splitlines()[0]))
                say("no German subtitles")
            except Exception as error:           # noqa: BLE001 — one bad video
                hunt.refused.append((video_id, f"{type(error).__name__}"))
                say("failed")
            else:
                hunt.added.append(video_id)
                say(f"{landed.lines} lines — {landed.title[:38]}")
            time.sleep(PAUSE)
        return hunt
