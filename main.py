"""CLI entry point.  Commands are added as each slice lands."""
from __future__ import annotations

import sys

from config import Settings
from db import Database, WordRepository
from vocab.function_words import FunctionWordFile

USAGE = """\
usage: python main.py <command>

  function-words   regenerate data/function_words.txt for review
"""


def function_words(settings: Settings) -> None:
    with Database(settings.database) as db:
        words = WordRepository(db, settings.language).function_words()
    count = FunctionWordFile().write(settings.function_words, words)
    print(f"wrote {settings.function_words} — {count} lemmas")


COMMANDS = {"function-words": function_words}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in COMMANDS:
        print(USAGE, file=sys.stderr)
        return 1
    COMMANDS[argv[1]](Settings())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
