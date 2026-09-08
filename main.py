"""CLI entry point."""
from __future__ import annotations

import argparse

from pathlib import Path

from commands import (
    BuildCorpusCommand, BuildRoadmapCommand, ExportSubtitlesCommand,
    FillGapsCommand, ReviewCommand, ServeCommand, StatusCommand,
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

    export = sub.add_parser(
        "export-subtitles",
        help="write corrected subtitles as WebVTT, aligned to the video clock",
    )
    export.add_argument("--out", type=Path, default=Path("out/subtitles"),
                        help="directory to write .vtt files into")
    export.add_argument("--source", nargs="+", default=[], metavar="BUILD",
                        help="which subtitle build to export (default: subtitle)")
    export.add_argument("--translation", action="store_true",
                        help="include the translation as a second cue line")

    review = sub.add_parser("review", help="review the cards that are due")
    review.add_argument("--limit", type=int, default=20)
    review.add_argument("--source", nargs="+", default=[], metavar="BUILD",
                        help=SOURCE_HELP)

    serve = sub.add_parser("serve", help="browse the results at localhost")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-browser", action="store_true",
                       help="do not open a browser window")

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
    elif args.command == "export-subtitles":
        ExportSubtitlesCommand().run(
            app, args.out, tuple(args.source), args.translation
        )
    elif args.command == "fill-gaps":
        FillGapsCommand().run(app, args.limit, tuple(args.source))
    elif args.command == "review":
        ReviewCommand().run(app, args.limit, tuple(args.source))
    elif args.command == "serve":
        ServeCommand().run(app, args.port, not args.no_browser)
    elif args.command == "status":
        StatusCommand().run(app)
    elif args.command == "function-words":
        function_words(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
