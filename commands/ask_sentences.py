"""`ask-sentences` — every question of the corpus pass, of every subtitle
sentence, once.

One request per sentence, carrying all of `corpus.questions`: whether it
stands alone, is complete, standard and well formed, whether it holds a
fixed expression, which level could read it, and per pattern unit in it
whether the word is the word itself and how much the sentence gives it
away. The state is charged once per request and the questions run in
parallel over it, which is why they travel together rather than one pass
per question. Answers land raw in `corpus.answers`, keyed by text, unit,
question, version and model; every threshold stays in code.

Subtitle text only. The transcripts are somebody's material and do not
leave the machine; the overlay-only sentences are never shown and are not
asked about. Resumable: a sentence the model has answered at this version
is skipped, so a run that dies is picked up where it stopped.

Ordered as `translate-sentences` orders: what a card shows first, then
what the walk weighed, then the rest of the teachable build. About a
thousand input tokens a sentence, and the vendor charges only for input;
the whole build is on the order of ten dollars and four hours at the rate
limit, and the first five hundred sentences say what the real figures are
before anything else is spent.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from deck.spoken import spoken
from vocab.entry import Unit

# What the vendor charges per million input tokens; output is free.
PER_MILLION = 0.042
# Progress every so many sentences, with exact counts.
EVERY = 500
# Consecutive failed requests before the run stops asking, on the same
# reasoning as `translate-sentences`: twenty in a row is the service, not
# the sentences.
GIVE_UP = 20


def _once(surface: str) -> str:
    """The matcher writes a token twice when two of its rules claim it —
    `tue mir mir an an` — and the matcher is fingerprinted, so the repeat
    is dropped here rather than there."""
    words: list[str] = []
    for word in surface.split():
        if not words or words[-1] != word:
            words.append(word)
    return " ".join(words)


def state_and_questions(sentence, skip: frozenset[str] = frozenset()):
    """One request: the state and the questions, from a corpus sentence."""
    from corpus import questions                          # noqa: PLC0415
    units: dict[str, dict] = {}
    which: dict[str, Unit] = {}
    surfaces = dict(sentence.surfaces)
    for n, unit in enumerate(sorted((u for u in sentence.units if u.is_pattern),
                                    key=lambda u: u.key), 1):
        ident = f"u{n}"
        which[ident] = unit
        units[ident] = {"spoken": spoken(unit.key), "canonical": unit.key,
                        "surface": _once(surfaces.get(unit, ""))}
    return (questions.state_for(sentence.text, units),
            questions.questions_for(units, skip=skip), which)


def read(response, asked) -> dict[str, tuple[float, dict | None]]:
    """Every answer as (value, distribution): a Noul's probability, a
    Score's expected level scaled to 0–1, a Choice's expected level over
    its ordered labels scaled to 0–1 with the distribution kept."""
    from corpus.questions import LEVELS                   # noqa: PLC0415
    out = {}
    for ident, question in asked.items():
        answer = response.answers[ident]
        kind = getattr(answer, "type", "")
        if kind == "noul":
            out[ident] = (answer.noul, None)
        elif kind == "score":
            top = max(answer.legend) if answer.legend else 1
            out[ident] = (answer.score / max(top, 1), None)
        elif kind == "choice":
            probabilities = dict(answer.probabilities)
            expected = sum(probabilities.get(label, 0.0) * i
                           for i, label in enumerate(LEVELS)) / (len(LEVELS) - 1)
            out[ident] = (expected, probabilities)
    return out


def _of_the_best_videos(app, sentences, count: int | None, per_video: int | None = None,
                        have: frozenset[str] = frozenset()):
    """The lines of the reel's best `count` videos, best video first.

    As the reel last ranked them (`ScoreStore.latest`), the videos it
    refuses to offer left out (`ENOUGH_LINES`), a removed channel's too.
    Best first, so a run that stops early has covered the top of the
    feed, which is what a reader sees. `count` None is every video.

    `per_video` asks about a sample of each video's lines instead of all
    of them -- `corpus.levels.sample`, the same lines every run, drawn
    from all the video's lines and not just the unanswered ones, or a
    resumed run would draw a fresh thirty each time. `have` is what is
    already answered, left out after the draw.
    """
    from corpus.levels import sample                         # noqa: PLC0415
    from scores import ScoreStore                            # noqa: PLC0415
    from watchability import ENOUGH_LINES                    # noqa: PLC0415
    banned = app.banned_videos()
    ranked = [row["video"] for row in ScoreStore(app.settings.state_path).latest()
              if row["lines"] >= ENOUGH_LINES and row["video"] not in banned][:count]
    place = {video: n for n, video in enumerate(ranked)}
    chosen = [s for s in sentences if s.timing and s.timing.video_id in place]
    if per_video:
        by_video: dict[str, list] = {}
        for s in chosen:
            by_video.setdefault(s.timing.video_id, []).append(s)
        drawn = {(video, text) for video, lines in by_video.items()
                 for text in sample(video, (s.text for s in lines), per_video)}
        chosen = [s for s in chosen if (s.timing.video_id, s.text) in drawn]
    chosen = [s for s in chosen if s.text not in have]
    return sorted(chosen, key=lambda s: (place[s.timing.video_id], s.timing.start))


class AskSentencesCommand:
    def run(self, app, limit: int | None = None, workers: int | None = None,
            dry_run: bool = False, log: Path = Path("out/ask.log"),
            plan: str | None = None, skip: tuple[str, ...] = (),
            only: tuple[str, ...] = (), videos: int | None = None,
            per_video: int | None = None) -> None:
        """`plan` restricts the run to one stored plan's candidates — the
        sentences that plan's cards show or could show — and `skip` names
        questions to leave out. Both are how a budget is met: the vendor
        charges per question per request, so the only savings are fewer
        sentences and fewer questions, and a sentence no card of the plan
        you use can show is the first not to ask about.

        `videos` is the other selection: the lines of the reel's best `N`
        videos as last scored, best first, for the numbers the reel wants
        of a whole video rather than of a card's sentence — its level
        above all; `per_video` takes a fixed sample of each video's lines
        instead of all of them (see `corpus.levels`). `only` is `skip` the
        other way round, for the run that asks one or two questions of
        many lines; a sentence is skipped as answered when it holds every
        question the run asks.
        """
        import os                                            # noqa: PLC0415
        from config import load_dotenv                       # noqa: PLC0415
        from corpus import questions                         # noqa: PLC0415
        from state import open_state                         # noqa: PLC0415

        load_dotenv()
        settings = app.settings
        model = settings.judge_model
        workers = workers or settings.judge_workers
        if not os.environ.get("TYPESAFE_API_KEY") and not dry_run:
            raise SystemExit("TYPESAFE_API_KEY is not set in .env")

        skipped = frozenset(skip)
        if only:
            skipped |= set(questions.NAMES) - set(only)
        unknown = (skipped | set(only)) - set(questions.NAMES)
        if unknown:
            raise SystemExit(f"no such question: {', '.join(sorted(unknown))}"
                             f" — the questions are {', '.join(questions.NAMES)}")
        asking = tuple(q for q in (*questions.SENTENCE, "level") if q not in skipped)
        if not asking:
            raise SystemExit("nothing left to ask about the sentence itself")
        sentences = app.corpus("subtitle")
        have = app.answers.answered(model, questions.VERSION, asking)
        # Every stored plan, or the one whose label matches `plan`.
        like = f"%{plan}%" if plan else "%"
        with open_state(settings.state_path) as conn:
            shown = {t for (t,) in conn.execute(
                "SELECT sentence FROM roadmap WHERE source LIKE ?"
                " UNION SELECT text FROM roadmap_example WHERE source LIKE ? AND n < 3",
                (like, like))}
            weighed = {t for (t,) in conn.execute(
                "SELECT DISTINCT text FROM roadmap_example WHERE source LIKE ?", (like,))}

        def tier(s) -> int:
            return 0 if s.text in shown else 1 if s.text in weighed else 2

        todo = sorted((s for s in sentences if s.text not in have), key=tier)
        if plan:
            todo = [s for s in todo if tier(s) < 2]
        if videos or per_video:
            todo = _of_the_best_videos(app, sentences, videos, per_video, frozenset(have))
        tiers = Counter(tier(s) for s in todo)
        print(f"{len(sentences):,} teachable subtitle sentences · "
              f"{len(have):,} answered by {model} at version {questions.VERSION} · "
              f"{len(todo):,} to ask"
              + (f" for the plan matching {plan!r}" if plan else "")
              + (f" in the reel's best {videos:,} videos" if videos else
                 " in every video the reel offers" if per_video else "")
              + (f", {per_video} lines a video" if per_video else ""),
              flush=True)
        if videos or per_video:
            print(f"  best video first · asking {', '.join(asking)}"
                  + ("" if "plain" in skipped else " · plain per unit"), flush=True)
        else:
            print(f"  in order: {tiers[0]:,} shown on a card · {tiers[1]:,} the walk "
                  f"weighed" + ("" if plan else f" · {tiers[2]:,} more")
                  + (f" · without {', '.join(sorted(skipped))}" if skipped else ""),
                  flush=True)
        if limit:
            todo = todo[:limit]
            print(f"  asking about the first {len(todo):,}", flush=True)
        if not todo:
            print("nothing to do")
            return

        if dry_run:
            state, asked, _ = state_and_questions(todo[0], skipped)
            print("\nstate:")
            print(json.dumps(state, ensure_ascii=False, indent=1))
            print("\nquestions:")
            for ident, question in asked.items():
                print(f"  {ident}: {type(question).__name__} — "
                      f"{str(question.instructions)[:90]}")
            return

        from typesafe_sdk import RetryPolicy, TypeSafeClient  # noqa: PLC0415
        client = TypeSafeClient(model=model, retry=RetryPolicy(max_retries=4, timeout=30.0))
        print(f"  {model} · {workers} in flight", flush=True)

        trouble = {"streak": 0}
        started = time.perf_counter()
        tokens = 0
        failed = 0

        def ask(sentence):
            if trouble["streak"] >= GIVE_UP:
                return sentence, None, None, None
            state, asked, which = state_and_questions(sentence, skipped)
            try:
                response = client.system_one(state, asked)
            except Exception as error:                        # noqa: BLE001 — logged
                return sentence, None, None, repr(error)[:200]
            return sentence, read(response, asked), which, response.usage.input_tokens

        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as out, \
                ThreadPoolExecutor(max_workers=workers) as pool:
            for index, (sentence, answers, which, extra) in enumerate(
                    pool.map(ask, todo), 1):
                if answers is None:
                    failed += 1
                    trouble["streak"] += 1
                    out.write(f"FAILED\t{sentence.text}\t{extra}\n")
                else:
                    trouble["streak"] = 0
                    tokens += extra
                    app.answers.save(sentence.text, model, questions.VERSION,
                                     answers, units=which)
                    brief = " ".join(f"{k}={v[0]:.2f}" for k, v in answers.items())
                    out.write(f"{sentence.text}\t{brief}\n")
                if index % EVERY == 0 or index == len(todo):
                    rate = index / max(time.perf_counter() - started, 1e-9)
                    left = (len(todo) - index) / rate / 3600 if rate else 0
                    print(f"  … {index:>7,}/{len(todo):,} · {failed:,} failed · "
                          f"{tokens:,} tokens ${tokens / 1e6 * PER_MILLION:.2f} · "
                          f"{rate * 3600:,.0f}/h · {left:.1f} h left", flush=True)
        client.close()
        if trouble["streak"] >= GIVE_UP:
            print(f"stopped: {GIVE_UP} requests failed in a row — see {log}")
        counts = app.answers.counts()
        print(f"done · {tokens:,} input tokens · ${tokens / 1e6 * PER_MILLION:.2f} · "
              f"{counts.get('complete', 0):,} sentences answered in all")
