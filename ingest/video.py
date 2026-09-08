"""Adding a YouTube video to the shared catalogue.

Wraps language-app's own scraper rather than reimplementing it. That package
already knows how to fetch a transcript, detect its language, segment it into
sentences and fill every bridge table — and a second implementation would
drift from the corpus this project reads, which is the one thing that must
not happen.

The coupling is deliberate and narrow: four functions from
`subtitle-scraper/pipeline.py`, reached by path. If that repository moves,
this is the file to change.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from db import Database, WritableDatabase

SCRAPER = Path("/Users/emir/Documents/GitHub/language-app/subtitle-scraper")


@dataclass(frozen=True)
class Ingested:
    """What landed, so the caller can say something true about it."""

    video_id: str
    title: str
    language: str
    lines: int
    source: str


class VideoIngestor:
    """Fetches one video's subtitles and writes them to the catalogue."""

    def __init__(self, settings, analyzer) -> None:
        self._settings = settings
        self._analyzer = analyzer
        self._pipeline = None

    @property
    def pipeline(self):
        """language-app's scraper, imported on demand.

        It pulls in yt-dlp, langdetect and a spaCy model at import time, and
        every command except this one gets by without them.
        """
        if self._pipeline is None:
            if not SCRAPER.is_dir():
                raise SystemExit(
                    f"language-app's scraper is not at {SCRAPER}.\n"
                    "Ingestion borrows it; adjust SCRAPER in ingest/video.py."
                )
            if str(SCRAPER) not in sys.path:
                sys.path.insert(0, str(SCRAPER))
            import pipeline                    # noqa: PLC0415 — heavy, deferred
            self._pipeline = pipeline
        return self._pipeline

    def already_have(self, video_id: str) -> bool:
        with Database(self._settings.database) as db:
            return bool(db.rows("SELECT 1 FROM video WHERE video_id = %s",
                                (video_id,)))

    def add(self, video_id: str, language: str | None = None) -> Ingested:
        """Scrape one video and write it, or raise saying why not."""
        pipeline = self.pipeline
        wanted = language or self._settings.language

        meta = pipeline.fetch_video_metadata(video_id)
        if meta is None:
            raise SystemExit(f"{video_id}: no such video, or it is unavailable.")

        transcript, detected, dialect, source = pipeline.get_transcript(
            video_id, wanted
        )
        if not transcript:
            # Deliberately not "has none". Nothing came back, and the two
            # reasons are indistinguishable from here: the video may truly
            # have no subtitles in this language, or YouTube may be refusing
            # a client that has asked too often. Three videos in one run were
            # reported as having no German subtitles minutes after the same
            # code had fetched a hundred lines from each.
            raise SystemExit(
                f"{video_id}: no {wanted} subtitles came back. Either it has "
                "none, or YouTube is rate-limiting — try it again later."
            )

        with WritableDatabase(self._settings.database) as db:
            cursor = db.cursor()
            # The scraper needs to know what is already catalogued so it does
            # not insert a second row for a word it has seen before.
            cursor.execute("SELECT word, pos, lemma FROM word_table")
            db_words = {(word, pos, lemma) for word, pos, lemma in cursor.fetchall()}
            cursor.execute(
                "SELECT language || '_' || rule, rule_id FROM grammar_rule")
            sentence_types = dict(cursor.fetchall())

            pipeline.populate(
                cursor=cursor,
                connection=db.connection,
                db_words=db_words,
                video_id=video_id,
                title=meta["title"],
                thumbnail_url=meta["thumbnail_url"],
                transcript=transcript,
                language=detected,
                dialect=dialect,
                nlp=self._analyzer.matcher.nlp,
                sentence_types=sentence_types,
                category=meta.get("category", "other"),
                # `video.channel_id` points at the `channel` table, which this
                # project never populates. A video added on its own belongs to
                # no channel row, and the column is nullable for that case.
                channel_id=None,
                transcript_source=source,
            )

        return Ingested(video_id=video_id, title=meta["title"],
                        language=detected, lines=len(transcript), source=source)
