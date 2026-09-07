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
    priority_words: Path = ROOT / "data" / "words_4000.txt"

    # Local mutable state (SRS cards, generated roadmap).
    state_path: Path = ROOT / "data" / "state.sqlite3"

    # Sentence acceptance band, in tokens.
    min_tokens: int = 4
    max_tokens: int = 25

    # Selection weight: score = unlock_gain + priority_weight * priority.
    # `priority` is in [0, 1] for both unit kinds, so the weight sets how far a
    # high-priority unit may outrank a higher-gain one.  Corpus gains are small
    # (median 0 at step 0), so this dominates in practice — deliberately.
    priority_weight: float = 3.0
