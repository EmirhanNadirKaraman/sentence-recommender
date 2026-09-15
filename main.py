"""CLI entry point."""
from __future__ import annotations

import argparse
from dataclasses import replace

from pathlib import Path

from commands import (
    AddVideoCommand, BlockersCommand, AddVideosCommand, BuildCorpusCommand, BuildRoadmapCommand,
    BuildVideoRoadmapCommand,
    CheckWordCommand, DifficultyCommand, QuizCommand, UnblockCommand,
    BuildStudyListCommand, BundleDeckCommand, CheckModelCommand,
    ExportDeckCommand,
    GlossDeckCommand,
    ExportSubtitlesCommand,
    FillGapsCommand, SpeakDeckCommand,
    HuntVideosCommand, ReviewCommand, ServeCommand, StatusCommand,
    SyncCatalogueCommand, OutOfReachCommand,
    BackfillChannelsCommand,
)
from config import Settings
from context import Application
from db import Database, WordRepository
from vocab.function_words import FunctionWordFile

SOURCE_HELP = (
    "corpus builds to use (default: all cached). "
    "e.g. --source subtitle:llm to study real video subtitles only"
)


from commands.export_deck import DEFAULT_LABEL as DECK_LABEL
from deck.speech import DEFAULT_HF_MODEL as HF_MODEL
from deck.speech import DEFAULT_ENGLISH as ENGLISH_VOICE
from deck.speech import DEFAULT_GERMAN as PIPER_VOICE


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
                      help="list what would be fetched, and stop; with "
                           "--auto, fetch and judge each track without "
                           "writing")
    many.add_argument("--pause", type=float, default=5.0,
                      help="seconds between videos on the --auto path "
                           "(default 5; the caption endpoint throttles)")
    many.add_argument("--auto", action="store_true",
                      help="where a video has no hand-written track, take a machine-generated one if it passes the quality gate; it lands in the `subtitle:auto` build, never beside the hand-written subtitles")

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
    hunt.add_argument("--goals-list", metavar="NAME",
                       help="saved word list to use, by name, instead of a file. `python main.py word-list` shows what there is")
    hunt.add_argument("--goals-file", metavar="PATH",
                      help="word list to chase, instead of data/study_list.txt")
    hunt.add_argument("--absent-only", action="store_true",
                      help="chase only the goals this corpus never says. The "
                           "rest are said but never alone, which more video "
                           "rarely fixes — they need the words around them "
                           "known, not another recording")

    channel = sub.add_parser(
        "add-channel",
        help="add every video in a channel that has manual German subtitles")
    channel.add_argument("channel", metavar="ID|@HANDLE|URL")
    channel.add_argument("--limit", type=int, default=0,
                         help="stop after N videos (default: the whole channel)")
    channel.add_argument("--language", help="subtitle language (default: de)")
    channel.add_argument("--dry-run", action="store_true",
                         help="list what would be fetched, and stop; with "
                              "--auto, fetch and judge each track without "
                              "writing")
    channel.add_argument("--pause", type=float, default=5.0,
                         help="seconds between videos on the --auto path "
                              "(default 5; the caption endpoint throttles)")
    channel.add_argument("--auto", action="store_true",
                         help="where a video has no hand-written track, take a machine-generated one if it passes the quality gate; it lands in the `subtitle:auto` build, never beside the hand-written subtitles")

    corpus = sub.add_parser("build-corpus", help="analyse and cache a sentence source")
    corpus.add_argument("source",
                        choices=["subtitle", "subtitle:auto", "transcript",
                                 "generated"])
    corpus.add_argument("--path", help="folder of .txt transcripts, for "
                                       "`build-corpus transcript`")
    corpus.add_argument(
        "--corrector", choices=["merge", "llm"], default="merge",
        help="how to turn subtitle lines into sentences; 'llm' repairs them "
             "with the local model and caches as 'subtitle:llm'",
    )
    corpus.add_argument("--workers", type=int, metavar="N",
                        help="processes for the rule-based correction "
                             "(default: cores minus one, capped at six). "
                             "1 runs it serially, as it always did")
    corpus.add_argument("--limit", type=int, help="analyse only the first N sentences")
    corpus.add_argument("--min-words", type=int,
                        help="shortest sentence to keep (default 5)")

    vplan = sub.add_parser("build-video-roadmap",
                           help="order the videos so each builds on the last")
    vplan.add_argument("--source", default="subtitle", metavar="BUILD")
    vplan.add_argument("--floor", type=int, default=40,
                       help="fewest subtitle lines a video needs to be planned")
    vplan.add_argument("--steps", type=int, help="stop after N videos")

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
    plan.add_argument("--goals-list", metavar="NAME",
                       help="saved word list to use, by name, instead of a file. `python main.py word-list` shows what there is")
    plan.add_argument("--goals-file", metavar="PATH",
                      help="word list to aim at, instead of data/study_list.txt. "
                           "One entry per line, or two tab-separated columns")
    plan.add_argument("--relax", action="store_true",
                      help="when nothing anywhere is one word away, teach two "
                           "from one sentence rather than stopping. Only at "
                           "that wall — the order stays i+1 while it can")
    plan.add_argument("--beginner", action="store_true",
                      help="seed from the function words alone, as someone "
                           "opening this for the first time would — not from "
                           "this reader's own vocabulary")
    plan.add_argument("--unblock", action="store_true",
                      help="with --strict, let the walk teach a word that is "
                           "not on the list when one stands between it and a "
                           "goal. Stored under its own name, since it is a "
                           "different curriculum")
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

    check = sub.add_parser(
        "check-model",
        help="is the local model reachable, and how fast is it?",
    )
    check.add_argument("--steps", type=int, default=3861,
                       help="how many steps to estimate a run over")

    deck = sub.add_parser(
        "export-deck",
        help="write the teaching order as a PDF and a slideshow",
    )
    deck.add_argument("--out", type=Path, default=Path("out/deck"),
                      help="directory to write the files into")
    deck.add_argument("--label", default=DECK_LABEL,
                      help="which stored plan to export")
    deck.add_argument("--format", nargs="+", dest="formats",
                      choices=("pdf", "pptx"), default=["pdf", "pptx"],
                      help="which files to write (default: both)")
    deck.add_argument("--limit", type=int, default=None,
                      help="only the first N steps, for a quick look")
    deck.add_argument("--examples", type=int, default=3,
                      help="sentences per card")

    bundle = sub.add_parser(
        "bundle-deck",
        help="join the clips into episodes with chapter timestamps",
    )
    bundle.add_argument("--audio", type=Path, default=Path("out/audio"),
                        help="where `speak-deck` wrote the clips")
    bundle.add_argument("--out", type=Path, default=Path("out/episodes"),
                        help="where to write the episodes")
    bundle.add_argument("--label", default=DECK_LABEL)
    bundle.add_argument("--per", type=int, default=50,
                        help="words per episode (default 50, about 23 min)")
    bundle.add_argument("--examples", type=int, default=3)
    bundle.add_argument("--limit", type=int, default=None)

    gloss = sub.add_parser(
        "gloss-deck",
        help="write each card's English with a local model",
    )
    gloss.add_argument("--label", default=DECK_LABEL)
    gloss.add_argument("--out", type=Path, default=Path("out/deck"),
                       help="where to re-render the PDF as it goes")
    gloss.add_argument("--log", type=Path, default=Path("out/gloss.log"),
                       help="a text log to tail while it runs")
    gloss.add_argument("--workers", type=int, default=2,
                       help="calls in flight; more needs more KV cache")
    gloss.add_argument("--every", type=int, default=50,
                       help="re-render the PDF every N cards")
    gloss.add_argument("--examples", type=int, default=3,
                       help="sentences per card")
    gloss.add_argument("--limit", type=int, default=None,
                       help="only the first N steps")

    aloud = sub.add_parser(
        "speak-deck",
        help="read the teaching order aloud with a local model",
    )
    aloud.add_argument("--out", type=Path, default=Path("out/audio"),
                       help="directory to write one WAV per step into")
    aloud.add_argument("--label", default=DECK_LABEL,
                       help="which stored plan to read")
    aloud.add_argument("--engine", choices=("piper", "transformers"),
                       default="piper",
                       help="piper for the whole deck; transformers for your "
                            "own weights")
    aloud.add_argument("--german", default=PIPER_VOICE,
                       help="piper voice for the German lines")
    aloud.add_argument("--english", default=ENGLISH_VOICE,
                       help="piper voice for the English lines")
    aloud.add_argument("--slow", action="store_true",
                       help="read the teaching sentence a second time, slower")
    aloud.add_argument("--examples", type=int, default=3,
                       help="sentences per card")
    aloud.add_argument("--model", default=HF_MODEL,
                       help="transformers: hub id or a local directory")
    aloud.add_argument("--device", default=None,
                       help="transformers: cuda, mps or cpu (default: best)")
    aloud.add_argument("--limit", type=int, default=None,
                       help="only the first N steps")
    aloud.add_argument("--overwrite", action="store_true",
                       help="re-read sentences that already have a file")
    aloud.add_argument("--german-only", action="store_true",
                       dest="german_only",
                       help="read cards that have no English yet, in German "
                            "alone, instead of leaving them for a later run")
    aloud.add_argument("--cuda", action="store_true",
                       help="piper: use the CUDA execution provider")

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

    blockers = sub.add_parser(
        "blockers", help="what stands between the roadmap and the rest of the "
                         "study list, and what it would cost to free them")
    blockers.add_argument("--source", nargs="+", default=[],
                          metavar="BUILD", help=SOURCE_HELP)
    blockers.add_argument("--limit", type=int, default=15)
    blockers.add_argument("--goals-list", metavar="NAME",
                       help="saved word list to use, by name, instead of a file. `python main.py word-list` shows what there is")
    blockers.add_argument("--goals-file", metavar="PATH",
                          help="word list to report against")
    blockers.add_argument("--all-sentences", action="store_true",
                          help="count from every sentence, not only well-formed ones")
    blockers.add_argument("--budget", type=int, default=150,
                          help="how many words from outside the list to price, "
                               "most useful first. The curve has no natural "
                               "end — given enough words the walk clears "
                               "almost anything — so this bounds the head of "
                               "it, where one word still frees many")

    sub.add_parser("build-study-list",
                   help="merge the ranking and the form dictionary into "
                        "data/study_list.txt")
    quiz = sub.add_parser(
        "quiz", help="check the words the roadmap assumes you already know")
    quiz.add_argument("--limit", type=int, default=40)
    quiz.add_argument("--source", default="subtitle")
    quiz.add_argument("--from", dest="files", default="both",
                      choices=("both", "known", "function"),
                      help="which vocabulary file to check (default: both)")

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

    sync = sub.add_parser(
        "sync-catalogue",
        help="refill this project's database from the shared one")
    sync.add_argument("--from", dest="source_db", required=True,
                      metavar="DATABASE",
                      help="the database to copy out of, on the same server "
                           "(language-app's is 'german_vocabulary')")
    sync.add_argument("--table", action="append", default=[], metavar="NAME",
                      help="copy only this table (repeatable); default is all")
    sync.add_argument("--dry-run", action="store_true",
                      help="say what would be copied, and stop")
    sync.add_argument("--replace", action="store_true",
                      help="sync even though videos scraped here are not "
                           "upstream, discarding them")

    fill = sub.add_parser(
        "backfill-channels",
        help="ask YouTube which channel each video came from")
    fill.add_argument("--limit", type=int, default=0,
                      help="stop after N videos (default: all of them)")
    fill.add_argument("--delay", type=float, default=15.0,
                      help="seconds between calls (default 15; five was "
                           "enough to be throttled)")
    fill.add_argument("--give-up", type=int, default=5, metavar="N",
                      help="stop after N refusals in a row (default 5)")
    fill.add_argument("--dry-run", action="store_true",
                      help="say what it would ask about, and stop")

    sub.add_parser("status", help="what is built and what is due")
    sub.add_parser("function-words", help="regenerate the closed-class review file")
    sub.add_parser("schema-doc", help="regenerate DATABASE.md from both databases")

    reach = sub.add_parser(
        "out-of-reach",
        help="write down the goals the corpus cannot teach, and why")
    reach.add_argument("--source", nargs="+", default=[], metavar="BUILD",
                       help=SOURCE_HELP)
    reach.add_argument("--out", metavar="PATH",
                       help="where to write it (default: beside the goal list)")
    reach.add_argument("--counting", choices=("strict", "list"),
                       default="strict",
                       help="which reading to report on. Strict counts every "
                            "word in a sentence and is what the page serves; "
                            "list counts only what the goal file names")
    reach.add_argument("--unblock", action="store_true",
                       help="report against the plan that may teach a word "
                            "off the list to clear the way to a goal")
    reach.add_argument("--all-sentences", action="store_true",
                       help="count badly-formed sentences as teaching material")
    reach.add_argument("--goals-list", metavar="NAME",
                       help="saved word list to use, by name, instead of a file. `python main.py word-list` shows what there is")
    reach.add_argument("--goals-file", metavar="PATH",
                       help="word list to report on, instead of the default")
    lists = sub.add_parser(
        "word-list", help="the word lists you have saved, and their contents")
    lists.add_argument("name", nargs="?", help="show one list's entries")
    lists.add_argument("--save", metavar="NAME",
                       help="save a list under this name")
    lists.add_argument("--from", dest="source_file", metavar="PATH",
                       help="read the entries to save from this file")
    lists.add_argument("--forget", metavar="NAME", help="delete a saved list")
    lists.add_argument("--rename", metavar="NEW",
                       help="rename the named list. A plan's label carries "
                            "the list name, so a renamed list looks for "
                            "plans built under the new name")

    captions = sub.add_parser(
        "caption-check",
        help="measure what auto-generated captions would cost, against the "
             "hand-written tracks already held")
    captions.add_argument("--limit", type=int, default=20,
                          help="how many videos to compare (default 20)")
    captions.add_argument("--source", default="subtitle", metavar="BUILD",
                          help="which build holds the manual side")
    captions.add_argument("--pause", type=float, default=1.5,
                          help="seconds between videos")

    sampler = sub.add_parser(
        "sample-channel",
        help="probe a channel's hand-written subtitle rate before importing "
             "it, sampling evenly rather than from the newest")
    sampler.add_argument("channel", metavar="ID|@HANDLE|URL")
    sampler.add_argument("--sample", type=int, default=12,
                         help="how many videos to probe (default 12)")
    sampler.add_argument("--language", default="de",
                         help="subtitle language (default: de)")
    sampler.add_argument("--pause", type=float, default=1.0,
                         help="seconds between probes")

    look_up = sub.add_parser(
        "lookup", help="the stranded words, as caption-search links to click")
    look_up.add_argument("--limit", type=int, default=25,
                         help="how many to print (default 25)")
    look_up.add_argument("--source", nargs="+", default=[], metavar="BUILD")
    look_up.add_argument("--all", action="store_true", dest="every",
                         help="include words the corpus says but never alone "
                              "— more video rarely helps those")
    look_up.add_argument("--goals-list", metavar="NAME")
    look_up.add_argument("--goals-file", metavar="PATH")

    cover = sub.add_parser(
        "cover", help="the fewest minutes of video that teach a saved list")
    cover.add_argument("--source", nargs="+", default=[], metavar="BUILD",
                       help="which build to choose videos from (default: "
                            "subtitle; only timed builds can be in a cover)")
    cover.add_argument("--depth", type=int, default=5,
                       help="sentences wanted per word (default 5). A word "
                            "with fewer is asked for what exists")
    cover.add_argument("--floor", type=int, metavar="LINES",
                       help="shortest video that may be chosen, in lines "
                            "(default 40) — without one a cover is clips")
    cover.add_argument("--dry-run", action="store_true",
                       help="print it and store nothing")
    cover.add_argument("--goals-list", metavar="NAME",
                       help="saved word list to cover")
    cover.add_argument("--goals-file", metavar="PATH",
                       help="word list file to cover, instead of a saved one")

    look = sub.add_parser(
        "search", help="find a word in the corpus vocabulary, misspellings and all")
    look.add_argument("term", help="what to look for")
    look.add_argument("--limit", type=int, default=20)
    look.add_argument("--source", nargs="+", default=[], metavar="BUILD",
                      help=SOURCE_HELP)

    return parser


