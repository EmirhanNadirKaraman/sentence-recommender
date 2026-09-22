"""`translate-sentences` — an English line for every sentence the roadmap holds.

`gloss-deck` translates a sentence only when a card shows it, and only beside
the word the card teaches: 16,526 sentences out of the 398,935 the corpus
holds without English. This asks about the rest, twenty at a time, with no
word attached -- the sentence alone, translated as it stands.

The roadmap by default, not the corpus: the sentence each step teaches with
and every candidate the walk weighed for it, about a hundred thousand
sentences, which is ten hours at the rate the endpoint answers. The corpus
is four times that, and the other three hundred thousand are sentences no
page shows unless a unit page is browsed or a video watched with the
overlay on. `--all` asks about them too, for when the endpoint is faster or
the roadmap is done.

Into the same table the gloss writes, `sentence_english`, under its own
`source`. The deck reads that table already, so every card whose sentences
this has reached gains its English without anything else changing -- and
`deck.gloss` says why the gloss is still asked afterwards, and why its answer
wins when both have one.

Order matters within that too, because the run is hours long and can be
stopped at any point without losing anything: a sentence is written the
moment its batch lands, keyed by its text, and a second run asks only about
what has no row yet. So the sentences the roadmap and its cards show go
first, then every sentence the walk weighed as a candidate; under `--all`,
then the rest of what is teachable, and last the rows a build keeps purely
so the video overlay has no gaps. Stopping early leaves the deck done and
the rest half done, which is the right half.

Built on the rails `polish-sentences` laid: a batch is asked as numbered
sentences and answered with the number echoed back, so a reply with nineteen
entries for twenty sentences loses one translation rather than attaching
nineteen to the wrong German. A batch that fails is owed, not stored, and a
run that fails twenty batches running stops rather than recording ten
thousand failures against an endpoint that has gone away.

Answered as numbered lines, not JSON, and that is a measured choice rather
than a stylistic one. The endpoint is generation-bound -- one request at a
time, forty-odd tokens a second -- so what the run costs is the tokens the
model emits. Wrapped as `{"n": 12, "english": "..."}` a sentence cost 34.5
of them; as `12. ...` it costs 15.2, for the same English and, on sixty
sentences, nothing lost. Guided decoding went with the JSON. The number at
the head of each line is what keeps the pairing honest, and a line without
one is not an answer and is simply owed again.
"""
from __future__ import annotations

import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

BATCH = 20
# A batch is also bounded in words, because the overlay-only rows are the
# lines the filter set aside for their length -- the median is four words
# and the longest is 26,059, an unsplit transcript in one row. Twenty of
# the long ones is more than a server slot's context, and the run stalled
# on such batches for two minutes at a time, three retries each. Lines
# longer than `TOO_LONG` are not sent at all: nothing reads a caption that
# long, and the model cannot answer it inside a slot.
BATCH_WORDS = 400
TOO_LONG = 120


def blocks_of(todo: list[str], batch: int) -> list[list[str]]:
    """Batches of at most `batch` lines and about `BATCH_WORDS` words."""
    out: list[list[str]] = []
    block: list[str] = []
    words = 0
    for text in todo:
        n = len(text.split())
        if block and (len(block) >= batch or words + n > BATCH_WORDS):
            out.append(block)
            block, words = [], 0
        block.append(text)
        words += n
    if block:
        out.append(block)
    return out
# In flight at once, when the server will not say how many it can take.
# Measured on 200-sentence pilots against a llama.cpp server with one slot,
# at twenty per batch: two workers and four both answered 1.15 sentences a
# second, eight answered 0.78, and forty per batch at four workers 1.05.
# Past the slot count a request only queues, and a pool sized to the queue
# was slower, not merely no faster -- the same slot arithmetic
# `deck.gloss.run` records. With the server reloaded at seven slots, seven
# workers answered 12.4 a second; so the count is asked for, not assumed.
WORKERS = 2
# Every so many sentences, a line saying where the run has got to. Exact
# counts, measured rate, and no projection of when it will finish.
REPORT = 500
# Consecutive failed batches before the run stops asking. See
# `polish-sentences` for the night this number was learned.
GIVE_UP = 20

