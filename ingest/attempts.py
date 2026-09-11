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

    def record(self, video_id: str, outcome: str, detail: str = "") -> None:
        with open_state(self._path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO video_attempts"
                " (video_id, outcome, detail, tried) VALUES (?, ?, ?, ?)",
                (video_id, outcome, detail[:400],
                 datetime.now().isoformat(timespec="seconds")))

    def settled(self) -> frozenset[str]:
        """Videos there is no point asking about again."""
        with open_state(self._path) as conn:
            rows = conn.execute(
                "SELECT video_id FROM video_attempts WHERE outcome IN"
                f" ({','.join('?' * len(SETTLED))})", tuple(SETTLED))
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
        if "subtitle" in low:
            return "no-subtitles"
        return "error"
