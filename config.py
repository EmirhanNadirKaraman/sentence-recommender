"""Runtime configuration.

Credentials come from `.env`; everything else is a tunable with a documented
default.

There are two Postgres databases and the difference is the whole point.
There is one Postgres database, `Settings.own`, named by `DB_NAME` and
managed by this project's own migrations. It began as a copy of language-app's
`german_vocabulary`, but `sync-catalogue` was the migration that made it, not
a link that outlives it: ingestion writes here, so re-copying would destroy
work, and the command refuses when it would. Other databases on the same
server — language-app's, `lexy` — are named at the point of use.

All other mutable state lives in `Settings.state_path` (local SQLite).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent


def load_dotenv(path: Path | None = None) -> None:
    """Populate os.environ from a KEY=VALUE file, without overriding real env vars."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class DatabaseConfig:
    name: str
    user: str
    password: str
    host: str
    port: int

    @classmethod
    def named(cls, name: str) -> "DatabaseConfig":
        """Any database on this server, under the same credentials.

        One server, one login, many databases — ours, language-app's, `lexy`.
        Only ours is configured; the others are named at the point of use by
        whatever needs them, because a name in `.env` would imply a standing
        relationship where there is only an occasional errand.

        Blanks rather than a KeyError when `.env` is missing, because a
        machine that only serves the cached artefacts has no Postgres to name
        and `Settings()` is built before anything knows whether it will be
        needed. `Database` refuses clearly when asked to connect without a
        name; failing here instead meant the whole program would not start,
        with a bare KeyError as the explanation.
        """
        load_dotenv()
        return cls(
            name=name,
            user=os.environ.get("DB_USER", ""),
            password=os.environ.get("DB_PASSWORD", ""),
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "5432")),
        )

    @classmethod
    def owned(cls) -> "DatabaseConfig":
        """This project's database — the one it reads, writes and migrates.

        `DB_NAME` names it, because it is now the only database this project
        uses in the ordinary course of things. It did not start that way:
        everything read from Postgres once belonged to language-app, and
        reading someone else's schema meant never being able to index it —
        the vocabulary lookup was a sequential scan of 129,841 rows because
        the index it wanted could not be added to a database under their
        migrations. That index exists here, and the same lookup is 57x
        faster for it.
        """
        load_dotenv()
        return cls.named(os.environ.get("DB_NAME", "sentence_recommender"))

    def url(self) -> str:
        """SQLAlchemy URL, for alembic. Nothing else here speaks SQLAlchemy.

        Every part is percent-encoded. A password containing `@` or `/` —
        both legal, both common in generated passwords — would otherwise be
        read as the end of the credentials or the start of the database name,
        and the failure looks like a wrong host rather than a quoting bug.
        """
        user = quote(self.user, safe="")
        password = quote(self.password, safe="")
        return (f"postgresql+psycopg2://{user}:{password}"
                f"@{self.host}:{self.port}/{self.name}")

    def dsn_kwargs(self) -> dict:
        return {
            "dbname": self.name,
            "user": self.user,
            "password": self.password,
            "host": self.host,
            "port": self.port,
        }


@dataclass(frozen=True)
class Settings:
    """Everything the CLI needs, assembled once at startup."""

    # One Postgres database: ours, named by `DB_NAME`, under `alembic`, and
    # the target of every read and write. Anything else on the same server is
    # reached with `DatabaseConfig.named` by the one command that wants it.
    own: DatabaseConfig = field(default_factory=DatabaseConfig.owned)
    language: str = "de"

    # Which browser yt-dlp should borrow cookies from, or "" for none.
    #
    # YouTube now answers an anonymous scrape with "Sign in to confirm you're
    # not a bot", and yt-dlp cannot get so far as the metadata — every video
    # comes back looking unavailable, whatever its subtitles. Borrowing the
    # session from a browser you are already signed into is the documented
    # way through, and it is your own account reading caption tracks that are
    # public either way.
    #
    # Set YTDLP_COOKIES_BROWSER=chrome (or safari, firefox, edge, brave).
    cookies_browser: str = field(
        default_factory=lambda: os.environ.get("YTDLP_COOKIES_BROWSER", ""))
    data_dir: Path = ROOT / "data"

    # Vocabulary sources.  `known_words` and `function_words` together form the
    # starting known set; `priority_words` supplies the teaching-order ranking.
    known_words: Path = ROOT / "data" / "known_words.txt"
    function_words: Path = ROOT / "data" / "function_words.txt"
    # The study list is built from two halves and used everywhere.
    #   order_words  supplies the ranking — curated, most useful first
    #   form_words   supplies the shape the matcher speaks
    # `build-study-list` joins them into `goal_words`, which is what the
    # roadmap reads for both what to learn and in what order.
    order_words: Path = ROOT / "data" / "old_data" / "words_4000.txt"
    form_words: Path = ROOT / "data" / "final_result.txt"
    goal_words: Path = ROOT / "data" / "study_list.txt"
    # A list the reader built and saved, handed over instead of read. The
    # path above still names it — a plan's label carries the stem — but the
    # entries come from `word_list` in the state file. See `vocab.word_lists`.
    goal_entries: tuple[str, ...] | None = None
    goal_lemmas: Path = ROOT / "data" / "goal_lemmas.txt"

    # Local mutable state (SRS cards, generated roadmap).
    state_path: Path = ROOT / "data" / "state.sqlite3"

    # Cached builds the program no longer studies from.  Tatoeba's sentences
    # were imported once and are kept — deleting them is irreversible now the
    # importer is gone — but nothing reads them: this corpus is video
    # subtitles, so that is what the roadmap and the blocked list mean.
    ignored_builds: frozenset[str] = frozenset({"tatoeba"})

    # Sentence acceptance band, in words. Four-word sentences carry too little
    # context to learn a word from; the floor is a taste setting, so
    # `build-corpus --min-words` overrides it.
    min_tokens: int = 5
    max_tokens: int = 25

    # Local model, reached over Tailscale.  Endpoint comes from LLM_BASE_URL
    # and LLM_MODEL in .env; without them the LLM paths refuse rather than
    # silently degrading.
    llm_chunk_size: int = 25      # subtitle lines sent per correction call
    llm_timeout: float = 180.0

    # spaCy worker processes for the one-off corpus analysis.
    analysis_processes: int = 4

    # Examples shown per review card.
    examples_per_card: int = 3

    # How many other words to get through before one set aside comes back.
    # Counted in decisions, not minutes — see `vocab.snooze_store`.
    snooze_words: int = 20

    # Selection weight: score = unlock_gain + priority_weight * priority.
    # `priority` is in [0, 1] for both unit kinds, so the weight sets how far a
    # high-priority unit may outrank a higher-gain one.  Corpus gains are small
    # (median 0 at step 0), so this dominates in practice — deliberately.
    priority_weight: float = 3.0
