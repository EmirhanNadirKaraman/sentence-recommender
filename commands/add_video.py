"""`add-video` — scrape one YouTube video into the catalogue.

The one command that writes to the shared database. Everything else reads,
so this says plainly what it is about to do and where the rows will land.
"""
from __future__ import annotations

import re

from corpus import CorpusUpdater
from ingest import VideoIngestor
from roadmap import RoadmapRefresher

# A YouTube id is eleven characters. Accepting a full URL as well, because
# that is what a browser hands you.
VIDEO_ID = re.compile(r"(?:v=|/shorts/|youtu\.be/|^)([A-Za-z0-9_-]{11})(?:[&?/]|$)")


class AddVideoCommand:
    def run(self, app, video: str, language: str | None = None) -> None:
        video_id = self._identify(video)
        ingestor = VideoIngestor(app.settings, app.analyzer)

        if ingestor.already_have(video_id):
            raise SystemExit(
                f"{video_id} is already in the catalogue. Delete its rows from "
                "`video` first if you want it re-scraped."
            )

        print(f"fetching {video_id}…", flush=True)
        landed = ingestor.add(video_id, language)
        print(f"  {landed.title}")
        print(f"  {landed.lines} subtitle lines, {landed.language}, "
              f"{landed.source} captions")

        print("analysing the new video…", flush=True)
        caught = CorpusUpdater(app).catch_up()
        print(f"  {caught.report()}")

        rebuilt = RoadmapRefresher(app).refresh(touching="subtitle")
        for label, steps in sorted(rebuilt.items()):
            print(f"  roadmap [{label}]: {steps} steps")
        if not rebuilt:
            print("  no roadmap over the subtitles yet — "
                  "`build-roadmap --source subtitle --goals --list-only`")

    @staticmethod
    def _identify(video: str) -> str:
        """The id, whether given as an id or pasted as any YouTube URL."""
        match = VIDEO_ID.search(video.strip())
        if not match:
            raise SystemExit(
                f"{video!r} is not a YouTube video id or URL. Ids are eleven "
                "characters, like dQw4w9WgXcQ."
            )
        return match.group(1)
