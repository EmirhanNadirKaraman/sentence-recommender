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

A reader's own state -- what they know, their cards, their plans -- lives in
a schema of its own in the same database, `Settings.state`; see `state`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import quote

from languages import GERMAN, language as _language

ROOT = Path(__file__).resolve().parent

# The schema an installation's reader state lives in when nobody is named:
# the one reader there was before there was a registry of them.
STATE_SCHEMA = "reader"


def state_schema(name: str) -> str:
    """The schema reader `name`'s state lives in: `reader_<name>`."""
    return f"{STATE_SCHEMA}_{name}"


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
    # The schema every query on this connection reads and writes, or "" for
    # the server's default, `public`. A language other than German keeps its
    # catalogue and corpus in a schema of its own inside the one database:
    # the tables are the same tables, with the same names, so nothing that
    # queries them has to know which language it is in -- and nothing one
    # language writes can land among the other's rows. See `languages`.
    schema: str = ""

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
    def owned(cls, schema: str = "") -> "DatabaseConfig":
        """This project's database — the one it reads, writes and migrates.

        `DB_NAME` names it, because it is now the only database this project
        uses in the ordinary course of things. It did not start that way:
        everything read from Postgres once belonged to language-app, and
        reading someone else's schema meant never being able to index it —
        the vocabulary lookup was a sequential scan of 129,841 rows because
        the index it wanted could not be added to a database under their
        migrations. That index exists here, and the same lookup is 57x
        faster for it.

        `schema` is the language's part of it: German's is the default,
        `public`; English's is `en`. See `languages`.
        """
        load_dotenv()
        made = cls.named(os.environ.get("DB_NAME", "sentence_recommender"))
        return replace(made, schema=schema) if schema else made

    def url(self) -> str:
        """SQLAlchemy URL, for alembic. Nothing else here speaks SQLAlchemy.

        Every part is percent-encoded. A password containing `@` or `/` —
        both legal, both common in generated passwords — would otherwise be
        read as the end of the credentials or the start of the database name,
        and the failure looks like a wrong host rather than a quoting bug.
        """
        user = quote(self.user, safe="")
        password = quote(self.password, safe="")
        # The schema rides on the connection's options, so what the
        # migrations create lands in it -- see `migrations/env.py`.
        options = (f"?options={quote(f'-c search_path={self.schema}', safe='')}"
                   if self.schema else "")
        return (f"postgresql+psycopg2://{user}:{password}"
                f"@{self.host}:{self.port}/{self.name}{options}")

    # Raised from the 4MB default, on the connection rather than the server.
    #
    # The corpus load joins 3.18M unit rows against 450k sentences, and at
    # 4MB the hash spills: `EXPLAIN (ANALYZE, BUFFERS)` reported 8 batches
    # and 17,151 blocks read and written through a temp file, 134 MB of I/O
    # to answer a query whose hash table needs 19 MB. At 64MB it is one batch
    # and no temp file, and the server side went 2,859 ms to 2,053 ms —
    # measured 2026-09-22.
    #
    # Here and not in postgresql.conf because it is this project's query that
    # wants it, not the machine's every query, and because a setting carried
    # in the repo is one a second machine gets for free. 256MB measured no
    # better than 64MB, so this is the knee rather than the ceiling; it is
    # per sort or hash node per connection, and this app keeps a handful.
    WORK_MEM = "64MB"

    def dsn_kwargs(self) -> dict:
        return {
            "dbname": self.name,
            "user": self.user,
            "password": self.password,
            "host": self.host,
            "port": self.port,
            "options": f"-c work_mem={self.WORK_MEM}" + (
                # One schema and nothing behind it. A path that fell back to
                # `public` would answer for a table the language's schema
                # lacks -- a migration not run there yet -- with German rows,
                # silently; with nothing behind it, the query fails instead.
                f" -c search_path={self.schema}" if self.schema else ""),
        }


