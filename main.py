"""CLI entry point."""
from __future__ import annotations

import argparse

from commands import (
    BuildCorpusCommand, BuildRoadmapCommand, FillGapsCommand,
    ReviewCommand, StatusCommand,
)
from context import Application
from db import Database, WordRepository
from vocab.function_words import FunctionWordFile

SOURCE_HELP = (
    "corpus builds to use (default: all cached). "
    "e.g. --source subtitle:llm to study real video subtitles only"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentence-recommender")
    sub = parser.add_subparsers(dest="command", required=True)

    corpus = sub.add_parser("build-corpus", help="analyse and cache a sentence source")
    corpus.add_argument("source", choices=["tatoeba", "subtitle"])
    corpus.add_argument(
        "--corrector", choices=["merge", "llm"], default="merge",
        help="how to turn subtitle lines into sentences; 'llm' repairs them "
             "with the local model and caches as 'subtitle:llm'",
    )
    corpus.add_argument("--limit", type=int, help="analyse only the first N sentences")

    plan = sub.add_parser("build-roadmap", help="run the greedy i+1 walk")
    plan.add_argument("--steps", type=int, help="stop after N steps")
    plan.add_argument("--source", nargs="+", default=[], metavar="BUILD",
                      help=SOURCE_HELP)

    gaps = sub.add_parser("fill-gaps", help="generate examples the corpus lacks")
    gaps.add_argument("--limit", type=int, help="stop after N generated sentences")
    gaps.add_argument("--source", nargs="+", default=[], metavar="BUILD",
                      help=SOURCE_HELP)

    review = sub.add_parser("review", help="review the cards that are due")
    review.add_argument("--limit", type=int, default=20)
    review.add_argument("--source", nargs="+", default=[], metavar="BUILD",
                        help=SOURCE_HELP)

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
        BuildCorpusCommand().run(app, args.source, args.limit, args.corrector)
    elif args.command == "build-roadmap":
        BuildRoadmapCommand().run(app, args.steps, tuple(args.source))
    elif args.command == "fill-gaps":
        FillGapsCommand().run(app, args.limit, tuple(args.source))
    elif args.command == "review":
        ReviewCommand().run(app, args.limit, tuple(args.source))
    elif args.command == "status":
        StatusCommand().run(app)
    elif args.command == "function-words":
        function_words(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