SYSTEM = (
    "You translate German into English for a learner.\n"
    "You are given numbered German sentences, mostly lines of speech from "
    "videos. Reply with the same numbers, one line each: the number, a full "
    "stop, a space, and one natural English translation. Nothing else -- no "
    "heading, no notes.\n"
    "Translate each sentence on its own, as it stands. Keep the register: "
    "casual German is casual English. Keep names as they are. If a sentence "
    "is a fragment or is cut off, translate the fragment; do not complete "
    "it, and do not explain. If a sentence is already English, or is not "
    "German, return it unchanged."
)

# `12. ...` -- the number the model echoed, then its answer. A `)` is
# tolerated because the model reaches for one now and then.
_LINE = re.compile(r"^\s*(\d+)[.)]\s+(.*\S)\s*$")
_SPACE = re.compile(r"\s+")

# A tunnel that gave up on the origin, rather than a model that said
# something wrong -- the same set `deck.gloss` waits on, for the same reasons.
_OVERLOADED = frozenset({429, 500, 502, 503, 504, 520, 522, 524})


def parse(reply: str, block: list[str]) -> dict[str, str]:
    """The answer as sentence -> English, for the sentences it answered.

    Indexed by the number the model echoed, never by position. A sentence
    the reply skips, or answers on a line with no number, is simply absent
    and stays owed.

    An answer that repeats the German is stored as nothing rather than
    dropped: the prompt asks for exactly that when a line is not German, so
    it is an answer, and asking again would cost the same to be told the
    same. It reads as "asked, nothing to show", which is how the deck
    already treats a sentence the gloss declined.
    """
    out: dict[str, str] = {}
    for line in reply.splitlines():
        found = _LINE.match(line)
        if not found:
            continue
        index = int(found.group(1)) - 1
        if not 0 <= index < len(block):
            continue
        original = block[index]
        english = _SPACE.sub(" ", found.group(2)).strip()
        if english.lower() == _SPACE.sub(" ", original).strip().lower():
            english = ""
        out[original] = english
    return out


TIERS = ("shown on the roadmap or a card", "more the walk weighed",
         "more teachable", "overlay-only")
# How many of those the roadmap is made of. The rest is the corpus.
ROADMAP_TIERS = 2


def tier(text: str, teachable: bool, shown: set[str],
         candidates: set[str]) -> int:
    """Which of the four tiers a sentence is asked in -- see `ordered`."""
    if text in shown:
        return 0
    if text in candidates:
        return 1
    return 2 if teachable else 3


def ordered(pending: list[tuple[str, bool]], shown: set[str],
            candidates: set[str]) -> list[str]:
    """The sentences still to ask, most useful first.

    Four tiers, each in corpus order within itself: what a card shows, what
    the walk weighed, the rest of the teachable corpus, and the overlay-only
    rows. A stable sort on the tier alone keeps the corpus order within
    each.
    """
    return [text for text, _ in sorted(
        pending, key=lambda item: tier(*item, shown, candidates))]


def best_videos_first(app, todo: list[str], count: int) -> tuple[list[str], int]:
    """`todo` with the lines of the reel's best `count` videos in front, best
    video first, the rest in the order they came; and how many moved.

    The tiers above serve the reader of cards. The reel's reader watches a
    transcript, and a line with no English under it is a gap they meet at
    the top of the feed first — so the feed's order, as last scored, is the
    order to fill it in.
    """
    from db import Database                                  # noqa: PLC0415
    from scores import ScoreStore                            # noqa: PLC0415
    from watchability import ENOUGH_LINES                    # noqa: PLC0415
    banned = app.banned_videos()
    ranked = [row["video"] for row in ScoreStore(app.settings.state_path).latest()
              if row["lines"] >= ENOUGH_LINES and row["video"] not in banned][:count]
    place = {video: n for n, video in enumerate(ranked)}
    first: dict[str, int] = {}
    if ranked:
        with Database(app.settings.own) as db:
            for video, text in db.rows(
                    "SELECT video_id, text FROM corpus_sentence"
                    " WHERE video_id = ANY(%s)", (ranked,)):
                first[text] = min(first.get(text, len(ranked)), place[video])
    todo = sorted(todo, key=lambda text: first.get(text, len(ranked)))
    return todo, sum(1 for text in todo if text in first)