def function_words(app: Application) -> None:
    with Database(app.settings.own) as db:
        words = WordRepository(db, app.settings.language).function_words()
    count = FunctionWordFile().write(app.settings.function_words, words)
    print(f"wrote {app.settings.function_words} — {count} lemmas")


def word_lists(app: Application, args) -> None:
    """Show, save or forget the lists the reader has built."""
    from vocab.word_lists import WordListStore            # noqa: PLC0415
    store = WordListStore(app.settings.state_path)
    if args.rename:
        if not args.name:
            raise SystemExit("--rename needs the current name: "
                             "`word-list OLD --rename NEW`")
        moved = store.rename(args.name, args.rename)
        if not moved:
            raise SystemExit(f"no saved list called {args.name!r}")
        print(f"renamed {args.name!r} to {args.rename!r} — {moved:,} entries")
    elif args.forget:
        store.forget(args.forget)
        print(f"forgot {args.forget!r}")
    elif args.save:
        if not args.source_file:
            raise SystemExit("--save needs --from PATH to read entries from")
        source = Path(args.source_file)
        if not source.exists():
            raise SystemExit(f"no file at {source}")
        entries = [line.split("\t")[-1].strip()
                   for line in source.read_text(encoding="utf-8").splitlines()
                   if line.strip() and not line.startswith("#")]
        n = store.save(args.save, entries, note=str(source))
        print(f"saved {args.save!r} — {n:,} entries from {source}")
    elif args.name:
        entries = store.entries(args.name)
        if not entries:
            raise SystemExit(f"no saved list called {args.name!r}")
        print(f"{args.name} — {len(entries):,} entries")
        for entry in entries:
            print(f"  {entry}")
    else:
        rows = store.names()
        if not rows:
            print("no saved lists yet — `word-list --save NAME --from PATH`")
        for name, count, saved in rows:
            print(f"  {name:<24} {count:>6,} entries   saved {saved}")


