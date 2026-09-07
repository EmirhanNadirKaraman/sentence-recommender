"""CLI entry point."""
from __future__ import annotations

import argparse

from commands import (
    BuildCorpusCommand, BuildRoadmapCommand, ReviewCommand, StatusCommand,
)
from context import Application
from db import Database, WordRepository
from vocab.function_words import FunctionWordFile


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentence-recommender")
    sub = parser.add_subparsers(dest="command", required=True)

    corpus = sub.add_parser("build-corpus", help="analyse and cache a sentence source")
    corpus.add_argument("source", choices=["tatoeba", "subtitle"])
    corpus.add_argument("--limit", type=int, help="analyse only the first N sentences")

    plan = sub.add_parser("build-roadmap", help="run the greedy i+1 walk")
    plan.add_argument("--steps", type=int, help="stop after N steps")

    review = sub.add_parser("review", help="review the cards that are due")
    review.add_argument("--limit", type=int, default=20)

    sub.add_parser("status", help="what is built and what is due")
    sub.add_parser("function-words", help="regenerate the closed-class review file")
    return parser


def function_words(app: Application) -> None:
    with Database(app.settings.database) as db:
        words = WordRepository(db, app.settings.language).function_words()
    count = FunctionWordFile().write(app.settings.function_words, words)
    print(f"wrote {app.settings.function_words} — {count} lemmas")


def main() -> int:
    args = _parser().parse_args()
    app = Application()
    if args.command == "build-corpus":
        BuildCorpusCommand().run(app, args.source, args.limit)
    elif args.command == "build-roadmap":
        BuildRoadmapCommand().run(app, args.steps)
    elif args.command == "review":
        ReviewCommand().run(app, args.limit)
    elif args.command == "status":
        StatusCommand().run(app)
    elif args.command == "function-words":
        function_words(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
