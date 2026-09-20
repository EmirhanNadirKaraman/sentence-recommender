"""`polish-sentences` — repair a sentence and say whether it is standard German.

Two questions in one call, because both are answered by reading the same
sentence and a round trip costs far more than a few extra tokens.

  *the repair.* Subtitle German loses full stops, opens lowercase where the
  line was cut, and carries the odd mishearing. The fix is stored beside the
  original and never over it: everything in this project is keyed by sentence
  text, so a rewrite in place would orphan the verdicts, the glosses, the
  vectors and the roadmap at once.

  *the dialect.* `Schaun mer mol, dann seng ma scho` is German, and not the
  German anyone is learning. Four cheap tests for this were tried and thrown
  away -- a lexicon that called `zum` foreign, a tagger that called
  `Dreieckshandel` an organisation, and word rarity, which flagged `nettesten`
  and `achtzehn` while missing `Ech find'` and `was is` entirely. It is a
  linguistic judgement and it needs a model.

The repair is checked before it is believed, on the rails `llm_corrector`
already had to learn: a reply that keeps too little of the original has
paraphrased rather than repaired, and one that grew has started explaining
itself. Both were seen in practice.
"""
from __future__ import annotations

import json
import re
import time
from difflib import SequenceMatcher

from corpus.fixes import FixStore, real_damage

WORD = re.compile(r"\w+", re.UNICODE)

# The same rails `corpus.llm_corrector` arrived at, for the same reasons.
MIN_RETENTION = 0.7
MAX_GROWTH = 1.5

# Dialect is demoted, not deleted -- like every other verdict here. Milder
# than a fragment (0.4), because a dialect sentence is still a real sentence
# and for a word the corpus only says in dialect it is better than nothing.
DIALECT = 0.5
SOURCE = "dialect"

# A repair that changes what the analyser finds cannot simply be shown. The
# i+1 promise on a card is computed from the units of the sentence as the
# corpus holds it, so displaying different text would describe a sentence the
# reader is not reading -- and these repairs do change it. Splitting `Ich
# lerne seit einem Jahr Chinesisch Seit einem Jahr?` into two sentences makes
# `das Jahr` appear as a unit that the walk never counted, so a card claiming
# one new word would show two.
#
# It cuts the other way as well, and that is the useful half: if repairing a
# run-on changes how it parses, then the corpus's analysis of the *original*
# was already unreliable, and the sentence is a poor thing to teach from
# whichever text is shown. So the repair is dropped and the original is marked
# instead.
MISREAD = 0.5
MISREAD_SOURCE = "misparsed"

BATCH = 20
REPORT = 2_000
# Consecutive failed batches before the run stops asking. One bad reply is
# ordinary; twenty in a row is the endpoint being gone, and carrying on only
# marks every remaining sentence as owed while learning nothing.
GIVE_UP = 20

SYSTEM = (
    "You clean up German subtitle lines for a learner.\n"
    "You are given numbered German sentences. For each one reply with:\n"
    '  "fixed"    — the same sentence with punctuation, capitalisation, '
    "spelling and obvious transcription errors corrected. Change NOTHING "
    "else. Keep every word, its order, and the wording. If it is already "
    "correct, repeat it back unchanged. Never translate, never rephrase, "
    "never shorten, never explain.\n"
    '  "standard" — true if it is ordinary standard German, false if it is '
    "dialect or heavy regional speech (Bairisch, Schwiizerdütsch, Kölsch and "
    "the like), for example 'Schaun mer mol' or 'deswegen habn ma'. Casual "
    "speech and contractions like 'hab' ich' are still standard: false is "
    "for the German a learner should not be taught from.\n"
    "Reply with JSON only, one entry per sentence, in the order given."
)

RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "polish",
        "schema": {
            "type": "object",
            "properties": {
                "sentences": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "n": {"type": "integer"},
                            "fixed": {"type": "string"},
                            "standard": {"type": "boolean"},
                        },
                        "required": ["n", "fixed", "standard"],
                    },
                },
            },
            "required": ["sentences"],
        },
    },
}

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def believable(original: str, fixed: str) -> bool:
    """Is this a repair, or has the model answered a different question?"""
    if not fixed.strip():
        return False
    was, now = WORD.findall(original.lower()), WORD.findall(fixed.lower())
    if not was:
        return False
    if len(now) > len(was) * MAX_GROWTH:
        return False
    kept = SequenceMatcher(None, was, now).ratio()
    return kept >= MIN_RETENTION


