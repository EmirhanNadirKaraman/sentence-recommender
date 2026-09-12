"""Adding a YouTube video to the catalogue.

Wraps language-app's own scraper rather than reimplementing it. That package
already knows how to fetch a transcript, detect its language, segment it into
sentences and fill every bridge table, and reimplementing that would be a
second parser of the same subtitles, drifting from the first.

It writes wherever it is pointed, and it is pointed at our database. The keys
it leaves for the database to assign are why migration 9863bcf8177b exists:
every statement omits the primary key and reads it back.

The coupling is deliberate and narrow: four functions from
`subtitle-scraper/pipeline.py`, reached by path. If that repository moves,
this is the file to change.
"""
from __future__ import annotations

from ingest.options import scrape

import sys
from dataclasses import dataclass
from pathlib import Path

from db import Database, WritableDatabase

SCRAPER = Path("/Users/emir/Documents/GitHub/language-app/subtitle-scraper")

# Below this a caption track is a title card or a burned-in credit, not
# speech. A hunting round pulled in two videos of one line each.
MIN_LINES = 20


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
        with Database(self._settings.own) as db:
            return bool(db.rows("SELECT 1 FROM video WHERE video_id = %s",
                                (video_id,)))

    @staticmethod
    def _says(transcript, wanted) -> bool:
        """Does this track say any of the words it was fetched for?

        A prefix rather than the whole word, because German inflects: a
        track saying `erzählt` is a track that says `erzählen`, and a track
        saying `Beschäftigten` says `Beschäftigte`. Two characters off the
        end catches the common endings without matching everything — short
        terms keep at least four, so `Top` stays `Top`.
        """
        text = " ".join(line.get("text", "") for line in transcript).lower()
        for term in wanted:
            term = term.strip().lower()
            if not term:
                continue
            if term[:max(4, len(term) - 2)] in text:
                return True
        return False

    def add(self, video_id: str, language: str | None = None,
            wanted: tuple[str, ...] = ()) -> Ingested:
        """Scrape one video and write it, or raise saying why not.

        `wanted` are the words the hunt went looking for. Nothing checked
        them before: the search is YouTube's own relevance ranking over
        `<word> deutsch`, which reads no captions, so a round could add
        eight videos that say none of what it was chasing and report
        progress. Checked here because this is where the caption text first
        exists and before the write, which is the last moment a video can
        be refused — the catalogue is shared and there is no command to
        undo one.
        """
        pipeline = self.pipeline
        wanted_lang = language or self._settings.language

        meta = pipeline.fetch_video_metadata(video_id)
        if meta is None:
            # The scraper returns None for every failure alike, so this
            # cannot tell a deleted video from a refused request. It said
            # "no such video" for forty in a row once, and every one of them
            # existed — YouTube was answering the scrape with a bot check.
            # Ambiguous on purpose, and `AttemptLog.classify` reads it as
            # weather rather than settling it.
            hint = ("" if self._settings.cookies_browser else
                    " If this is happening to every video, YouTube is probably"
                    " asking the scraper to sign in: set"
                    " YTDLP_COOKIES_BROWSER=chrome (or safari, firefox) so"
                    " yt-dlp can use a browser session you are already"
                    " logged into.")
            raise SystemExit(
                f"{video_id}: metadata could not be fetched — the video may be"
                f" gone, or the request may have been refused.{hint}")

        transcript, detected, dialect, source = pipeline.get_transcript(
            video_id, wanted_lang
        )
        if transcript and len(transcript) < MIN_LINES:
            # A caption track with a couple of lines is a title card or a
            # music video, not material. Refused before the write, because
            # the catalogue is shared and there is no command to undo one.
            raise SystemExit(
                f"{video_id}: only {len(transcript)} caption lines — too "
                "little to be worth keeping."
            )
        if not transcript:
            raise SystemExit(f"{video_id}: {self._why_empty(video_id, wanted_lang)}")
        if wanted and not self._says(transcript, wanted):
            raise SystemExit(
                f"{video_id}: says none of {', '.join(wanted)} — off target.")

        with WritableDatabase(self._settings.own) as db:
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
                channel_id=self._channel(cursor, meta, detected),
                transcript_source=source,
            )

        return Ingested(video_id=video_id, title=meta["title"],
                        language=detected, lines=len(transcript), source=source)


    def _channel(self, cursor, meta: dict, language: str) -> int | None:
        """The `channel` row this video belongs to, made if it is not there.

        `fetch_video_metadata` has always returned the channel's id and name
        alongside the title — the same yt-dlp call — and this threw them away
        and wrote NULL. So the catalogue could not answer "what do I already
        have from this channel", which is the first thing you want to know
        before scraping one: 1,134 German videos, 17 of them attached to the
        channel they came from.

        Taken from the video rather than passed down from `add-channel`, so a
        video added on its own is linked too. `upsert_channel` is
        language-app's, and idempotent — it keeps a name already recorded
        rather than overwriting it with whatever yt-dlp says today.

        None when the metadata has no channel, which is what the column
        expects and what every row written until now holds.
        """
        youtube_id = (meta.get("channel_id") or "").strip()
        if not youtube_id:
            return None
        return self.pipeline.upsert_channel(
            cursor, youtube_id, (meta.get("channel_name") or "").strip(),
            language)

    def _why_empty(self, video_id: str, wanted: str) -> str:
        """Say which reason it was, rather than listing the possibilities.

        Only manually written subtitles are accepted — auto-generated ones
        mangle exactly what a learner is studying — and YouTube reports the
        two kinds separately, so the distinction is there for the asking.
        Worth asking: twenty videos in one run were guessed at as
        rate-limiting when every one of them simply had no hand-written
        track.
        """
        import yt_dlp                            # noqa: PLC0415 — heavy

        try:
            with yt_dlp.YoutubeDL(scrape(self._settings)) as ydl:
                info = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}", download=False)
        except Exception:                        # noqa: BLE001 — say less, not wrong
            return (f"no {wanted} subtitles came back, and the video could not "
                    "be inspected to say why.")
        manual = set(info.get("subtitles") or {})
        auto = set(info.get("automatic_captions") or {})
        if wanted in auto and wanted not in manual:
            return (f"only auto-generated {wanted} captions, which are not "
                    "used — they mangle the endings you are learning.")
        if manual:
            return (f"no hand-written {wanted} subtitles; it has "
                    f"{', '.join(sorted(manual)[:4])}.")
        return f"no hand-written subtitles at all, in any language."
