"""Adding a YouTube video to the catalogue.

Wraps language-app's own scraper rather than reimplementing it. That package
already knows how to segment a transcript into sentences and fill every
bridge table, and reimplementing that would be a second parser of the same
subtitles, drifting from the first.

It writes wherever it is pointed, and it is pointed at our database. The keys
it leaves for the database to assign are why migration 9863bcf8177b exists:
every statement omits the primary key and reads it back.

The coupling is deliberate and narrow: three functions from
`subtitle-scraper/pipeline.py` — the metadata, the channel row and the
write — reached by path. If that repository moves, this is the file to
change.

What it no longer borrows is the caption fetch. `get_transcript` goes
through yt-dlp, and 413 videos in the attempt log stopped at the end of it:
the track download, refused with HTTP 429 after yt-dlp had found a
hand-written German track. `ingest.captions` asks YouTube's player API
directly, as its iOS app does, and on 2026-09-25 read all 413 of those
tracks at one video every 1.5 seconds without a single refusal. Its json3
parse is a second parser of the same subtitles — what the first paragraph
warns against — so it was measured against the first: thirty catalogued
videos, identical to language-app's cache line for line.

The policy is still upstream's: a hand-written track, never a machine one
passed off as one. The machine track is taken only under `accept_auto`,
marked `transcript_source='auto'`, which `corpus.source.BUILD_SOURCES`
keeps out of the hand-written builds.
"""
from __future__ import annotations