class PolishSentencesCommand:
    def run(self, app, label: str | None = None, limit: int | None = None,
            batch: int = BATCH, workers: int = 4,
            everything: bool = False) -> None:
        import sqlite3                                      # noqa: PLC0415
        from concurrent.futures import ThreadPoolExecutor    # noqa: PLC0415

        from commands.export_deck import DEFAULT_LABEL      # noqa: PLC0415
        from generation.client import LLMClient             # noqa: PLC0415

        label = label or DEFAULT_LABEL
        settings = app.settings
        # Shown examples by default, not every candidate the walk weighed.
        # Measured on the first 1,460 answers, only 14.4% of sentences are
        # changed at all, and asking about all 61,978 costs about 21 hours to
        # repair punctuation on sentences nobody will ever be shown. The
        # 11,395 that reach a card are 18% of that work and all of the
        # benefit. `--all` asks about the rest, for when the plan is settled.
        #
        # A damage filter was measured first and rejected: the only signal
        # with any reach -- a lowercase word followed by a capitalised one --
        # covers 52% of the work to catch 65% of the repairs, and every other
        # cheap test (mojibake, missing terminal mark, lowercase opening)
        # matched nothing at all, because `filter.py` and `quality` already
        # settle those upstream.
        shown = "" if everything else " AND n < 3"
        with sqlite3.connect(settings.state_path) as conn:
            wanted = [row[0] for row in conn.execute(
                "SELECT DISTINCT text FROM roadmap_example"
                f" WHERE source = ?{shown}", (label,))]
        if not wanted:
            raise SystemExit(f"no stored examples for '{label}'")

        store = FixStore(settings.state_path)
        done = store.have()
        todo = [text for text in wanted if text not in done]
        if limit:
            todo = todo[:limit]
        print(f"{len(wanted):,} candidate sentences · {len(done):,} already "
              f"asked · {len(todo):,} to do", flush=True)
        if not todo:
            print("nothing to do")
            return

        client = LLMClient(timeout=600)
        if not client.available:
            raise SystemExit("no local model configured — set LLM_BASE_URL")
        print(client.describe(), flush=True)

        blocks = [todo[at:at + batch] for at in range(0, len(todo), batch)]

        # Why a batch failed, and how many have failed in a row. A run over
        # thousands of sentences should survive one bad reply, and should not
        # spend thirty seconds cheerfully recording ten thousand failures
        # because the endpoint went away -- which is exactly what happened
        # when a tunnel expired mid-run. The first reason is printed rather
        # than swallowed, because "10,606 failed" says nothing a person can
        # act on and "Failed to resolve" says everything.
        trouble = {"said": False, "streak": 0}

        def ask(block):
            if trouble["streak"] >= GIVE_UP:
                return {}, {}, len(block)
            numbered = "\n".join(f"{n}. {text}"
                                 for n, text in enumerate(block, start=1))
            try:
                reply = client.complete(SYSTEM, numbered, temperature=0.1,
                                        response_format=RESPONSE_FORMAT)
                rows = json.loads(_FENCE.sub("", reply.strip()))["sentences"]
            except Exception as error:                      # noqa: BLE001
                trouble["streak"] += 1
                if not trouble["said"]:
                    trouble["said"] = True
                    print(f"  ! {type(error).__name__}: {error}"[:200],
                          flush=True)
                return {}, {}, len(block)
            trouble["streak"] = 0
            fixes, dialect = {}, {}
            for row in rows:
                index = int(row.get("n", 0)) - 1
                if not 0 <= index < len(block):
                    continue
                original = block[index]
                fixed = str(row.get("fixed", "")).strip()
                # An unbelievable repair is dropped, but the sentence still
                # counts as asked -- stored as itself -- so a rerun does not
                # spend the same call again to be told the same thing.
                fixes[original] = fixed if believable(original, fixed) \
                    else original
                if row.get("standard") is False:
                    dialect[original] = DIALECT
            return fixes, dialect, 0

        start = time.perf_counter()
        fixes: dict[str, str] = {}
        dialect: dict[str, float] = {}
        failed = asked = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for got, said, bad in pool.map(ask, blocks):
                fixes.update(got)
                dialect.update(said)
                failed += bad
                asked += len(got) + bad
                if got:
                    store.add_many(got, client.model)
                if asked % REPORT < batch * workers and asked:
                    rate = asked / max(time.perf_counter() - start, 1e-9)
                    print(f"  … {asked:,} of {len(todo):,} · {rate:.0f}/s · "
                          f"{(len(todo) - asked) / rate / 60:.0f} min left",
                          flush=True)

        # Which repairs are safe to show: the ones the analyser reads the
        # same way before and after. Done once at the end rather than per
        # batch, because the analyser is far happier with thousands of
        # sentences than with six.
        changed = {text: fixed for text, fixed in fixes.items()
                   if fixed != text and real_damage(text, fixed)}
        misread: dict[str, float] = {}
        if changed:
            from corpus.sentence import Sentence            # noqa: PLC0415

            pairs = sorted(changed.items())
            read = app.analyzer.analyze_all(
                [Sentence(text=t) for pair in pairs for t in pair])
            units = {s.text: s.units for s in read}
            for original, fixed in pairs:
                if units.get(original) != units.get(fixed):
                    # Not shown, and the original is demoted: its parse moved
                    # when the damage was repaired, so neither text can be
                    # trusted to teach what the walk thinks it teaches.
                    store.add_many({original: original}, client.model)
                    misread[original] = MISREAD
            print(f"\n  {len(changed):,} repairs fix real damage · "
                  f"{len(changed) - len(misread):,} keep the same units and "
                  f"will be shown")
            print(f"  {len(misread):,} change what the sentence teaches — "
                  "dropped, and the original marked instead")

        # Its own source, so rerunning this never disturbs what the parser
        # found and a reader still outranks both. And only what this run
        # read: the pass resumes over what has not been asked, so every run
        # is partial, and replacing the whole source each time left the
        # marks of the last batch alone -- 174 of them, from thousands
        # polished. See `mark_many`.
        if dialect:
            app.overrides.mark_many(dialect, SOURCE, judged=todo)
        if misread:
            app.overrides.mark_many(misread, MISREAD_SOURCE, judged=todo)

        spent = time.perf_counter() - start
        changed = sum(1 for text, fixed in fixes.items() if fixed != text)
        print(f"\nasked about {len(fixes):,} sentences in {spent / 60:.1f} min")
        print(f"  {changed:,} were repaired")
        print(f"  {len(dialect):,} are dialect, marked at {DIALECT}")
        if failed:
            print(f"  {failed:,} failed and are still owed — run it again")
        if trouble["streak"] >= GIVE_UP:
            raise SystemExit(
                f"gave up after {GIVE_UP} batches in a row failed — the "
                "endpoint looks unreachable; nothing already stored is lost")
