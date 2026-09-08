"""Runtime configuration.

Credentials come from `.env`; everything else is a tunable with a documented
default.  The database is treated as read-only throughout — it is the
language-app schema and this project is a consumer, never a writer.  All
mutable state lives in `Settings.state_path` (local SQLite).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

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
    def from_env(cls) -> "DatabaseConfig":
        load_dotenv()
        return cls(
            name=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "5432")),
        )

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

    database: DatabaseConfig = field(default_factory=DatabaseConfig.from_env)
    language: str = "de"
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

    # Tatoeba German-English export.  Human-written sentences with human
    # translations — the primary source of examples.  Local files, nothing
    # is downloaded.
    tatoeba_sentences: Path = Path(
        "/Users/emir/Documents/GitHub/FakeClozemaster/tatoeba_filler/good_sentences.csv")
    tatoeba_links: Path = Path(
        "/Users/emir/Documents/GitHub/FakeClozemaster/tatoeba_filler/good_sentence_ids.csv")

    # Local mutable state (SRS cards, generated roadmap).
    state_path: Path = ROOT / "data" / "state.sqlite3"

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

    # Selection weight: score = unlock_gain + priority_weight * priority.
    # `priority` is in [0, 1] for both unit kinds, so the weight sets how far a
    # high-priority unit may outrank a higher-gain one.  Corpus gains are small
    # (median 0 at step 0), so this dominates in practice — deliberately.
    priority_weight: float = 3.0