from ingest.auto_captions import Refused, Unfetchable, judge
from ingest.captions import Throttled, Tracks, list_tracks, snippets

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
            wanted: tuple[str, ...] = (),
            accept_auto: bool = False, max_minutes: float = 0) -> Ingested:
        """Scrape one video and write it, or raise saying why not.

        `wanted` are the words the hunt went looking for. Nothing checked
        them before: the search is YouTube's own relevance ranking over
        `<word> deutsch`, which reads no captions, so a round could add
        eight videos that say none of what it was chasing and report
        progress. Checked here because this is where the caption text first
        exists and before the write, which is the last moment a video can
        be refused — the catalogue is shared and there is no command to
        undo one.

        `accept_auto` allows a machine track *only where there is no
        hand-written one*, and only if it passes the gate in
        `ingest.auto_captions`. The order is not a detail: measured over
        thirty videos holding both, every machine track was worse than its
        manual counterpart — 31% fewer teachable sentences — so a manual
        track is never passed over for one. The flag changes what happens
        when the manual fetch comes back empty, which until now was always a
        refusal.
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

        # One list for every question below — which track, whether a machine
        # one exists, and why there is nothing — where each of those used to
        # be its own yt-dlp extraction. A refusal propagates as `Throttled`,
        # a plain exception whose "HTTP 429" `add-videos` counts towards
        # stopping the run, exactly as the refused downloads it replaces did.
        offered = list_tracks(video_id)
        # Length before the track, because the player's answer already carries
        # it (`Tracks.length`) and downloading the captions is the expensive,
        # rate-limited half. A cap here costs nothing to apply.
        #
        # Settled, not weather: a two-hour video will still be two hours
        # tomorrow, so `AttemptLog` should not offer it again.
        if max_minutes and offered.length and offered.length > max_minutes * 60:
            refusal = SystemExit(
                f"{video_id}: {offered.length / 60:.0f} minutes, over the "
                f"{max_minutes:g} minute cap.")
            refusal.outcome = "too-long"
            raise refusal
        track = offered.manual(wanted_lang)
        transcript = snippets(offered.read(track)) if track else []
        source = "manual"
        if transcript and len(transcript) < MIN_LINES:
            # A caption track with a couple of lines is a title card or a
            # music video, not material. Refused before the write, because
            # the catalogue is shared and there is no command to undo one.
            raise SystemExit(
                f"{video_id}: only {len(transcript)} caption lines — too "
                "little to be worth keeping."
            )
        if not transcript and accept_auto:
            # Nothing hand-written. This is the only point the machine track
            # is considered, and `machine_transcript` raises rather than
            # returning empty when the gate refuses it, so a bad track is
            # never confused with an absent one.
            transcript, _, _, source = self.machine_transcript(
                video_id, wanted_lang, offered)
        if not transcript:
            raise SystemExit(
                f"{video_id}: {self._why_empty(offered, wanted_lang)}")
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
                # The language asked for, in both columns. `get_transcript`
                # returned the code it matched — always the plain one, since
                # `de` catches `de-DE` by prefix before `de-DE` is tried — so
                # every German row holds `de` in each, and still will.
                language=wanted_lang,
                dialect=wanted_lang,
                nlp=self._analyzer.matcher.nlp,
                sentence_types=sentence_types,
                category=meta.get("category", "other"),
                channel_id=self._channel(cursor, meta, wanted_lang),
                transcript_source=source,
            )

        return Ingested(video_id=video_id, title=meta["title"],
                        language=wanted_lang, lines=len(transcript),
                        source=source)


    def machine_transcript(self, video_id: str, language: str,
                           offered: Tracks | None = None):
        """The ASR track for a video with no hand-written one, if it is good.

        Returns what `add` builds from a hand-written track — snippets,
        language, dialect, source — with `source` fixed at `auto`, which is
        what reaches `video.transcript_source` and what every build filters
        on afterwards.

        `offered` is the track list `add` already holds. The dry-run survey
        has none, and it is asked for here.

        The language is the one that was asked for rather than langdetect's
        verdict on the first twenty snippets. That is not a shortcut: the
        gate has already read the *whole* track in windows and required 60%
        of them to be German, which is a stronger test than the one
        `get_transcript` applies, and it exists because this channel teaches
        German in English. A video that opens "Hallo und willkommen" and
        then runs twelve minutes in English passes a check on its first
        twenty lines.
        """
        try:
            offered = offered or list_tracks(video_id)
            track = offered.machine(language)
            lines = offered.read(track) if track else []
        except Throttled as error:
            # Named rather than left to `classify`, which reads the wording —
            # the confusion that once wrote off nine videos nobody had
            # checked. Every refusal the list or the download can meet
            # arrives as this one exception.
            raise Unfetchable(f"{video_id}: {error}") from error
        if not lines:
            raise Refused(
                f"{video_id}: no {language} machine track — YouTube's speech "
                f"recognition did not hear {language} in it.",
                "auto-no-track")
        verdict = judge(lines, floor=MIN_LINES)
        if not verdict.ok:
            raise Refused(f"{video_id}: {verdict.why()}",
                          f"auto-{verdict.verdict}")
        return snippets(lines), language, language, "auto"

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

    @staticmethod
    def _why_empty(offered: Tracks, wanted: str) -> str:
        """Say which reason it was, rather than listing the possibilities.

        Only manually written subtitles are accepted — auto-generated ones
        mangle exactly what a learner is studying — and YouTube reports the
        two kinds separately, so the distinction is there for the asking.
        Worth asking: twenty videos in one run were guessed at as
        rate-limiting when every one of them simply had no hand-written
        track.

        Read off the list `add` already holds. This used to be a second
        yt-dlp extraction of its own, which could fail where the first had
        not and then had to say "could not be inspected"; now a request
        refused is refused once, in `list_tracks`, where it is weather.
        """
        if offered.manual(wanted):
            return (f"its hand-written {wanted} subtitles hold no lines at "
                    "all.")
        if offered.machine(wanted):
            return (f"only auto-generated {wanted} captions, which are not "
                    "used — they mangle the endings you are learning.")
        manual = offered.hand_written()
        if manual:
            return (f"no hand-written {wanted} subtitles; it has "
                    f"{', '.join(manual[:4])}.")
        return "no hand-written subtitles at all, in any language."