@dataclass(frozen=True)
class Settings:
    """Everything the CLI needs, assembled once at startup."""

    # One Postgres database: ours, named by `DB_NAME`, under `alembic`, and
    # the target of every read and write. Anything else on the same server is
    # reached with `DatabaseConfig.named` by the one command that wants it.
    own: DatabaseConfig = field(default_factory=DatabaseConfig.owned)
    # The language being learned, and the one translations are made into.
    language: str = GERMAN.code
    native: str = "en"
    # Whose state this is: a name from the registry (see `readers`), or
    # empty for an installation that has only ever had one reader.
    reader: str = ""

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
    function_words: Path = GERMAN.function_words
    # The study list is built from two halves and used everywhere.
    #   order_words  supplies the ranking — curated, most useful first
    #   form_words   supplies the shape the matcher speaks
    # `build-study-list` joins them into `goal_words`, which is what the
    # roadmap reads for both what to learn and in what order.
    # German only: no other language has the valency dictionary to merge.
    order_words: Path | None = GERMAN.order_words
    form_words: Path | None = GERMAN.form_words
    goal_words: Path = ROOT / "data" / "study_list.txt"
    # Fixed expressions — units found by their words. The matcher reads how;
    # the application and the study list read only the names.
    expressions: Path = GERMAN.expressions
    # A list the reader built and saved, handed over instead of read. The
    # path above still names it — a plan's label carries the stem — but the
    # entries come from `word_list` in the state file. See `vocab.word_lists`.
    goal_entries: tuple[str, ...] | None = None
    goal_lemmas: Path = GERMAN.goal_lemmas

    # The reader's own schema: what they know, their cards, their plans, and
    # what has been derived and paid for on their behalf. See `state`. An
    # installation with no registry of readers has one, `reader`.
    state: DatabaseConfig = field(
        default_factory=lambda: DatabaseConfig.owned(STATE_SCHEMA))

    # Cached builds the program no longer studies from. See `languages`.
    ignored_builds: frozenset[str] = GERMAN.ignored_builds

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

    # The judge the corpus pass asks (`ask-sentences`) and the answers the
    # rankings read. TypeSafe's Jev, hosted, keyed by TYPESAFE_API_KEY in
    # .env; measured against the local model in experiment 04 and chosen
    # for separating the verbs the local one could not. Pinned to the
    # version the calibration ran on, so `jev-latest` moving does not
    # silently change every answer read back.
    judge_model: str = "jev-1.13.0"
    judge_workers: int = 4        # requests in flight; the limit is 1,200 a minute

    # Worker processes for the one-off corpus analysis (`corpus.parallel`):
    # each parses and reads its sentences' units.
    #
    # Four, not eight. This said eight on the strength of a 2026-09-21
    # measurement against spaCy's own `n_process` — 990 sentences a second
    # against 540 — which compared this module with the thing it replaced,
    # not eight workers with four. Compared with four, eight is slower:
    # best of three on 24,000 real sentences, 2026-09-22, four gave 1,402 a
    # second, six 1,390 and eight 1,236, and eight lost every repeat. This
    # machine has four performance cores and four efficiency cores, and the
    # second four cost more in contention than they return in throughput.
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

    @classmethod
    def for_reader(cls, reader) -> "Settings":
        """Everything one reader's commands and pages read and write.

        Their own files live in their `home`; what belongs to the language
        they are learning comes from `languages`. The first reader's home is
        `data/` itself, and for them this is exactly `Settings()` -- the
        layout the program had before it had a second reader.
        """
        lang = _language(reader.language)
        home = reader.home
        # Their own copy of the closed classes, where `reader add` made one:
        # the quiz comments out what they say they do not know, and the
        # language's file is in the repository for every reader of it.
        mine = home / lang.function_words.name
        return cls(
            own=DatabaseConfig.owned(lang.schema),
            language=lang.code,
            native=reader.native,
            reader=reader.name,
            data_dir=home,
            known_words=home / "known_words.txt",
            function_words=mine if mine.exists() else lang.function_words,
            order_words=lang.order_words,
            form_words=lang.form_words,
            goal_words=home / "study_list.txt",
            expressions=lang.expressions,
            goal_lemmas=lang.goal_lemmas,
            state=DatabaseConfig.owned(state_schema(reader.name)),
            ignored_builds=lang.ignored_builds,
        )
