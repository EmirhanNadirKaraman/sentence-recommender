"""CLI entry point."""
from __future__ import annotations

import argparse

from pathlib import Path

from commands import (
    AddVideoCommand, AddVideosCommand, BuildCorpusCommand, BuildRoadmapCommand,
    CheckWordCommand, DifficultyCommand, QuizCommand, UnblockCommand,
    BuildStudyListCommand, ExportSubtitlesCommand, FillGapsCommand,
    HuntVideosCommand, ReviewCommand, ServeCommand, StatusCommand,
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

    video = sub.add_parser(
        "add-video",
        help="scrape a YouTube video's subtitles into the catalogue",
    )
    video.add_argument("video", metavar="ID_OR_URL",
                       help="a YouTube video id, or any URL containing one")
    video.add_argument("--language", help="subtitle language (default: de)")

    many = sub.add_parser(
        "add-videos", help="scrape a list of videos into the catalogue")
    many.add_argument("source", metavar="FILE|lexy|-",
                      help="a file of ids or URLs, 'lexy' to read them from "
                           "that database, or '-' for standard input")
    many.add_argument("--language", help="subtitle language (default: de)")
    many.add_argument("--dry-run", action="store_true",
                      help="list what would be fetched, and stop")

    hunt = sub.add_parser(
        "hunt", help="find and add video for the words the corpus cannot teach")
    hunt.add_argument("--batch", type=int, default=10,
                      help="videos to add per round (default 10)")
    hunt.add_argument("--rounds", type=int, default=1,
                      help="how many times to repeat (default 1)")
    hunt.add_argument("--source", default="subtitle", help="corpus to grow")
    hunt.add_argument("--quality", action="store_true",
                      help="chase what a well-formed-only roadmap cannot reach")
    hunt.add_argument("--dry-run", action="store_true",
                      help="show what it would fetch, and stop")

    channel = sub.add_parser(
        "add-channel",
        help="add every video in a channel that has manual German subtitles")
    channel.add_argument("channel", metavar="ID|@HANDLE|URL")
    channel.add_argument("--limit", type=int, default=0,
                         help="stop after N videos (default: the whole channel)")
    channel.add_argument("--language", help="subtitle language (default: de)")
    channel.add_argument("--dry-run", action="store_true",
                         help="list what would be fetched, and stop")

    corpus = sub.add_parser("build-corpus", help="analyse and cache a sentence source")
    corpus.add_argument("source", choices=["subtitle"])
    corpus.add_argument(
        "--corrector", choices=["merge", "llm"], default="merge",
        help="how to turn subtitle lines into sentences; 'llm' repairs them "
             "with the local model and caches as 'subtitle:llm'",
    )
    corpus.add_argument("--limit", type=int, help="analyse only the first N sentences")
    corpus.add_argument("--min-words", type=int,
                        help="shortest sentence to keep (default 5)")

    plan = sub.add_parser("build-roadmap", help="run the greedy i+1 walk")
    plan.add_argument("--steps", type=int, help="stop after N steps")
    plan.add_argument("--source", nargs="+", default=[], metavar="BUILD",
                      help=SOURCE_HELP)
    plan.add_argument("--list-only", action="store_true",
                      help="count only what data/study_list.txt names, so a "
                           "noun is not learned twice as both a bare word and "
                           "an article form")
    plan.add_argument("--quality", action="store_true",
                      help="teach only from well-formed sentences")
    plan.add_argument("--strict", action="store_true",
                      help="only offer sentences where every other word is "
                           "already known, rather than every other word on "
                           "the study list; implies --goals")
    plan.add_argument("--goals", action="store_true",
                      help="aim at the list in data/final_result.txt instead "
                           "of making as many sentences readable as possible")

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
    serve.add_argument("--host", default="127.0.0.1",
                       help="address to bind. 0.0.0.0 reaches it from a phone "
                            "on the same wifi — there is no authentication, so "
                            "only on a network you trust")
    serve.add_argument("--no-browser", action="store_true",
                       help="do not open a browser window")

    sub.add_parser("build-study-list",
                   help="merge the ranking and the form dictionary into "
                        "data/study_list.txt")
    quiz = sub.add_parser(
        "quiz", help="check the words the roadmap assumes you already know")
    quiz.add_argument("--limit", type=int, default=40)
    quiz.add_argument("--source", default="subtitle")

    hard = sub.add_parser(
        "difficulty", help="how hard each video is, and what it would teach")
    hard.add_argument("--source", default="subtitle")
    hard.add_argument("--limit", type=int, default=30)
    hard.add_argument("--sort", default="yield",
                      choices=["yield", "comprehension", "i+1", "lines",
                               "unknown", "watch", "minutes"])

    seed = sub.add_parser(
        "unblock", help="the smallest vocabulary that gets the walk moving again")
    seed.add_argument("--source", default="subtitle")
    seed.add_argument("--limit", type=int, default=40)
    seed.add_argument("--quality", action="store_true",
                      help="only well-formed sentences, the ones worth learning from")
    seed.add_argument("--everything", action="store_true",
                      help="count every unit, not only the study list")

    check = sub.add_parser(
        "check", help="trace one word from the study list into the corpus")
    check.add_argument("word")

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
    if args.command == "add-video":
        AddVideoCommand().run(app, args.video, args.language)
    elif args.command == "add-videos":
        AddVideosCommand().run(app, args.source, args.language, args.dry_run)
    elif args.command == "hunt":
        HuntVideosCommand().run(app, args.batch, args.rounds, args.source,
                                args.dry_run, args.quality)
    elif args.command == "add-channel":
        AddVideosCommand().run(app, args.channel, args.language, args.dry_run,
                               args.limit)
    elif args.command == "quiz":
        QuizCommand().run(app, args.limit, args.source)
    elif args.command == "difficulty":
        DifficultyCommand().run(app, args.source, args.limit, args.sort)
    elif args.command == "unblock":
        UnblockCommand().run(app, args.source, not args.everything, args.limit,
                             args.quality)
    elif args.command == "check":
        CheckWordCommand().run(app, args.word)
    elif args.command == "build-corpus":
        BuildCorpusCommand().run(app, args.source, args.limit,
                                 args.corrector, args.min_words)
    elif args.command == "build-roadmap":
        BuildRoadmapCommand().run(app, args.steps, tuple(args.source),
                                  args.goals, args.list_only, args.quality,
                                  args.strict)
    elif args.command == "export-subtitles":
        ExportSubtitlesCommand().run(
            app, args.out, tuple(args.source), args.translation
        )
    elif args.command == "fill-gaps":
        FillGapsCommand().run(app, args.limit, tuple(args.source))
    elif args.command == "review":
        ReviewCommand().run(app, args.limit, tuple(args.source))
    elif args.command == "serve":
        ServeCommand().run(app, args.port, not args.no_browser, args.host)
    elif args.command == "build-study-list":
        BuildStudyListCommand().run(app)
    elif args.command == "status":
        StatusCommand().run(app)
    elif args.command == "function-words":
        function_words(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
