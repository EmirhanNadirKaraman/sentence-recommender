"""Which videos have been tried, and how it went.

`already_have` only ever knew about successes: it asks the catalogue, and the
catalogue holds videos that were ingested. A video refused for having no
manual subtitles left no trace at all — the refusal lived in a list on a
dataclass and died with the process — so every later run listed the same
channel, fetched the same metadata, and discovered the same refusal again.

Across a hundred and eighty channels that is most of the work, and it is the
reason an interrupted import has to start its channel over rather than
carrying on.

Some refusals are permanent and some are weather. A video with no German
subtitle track will still have none tomorrow; a request that timed out or came
back rate-limited says nothing about the video at all, and retrying it is
right. So the outcome is recorded, not merely the fact of an attempt, and only
the settled ones are skipped.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from state import open_state

# Outcomes worth never repeating. Anything else — a timeout, a bot check, an
# error nobody has classified — is treated as weather and tried again.
SETTLED = frozenset({"no-subtitles", "unavailable", "not-wanted-language"})

SCHEMA = """
CREATE TABLE IF NOT EXISTS video_attempts (
    video_id TEXT PRIMARY KEY,
    tries   INTEGER NOT NULL DEFAULT 0,
    outcome  TEXT NOT NULL,
    detail   TEXT,
    tried    TEXT NOT NULL
);
"""


class AttemptLog:
    """Every video the ingester has tried, and what came of it."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)
            # CREATE TABLE IF NOT EXISTS leaves an existing table alone, so
            # a column added later has to be asked for separately.
            self._widen(conn)

    GIVE_UP = 3

    def _widen(self, conn) -> None:
        """`tries` arrived after the table did."""
        have = {row[1] for row in conn.execute("PRAGMA table_info(video_attempts)")}
        if "tries" not in have:
            conn.execute("ALTER TABLE video_attempts ADD COLUMN"
                         " tries INTEGER NOT NULL DEFAULT 0")

    def record(self, video_id: str, outcome: str, detail: str = "") -> None:
        with open_state(self._path) as conn:
            self._widen(conn)
            conn.execute(
                "INSERT INTO video_attempts"
                " (video_id, outcome, detail, tried, tries) VALUES (?, ?, ?, ?, 1)"
                " ON CONFLICT(video_id) DO UPDATE SET"
                " outcome = excluded.outcome, detail = excluded.detail,"
                " tried = excluded.tried, tries = video_attempts.tries + 1",
                (video_id, outcome, detail[:400],
                 datetime.now().isoformat(timespec="seconds")))

    def settled(self) -> frozenset[str]:
        """Videos there is no point asking about again.

        Two ways to earn that. A definite verdict — no subtitles, unavailable,
        wrong language — settles a video at once. An indefinite one settles it
        after `GIVE_UP` attempts, which is the compromise this needed: the
        ambiguous outcomes are never settled on a single failure, because
        `unfetchable` cannot tell a deleted video from a throttled request and
        writing those off once cost forty good videos. But refusing to settle
        them *ever* is its own bug — a second pass over a channel spent its
        first thirty-four videos re-asking questions the first pass had
        already failed to answer, and a third would have done it again.

        Three failures is not weather.
        """
        with open_state(self._path) as conn:
            self._widen(conn)
            rows = conn.execute(
                "SELECT video_id FROM video_attempts"
                f" WHERE outcome IN ({','.join('?' * len(SETTLED))})"
                "    OR (outcome <> 'added' AND tries >= ?)",
                (*SETTLED, self.GIVE_UP))
            return frozenset(r[0] for r in rows)

    def counts(self) -> dict[str, int]:
        with open_state(self._path) as conn:
            return dict(conn.execute(
                "SELECT outcome, count(*) FROM video_attempts GROUP BY outcome"))

    @staticmethod
    def classify(why: str) -> str:
        """Which kind of refusal a message describes.

        Read from the text because that is all there is: `VideoIngestor.add`
        raises SystemExit with a sentence meant for a person.
        """
        low = why.lower()
        if "not a bot" in low or "sign in to confirm" in low:
            return "blocked"          # weather, and the fix is cookies
        if "metadata could not be fetched" in low or "refused" in low:
            # Cannot tell a deleted video from a blocked request, so it is
            # never settled — blacklisting these would have thrown away forty
            # good videos the day YouTube started asking for a sign-in.
            return "unfetchable"
        if "no such video" in low or "unavailable" in low:
            return "unavailable"
        if "could not be inspected" in low:
            # `_why_empty` says this when its own look at the video threw.
            # The sentence mentions subtitles, but it is explicitly a refusal
            # to say why — and YouTube throttles a burst of requests with
            # "The page needs to be reloaded", which arrives here looking
            # exactly like a verdict.
            #
            # It was settled as `no-subtitles`, so nine videos were written
            # off permanently without one of them being checked. One had
            # already been scraped successfully minutes before: 176
            # sentences, from a video the log called subtitle-less.
            return "unfetchable"      # weather; try again later
        if "off target" in low:
            # Says nothing the hunt was chasing. Not a fault of the video —
            # it may be exactly right for the next word — so never settled.
            return "off-target"
        if "auto-generated" in low:
            # A definite verdict, and it has to be said separately because
            # `_why_empty` calls this track "captions" — YouTube's own word
            # for it — so the `subtitle` test below never saw it and every
            # auto-only video classified as `error`, which is never settled.
            # The video has a track; it is simply the wrong kind, and
            # fetching it again will not make it hand-written.
            return "no-subtitles"
        if "subtitle" in low:
            return "no-subtitles"
        return "error"