def search_vocabulary(app: Application, term: str, limit: int,
                      builds: tuple[str, ...]) -> None:
    """What the corpus says that looks like this."""
    from vocab.search import UnitSearch                   # noqa: PLC0415
    wanted = list(builds) or list(app.corpus_store.builds())
    if not wanted:
        raise SystemExit("no cached corpus — run `build-corpus` first")
    search = UnitSearch(app.corpus_store.unit_counts(*wanted))
    found = search.find(term, limit=limit)
    print(f"{len(search):,} units in {'+'.join(wanted)}; "
          f"{len(found)} like {term!r}")
    for unit, said, score in found:
        kind = "pattern" if unit.is_pattern else "word"
        print(f"  {score:>5.2f}  {said:>6,}x  [{kind}] {unit.key}")


def main() -> int:
    args = _parser().parse_args()
    settings = Settings()
    if getattr(args, "goals_list", None):
        # Named rather than pathed, but still given a path: the stem is what
        # a plan's label carries, and a stored list needs a name there like
        # any other. The file need not exist — the entries come from the
        # table, and `goal_entries` is what tells `Application` to use them.
        from vocab.word_lists import WordListStore      # noqa: PLC0415
        store = WordListStore(settings.state_path)
        if args.goals_list not in store:
            raise SystemExit(f"no saved list called {args.goals_list!r} — "
                             "`python main.py word-list` shows what there is")
        settings = replace(
            settings,
            goal_words=settings.data_dir / f"{args.goals_list}.txt",
            goal_entries=store.entries(args.goals_list))
    elif getattr(args, "goals_file", None):
        # A different list changes the goals, and everything derived from them
        # follows: `covered_forms`, the teaching order, what counts as
        # stranded. The resolved cache is stamped on the file, so it
        # invalidates itself.
        chosen = Path(args.goals_file)
        if not chosen.exists():
            raise SystemExit(f"no word list at {chosen}")
        settings = replace(settings, goal_words=chosen)
    app = Application(settings)
    if args.command == "add-video":
        AddVideoCommand().run(app, args.video, args.language)
    elif args.command == "add-videos":
        AddVideosCommand().run(app, args.source, args.language, args.dry_run,
                               accept_auto=args.auto, pause=args.pause)
    elif args.command == "hunt":
        HuntVideosCommand().run(app, args.batch, args.rounds, args.source,
                                args.dry_run, args.quality, args.absent_only)
    elif args.command == "add-channel":
        AddVideosCommand().run(app, args.channel, args.language, args.dry_run,
                               args.limit, accept_auto=args.auto,
                               pause=args.pause)
    elif args.command == "quiz":
        QuizCommand().run(app, args.limit, args.source, args.files)
    elif args.command == "difficulty":
        DifficultyCommand().run(app, args.source, args.limit, args.sort)
    elif args.command == "unblock":
        UnblockCommand().run(app, args.source, not args.everything, args.limit,
                             args.quality)
    elif args.command == "check":
        CheckWordCommand().run(app, args.word)
    elif args.command == "blockers":
        BlockersCommand().run(app, tuple(args.source), args.limit,
                              not args.all_sentences, args.budget)
    elif args.command == "build-corpus":
        BuildCorpusCommand().run(app, args.source, args.limit,
                                 args.corrector, args.min_words, args.path,
                                 args.workers)
    elif args.command == "build-video-roadmap":
        BuildVideoRoadmapCommand().run(app, args.source, args.floor, args.steps)
    elif args.command == "build-roadmap":
        BuildRoadmapCommand().run(app, args.steps, tuple(args.source),
                                  args.goals, args.list_only, args.quality,
                                  args.strict, args.relax, args.unblock,
                                  args.beginner)
    elif args.command == "bundle-deck":
        BundleDeckCommand().run(app, args.audio, args.out,
                                args.label, args.per,
                                args.examples, args.limit)
    elif args.command == "check-model":
        CheckModelCommand().run(app, args.steps)
    elif args.command == "export-deck":
        ExportDeckCommand().run(app, args.out, args.label,
                                tuple(args.formats), args.limit,
                                args.examples)
    elif args.command == "gloss-deck":
        GlossDeckCommand().run(app, args.label, args.out, args.log,
                               args.workers, args.every, args.limit,
                               args.examples)
    elif args.command == "speak-deck":
        SpeakDeckCommand().run(app, args.out, args.label, args.engine,
                               args.german, args.english, args.model,
                               args.device, args.limit, args.overwrite,
                               args.cuda, args.slow, args.examples,
                               args.german_only)
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
    elif args.command == "sync-catalogue":
        SyncCatalogueCommand().run(app, args.source_db, tuple(args.table),
                                   args.dry_run, args.replace)
    elif args.command == "status":
        StatusCommand().run(app)
    elif args.command == "function-words":
        function_words(app)
    elif args.command == "backfill-channels":
        BackfillChannelsCommand().run(app, args.limit, args.delay,
                                      args.give_up, args.dry_run)
    elif args.command == "out-of-reach":
        OutOfReachCommand().run(app, tuple(args.source), args.out,
                                not args.all_sentences, args.counting,
                                args.unblock)
    elif args.command == "caption-check":
        from commands.caption_check import CaptionCheckCommand  # noqa: PLC0415
        CaptionCheckCommand().run(app, args.limit, args.source, args.pause)
    elif args.command == "sample-channel":
        from commands.sample_channel import SampleChannelCommand  # noqa: PLC0415
        SampleChannelCommand().run(app, args.channel, args.sample,
                                   args.language, args.pause)
    elif args.command == "lookup":
        from commands.lookup_links import LookupCommand      # noqa: PLC0415
        LookupCommand().run(app, args.limit, tuple(args.source),
                            not args.every)
    elif args.command == "cover":
        from commands.cover_list import CoverListCommand   # noqa: PLC0415
        CoverListCommand().run(app, tuple(args.source), args.depth,
                               args.floor, args.dry_run)
    elif args.command == "word-list":
        word_lists(app, args)
    elif args.command == "search":
        search_vocabulary(app, args.term, args.limit, tuple(args.source))
    elif args.command == "schema-doc":
        from db.schema_doc import write        # noqa: PLC0415 — only here
        print(f"wrote {write(app)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