class TranslateSentencesCommand:
    def run(self, app, limit: int | None = None, batch: int = BATCH,
            workers: int | None = None, log: Path = Path("out/translate.log"),
            everything: bool = False, videos: int | None = None) -> None:
        import os                                            # noqa: PLC0415
        from concurrent.futures import (ThreadPoolExecutor,   # noqa: PLC0415
                                        as_completed)

        import requests                                      # noqa: PLC0415

        from deck.gloss import GlossStore                    # noqa: PLC0415
        from generation.client import LLMClient              # noqa: PLC0415
        from state import open_state                         # noqa: PLC0415

        settings = app.settings
        # Two minutes, not ten. A batch answers in a couple of seconds, so
        # a request still open after a minute is a connection the tunnel
        # dropped, not a slow answer -- and the ten-minute wait was paid in
        # full, per hang, before anything was retried.
        client = LLMClient(timeout=120)
        if not client.available:
            raise SystemExit(
                "no local model configured — set LLM_BASE_URL and LLM_MODEL "
                "in .env, then check it with `python main.py check-model`")
        model = os.environ.get("LLM_MODEL", "")
        # As many in flight as the server has slots: one request per slot is
        # the whole of the concurrency there is, and one more only queues.
        if workers is None:
            workers = client.slots() or WORKERS

        wanted = app.corpus_store.untranslated()
        glosses = GlossStore(settings.state_path)
        have = glosses.sentences(model)
        pending = [(text, teachable) for text, teachable in wanted
                   if text not in have]
        with open_state(settings.state_path) as conn:
            # What a reader sees: the sentence each roadmap step teaches
            # with, and the three a card shows. Not the same set -- a third
            # of the step sentences sit past the third example, or outside
            # the examples altogether.
            shown = {t for (t,) in conn.execute(
                "SELECT sentence FROM roadmap"
                " UNION SELECT text FROM roadmap_example WHERE n < 3")}
            candidates = {t for (t,) in conn.execute(
                "SELECT DISTINCT text FROM roadmap_example")}
        tiers = Counter(tier(text, teachable, shown, candidates)
                        for text, teachable in pending)
        last = len(TIERS) if everything else ROADMAP_TIERS
        todo = ordered([(text, teachable) for text, teachable in pending
                        if tier(text, teachable, shown, candidates) < last],
                       shown, candidates)
        print(f"{len(wanted):,} sentences without English in the corpus · "
              f"{len(wanted) - len(pending):,} already have it from {model} · "
              f"{len(todo):,} to ask", flush=True)
        print("  in order: " + " · ".join(
            f"{tiers[n]:,} {TIERS[n]}" for n in range(last)), flush=True)
        if not everything:
            print("  left for --all: " + " · ".join(
                f"{tiers[n]:,} {TIERS[n]}" for n in range(last, len(TIERS))),
                flush=True)
        if videos:
            todo, moved = best_videos_first(app, todo, videos)
            print(f"  the reel's best {videos:,} videos first: {moved:,} of their lines",
                  flush=True)
        if limit:
            todo = todo[:limit]
            print(f"  asking about the first {len(todo):,}", flush=True)
        if not todo:
            print("nothing to do")
            return
        print(f"  {client.describe()} · {workers} in flight", flush=True)

        long = [t for t in todo if len(t.split()) > TOO_LONG]
        if long:
            todo = [t for t in todo if len(t.split()) <= TOO_LONG]
            print(f"  {len(long):,} lines over {TOO_LONG} words are not sent", flush=True)
        blocks = blocks_of(todo, batch)
        trouble = {"said": False, "streak": 0}

        def ask(block: list[str]) -> tuple[dict[str, str], int]:
            """One batch: what came back, and how many sentences it lost."""
            if trouble["streak"] >= GIVE_UP:
                return {}, len(block)
            numbered = "\n".join(f"{n}. {text}"
                                 for n, text in enumerate(block, start=1))
            wait = 5.0
            for attempt in range(3):
                try:
                    reply = client.complete(SYSTEM, numbered, temperature=0.1)
                    got = parse(reply, block)
                except requests.HTTPError as error:
                    # Only a saturated server is worth waiting on. Anything
                    # else -- a 401, a 404 -- will say the same thing again.
                    status = getattr(error.response, "status_code", None)
                    if status not in _OVERLOADED or attempt == 2:
                        return self._failed(trouble, error, block)
                    time.sleep(wait)
                    wait *= 3
                except (requests.RequestException, ValueError, KeyError,
                        TypeError) as error:
                    if attempt == 2:
                        return self._failed(trouble, error, block)
                    time.sleep(wait)
                    wait *= 3
                else:
                    if not got:
                        # Well-formed and empty is still the endpoint
                        # saying nothing, and counts towards giving up.
                        return self._failed(
                            trouble, ValueError("no entries in the reply"),
                            block)
                    trouble["streak"] = 0
                    return got, len(block) - len(got)
            return {}, len(block)

        log.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        done = failed = declined = 0
        with ThreadPoolExecutor(max_workers=workers) as pool, \
                open(log, "a", encoding="utf-8") as handle:
            handle.write(f"\n--- {datetime.now().isoformat(timespec='seconds')}"
                         f" · {model} · {len(todo):,} to ask ---\n")
            # Stored as each batch lands, in whatever order that is. `map`
            # hands results back in the order they were sent, so one request
            # hung on the tunnel held every finished batch behind it in
            # memory until it timed out -- thirteen minutes of nothing
            # stored, from a server answering in under a second. The rows
            # are keyed by sentence, so order was never needed.
            for future in as_completed([pool.submit(ask, b) for b in blocks]):
                got, lost = future.result()
                if got:
                    glosses.save_translations(got, model)
                    for text, english in got.items():
                        handle.write(f"{text}\n    {english or '(nothing)'}\n")
                    handle.flush()
                before = done + failed
                done += len(got)
                declined += sum(1 for english in got.values() if not english)
                failed += lost
                if (done + failed) // REPORT > before // REPORT:
                    spent = time.perf_counter() - started
                    print(f"  … {done:,} of {len(todo):,} answered · "
                          f"{failed:,} failed · {done / spent:.2f}/s · "
                          f"{spent / 3600:.1f} h elapsed", flush=True)

        spent = time.perf_counter() - started
        print(f"\n{done - declined:,} sentences translated in "
              f"{spent / 60:.1f} min")
        if declined:
            print(f"  {declined:,} more came back as not German, or not "
                  "translatable, and are stored as such")
        if failed:
            print(f"  {failed:,} failed and are still owed — run it again; "
                  "nothing already stored is asked twice")
        print(f"  {log}   — every sentence and its English, as they landed")
        if trouble["streak"] >= GIVE_UP:
            raise SystemExit(
                f"gave up after {GIVE_UP} batches in a row failed — the "
                "endpoint looks unreachable; nothing already stored is lost")

    @staticmethod
    def _failed(trouble: dict, error: Exception,
                block: list[str]) -> tuple[dict[str, str], int]:
        """Record one lost batch, and say why the first time only.

        "10,606 failed" says nothing a person can act on; "Failed to resolve"
        says everything, and once is enough.
        """
        trouble["streak"] += 1
        if not trouble["said"]:
            trouble["said"] = True
            print(f"  ! {type(error).__name__}: {error}"[:200], flush=True)
        return {}, len(block)
