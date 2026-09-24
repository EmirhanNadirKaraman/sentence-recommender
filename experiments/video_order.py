"""How long does it take to watch your way through the study list?

A roadmap orders words; this orders *videos*. Watch them in some order and
each one is worth more than it would have been, because the ones before it
taught you the words it needed. The question is how few hours that can take.

Three things are varied.

  * **K** — how many times a word must be met before it counts as learned.
    K=1 is what `VideoWalk` assumes today; `cover.py` asks for 5 in the set
    version, and the SRS asks for 5 passes, so 1 is the optimistic end.
  * **gate** — whether an encounter has to be an i+1 sentence (the word the
    only unknown in it) or merely an occurrence of the word.
  * **rewatch** — whether a video may be watched again once its other words
    have landed elsewhere and it has fresh i+1 sentences to give.

The lower bound drops the ordering. In any schedule, the moment a video
teaches a word every other unit in that sentence is already known, and
everything known lies inside the reachable closure (`roadmap.reach` proves
that closure is order-independent). So "v can teach w" implies "v holds a
sentence with w whose other units are all reachable", and min-cost cover
under that relaxed rule is no dearer than the true optimum.

Exact optimum is out of reach: the problem contains weighted set cover, and
the i+1 gate makes coverage *super*modular — a video can be worth more after
you have seen another — so greedy's usual ln(n) guarantee does not hold
either. Bounding it is the honest alternative.
"""
from __future__ import annotations

import csv
import itertools
import statistics
import time
from pathlib import Path

from html import escape

from corpus.quality import well_formed
from corpus.transcripts import TranscriptSource, language
from db import Database
from roadmap.effort import BOTTLENECK, CHAIN, effort
from roadmap.reach import reachable
from watchability import ENOUGH_LINES

OUT = Path("experiment_results")
SUMMARY = "07-video-order.csv"

# When a sentence teaches, given how many of its units are unknown and how
# many words it runs to.
#
# `i+1` is the rule the app is built on: exactly one unknown, and the rest of
# the line carries it. The looser ones ask what is given up by relaxing that,
# and they teach *every* unknown in a qualifying sentence -- which is the
# claim being tested, not a convenience. Two new words in one line is two
# words learned or it is nothing.
#
# The density gates are the interesting ones, and they are the question as it
# was put: two unknowns in a four-word line is not the same as one in a
# ten-word line. They are a plain ratio -- unknowns over the sentence's word
# count -- so `15%` admits a line where at most one word in seven is new,
# which is one unknown by nine words and three by twenty.
#
# The `unknown == 1` arm is not decoration. Without it a six-word line with a
# single unknown would fail 10%, which makes the gate *stricter* than i+1 on
# short sentences and the comparison meaningless -- hours could move in
# either direction for two unrelated reasons. With it every gate here is a
# superset of i+1, so a looser gate can only take less time and reach more
# words, and any row that does not is telling you something real.
#
# `corpus.quality.well_formed` keeps sentences between five and twenty-five
# words, so the ratios cap themselves at the top end: two unknowns at 10%,
# three at 15%, five at 20%, with no arbitrary ceiling bolted on.
#
# `any` is the other end: every occurrence counts, however dense the line.
# It is not a proposal, it is the bound that says what the gate is buying.
# How an encounter is weighed when a video is being chosen. `FREQUENCY` is
# the default because the schedule is lived through rather than totted up at
# the end -- see `walk`.
FREQUENCY = "frequency"
FLAT = "flat"

GATES: dict = {
    "i+1": lambda unknown, words: unknown == 1,
    "i+2": lambda unknown, words: unknown <= 2,
    "i+3": lambda unknown, words: unknown <= 3,
    "10%": lambda unknown, words: unknown == 1 or unknown <= 0.10 * words,
    "15%": lambda unknown, words: unknown == 1 or unknown <= 0.15 * words,
    "20%": lambda unknown, words: unknown == 1 or unknown <= 0.20 * words,
    "any": lambda unknown, words: True,
}
TRANSCRIPTS = Path("Easy German Transcripts")


def speaking_rate(app, minutes) -> float:
    """Spoken German words a minute, measured rather than assumed.

    The transcripts carry no timing — they are prose, not subtitles — so an
    episode's length has to be estimated from its word count. The rate comes
    from the videos that *do* have both, median over them, and short or thin
    videos are left out because a ratio over a minute of speech is noise.
    """
    words: dict = {}
    for s in app.corpus_store.load("subtitle", teachable_only=False):
        if s.timing:
            words[s.timing.video_id] = (words.get(s.timing.video_id, 0)
                                        + len(s.text.split()))
    rates = [words[v] / minutes[v] for v in words
             if v in minutes and minutes[v] >= 2 and words[v] >= 200]
    return statistics.median(rates)


def german_only(lines: list[str]) -> list[str]:
    """The German half of a transcript file, where it carries a translation.

    `TranscriptSource._alternates` asks the same question for the corpus, off
    the first forty lines and a strict German-then-English run. In these files
    that under-fires badly -- a street interview is mostly short answers, and
    `Manchmal.` / `Sometimes.` carry no function word at all, so both score
    `?` and the run breaks. It finds 534 of 1,399 files bilingual; the rest
    are read as if every line were German.

    That costs the corpus nothing, because `filter.py` throws the English out
    at ingest. It costs the *pricing* a great deal: an episode is priced by
    its word count over a rate measured on German subtitles, so counting the
    translation inflates every bilingual episode.

    Over a whole file the vote is unambiguous where a forty-line window is
    not, and pricing needs only the halves, never the pairing -- so this asks
    the cheaper question and leaves `_alternates` alone.
    """
    votes = [0, 0]
    for n, line in enumerate(lines):
        tag = language(line)
        if tag == "de":
            votes[n % 2] += 1
        elif tag == "en":
            votes[n % 2] -= 1
    if votes[0] > 0 > votes[1]:
        return lines[0::2]
    if votes[1] > 0 > votes[0]:
        return lines[1::2]
    return lines                      # one language, or too short to tell


def is_seg(path: Path) -> bool:
    """Whether a transcript is a Super Easy German episode.

    By the filename and not the folder. `Super Easy German/` holds 458
    files, and one of them -- `EG 210` -- is an ordinary Easy German episode
    filed in the wrong place, so the folder would take it too. The number
    prefix is the reliable mark: 457 files begin `SEG`, two of them in lower
    case, and no file outside that folder has `seg` in its name at all.
    """
    return path.name.lower().startswith("seg")


def episodes(sentences, rate: float, floor: int = ENOUGH_LINES,
             drop_seg: bool = False) -> tuple[dict, dict]:
    """Easy German episodes as things to watch, and what each costs.

    The corpus does not record which file a transcript sentence came from —
    every row's origin is just `transcript` — so the files are parsed again
    and joined on the text. A line said in several episodes is credited to
    each: the corpus keeps one copy after de-duplication, but it really is
    spoken in all of them.

    Watched on YouTube rather than in the app, so the cost is the episode's
    running time, estimated from its words. That estimate is the softest
    number here: the interquartile spread of the rate is about +/-15%, so
    totals are worth more than any single episode's length.

    `floor` is separate from a video's because an episode is not a clip. The
    floor counts lines that survived `filter.py` and `well_formed`, and a
    street interview loses most of its own to the format -- English
    translation lines, one-word answers, two voices to a line. At 40 that
    drops 886 of 1,399 files, and the ones it drops are whole episodes
    somebody would sit down and watch. The video floor is about whether the
    thing is worth opening; this one is only about whether enough of it
    survived transcription to plan with.
    """
    if not TRANSCRIPTS.exists():
        return {}, {}
    by_text = {s.text: s for s in sentences
               if not s.timing and s.origin == "transcript"}
    grouped: dict = {}
    cost: dict = {}
    for path in TranscriptSource(TRANSCRIPTS).files():
        if drop_seg and is_seg(path):
            continue
        read = TranscriptSource.read(path)
        here = [by_text[s.text] for s in read if s.text in by_text]
        if len(here) < floor:
            continue
        key = ("e", str(path))
        grouped[key] = here
        raw = path.read_text(encoding="utf-8", errors="replace")
        lines = [line.strip() for line
                 in raw.replace("\r", "\n").split("\n") if line.strip()]
        cost[key] = sum(len(line.split())
                        for line in german_only(lines)) / rate
    return grouped, cost


def shelf(app, seed, with_episodes: bool = True,
          episode_floor: int = ENOUGH_LINES, drop_machine: bool = False,
          drop_seg: bool = False):
    """Everything worth planning over, and what each holds and costs.

    Keys are `("v", video_id)` or `("e", transcript path)`, so the two kinds
    sit in one list and the walk need not know the difference.
    """
    sentences = [s for s in app.corpus(strict=True) if well_formed(s.text)]
    goals = frozenset(app.goal_units)
    minutes = app.video_minutes
    # Reachability over the *whole* corpus, always, even when the walk is
    # about to be denied half of it. `target` is the question being asked --
    # which of my words can this corpus teach me -- and an arm that shrinks
    # the question it is answering cannot be compared with one that does not.
    # Dropping machine-made channels from `reach` would do exactly that: the
    # hours would fall because there was less to learn, and the row would
    # read as the drop being cheap. So the goal set is fixed here and the
    # material is thinned below, which shows up honestly as words unmet.
    reach = reachable(sentences, seed, goals, budget=0, compounds=app.compounds)
    target = frozenset(goals & reach) - frozenset(seed.units)

    if drop_machine:
        synthetic = app.machine_made()
        sentences = [s for s in sentences if s.text not in synthetic]

    grouped: dict = {}
    for s in sentences:
        if s.timing:
            grouped.setdefault(("v", s.timing.video_id), []).append(s)
    grouped = {k: ss for k, ss in grouped.items()
               if len(ss) >= ENOUGH_LINES and k[1] in minutes}
    cost = {k: minutes[k[1]] for k in grouped}
    if with_episodes:
        more, more_cost = episodes(sentences, speaking_rate(app, minutes),
                                   floor=episode_floor, drop_seg=drop_seg)
        grouped.update(more)
        cost.update(more_cost)

    says: dict = {}
    for k, ss in grouped.items():
        for s in ss:
            for u in s.units:
                says.setdefault(u, set()).add(k)
    return sentences, grouped, cost, says, reach, target


def frequency(grouped, target) -> dict:
    """unit -> how many sentences on the shelf say it, at all.

    Every occurrence, not only the teachable ones: this is how common the
    word is in the German you are going to hear, which is the thing worth
    front-loading. `chances` counts the narrower set.
    """
    counted: dict = {w: 0 for w in target}
    for lines in grouped.values():
        for line in lines:
            for unit in line.units & target:
                counted[unit] += 1
    return counted


def chances(grouped, target, reach, gate: str) -> dict:
    """unit -> the distinct sentences that could ever teach it.

    A sentence can teach `w` if, at the best moment it could ever be read,
    the gate accepts it. That best moment is when everything reachable is
    already known, so the unknowns left are `w` itself plus whatever the
    corpus can never teach -- which is what `reach` names. Under `i+1` that
    reduces to the old test, everything but `w` reachable; under a density
    gate it lets a longer line carry a blocker or two and still count.

    Distinct *texts*, because a corpus holds repeats and five copies of one
    line is not five encounters.
    """
    allow = GATES[gate]
    out: dict = {}
    for ss in grouped.values():
        for s in ss:
            blocked = s.units - reach
            words = len(s.text.split())
            for w in s.units & target:
                if allow(len(blocked - {w}) + 1, words):
                    out.setdefault(w, set()).add(s.text)
    return out


def walk(grouped, cost, says, target, supply, seed, k: int, gate: str,
         rewatch: bool, order: list | None = None,
         weight: str = FREQUENCY) -> dict:
    """Greedy: the video giving the most unmet encounters per minute.

    A word stays unknown until its Kth encounter, so under the i+1 gate it
    goes on blocking the sentences it appears in until then. That is what
    makes K>1 harder than K times the work, and what gives rewatching
    something to do.

    `order` steps through a saved plan instead of choosing one. Everything
    else is the same machine, so the walk does not gain a second copy of
    itself that can drift -- and since choosing is where the time goes
    (every video re-scored whenever a word lands), a replay is seconds where
    the walk is minutes. That is how a finished experiment gets its per-word
    costs without being run again.
    """
    need = {w: min(k, len(supply.get(w, ()))) or 1 for w in target}
    have = set(seed.units)
    seen: dict = {w: set() for w in target}
    # What each word cost. A viewing's minutes are split across the words it
    # gave encounters to, in proportion to how many it gave each, so the
    # charges add up to the hours the plan really takes and a film watched
    # for one word carries the whole of its own length.
    #
    # Shares, not leave-one-out: dropping a word from the list may save less
    # than its charge, because the video might have been worth watching
    # anyway, and may save more, because it was holding others back. It is
    # the cheap attribution, and it is right at the extremes, which is where
    # the question is asked.
    charge: dict = {w: 0.0 for w in target}
    alone: dict = {w: 0.0 for w in target}
    done_at: dict = {}
    worst: dict = {}
    allow = GATES[gate]
    # What an encounter is worth when choosing -- the word's frequency in the
    # corpus by default, so a video teaching common words beats one teaching
    # rare ones at the same rate.
    #
    # This used to be a flat one, and the change is worth its four hours.
    # Measured over the same shelf at K=5: after ten hours you can read 4.8%
    # of the occurrences in this corpus rather than 2.4%, half of it arrives
    # at 60.3 hours rather than 65.7, and the whole thing costs 598.5 hours
    # against 594.3 -- seven tenths of a percent more watching for twice the
    # reading early on, which is the part anyone actually lives through.
    #
    # `FLAT` is kept because the comparison has to stay runnable; it is not
    # a fallback. The *count* of encounters is still what a plan row reports,
    # because a row saying "169 encounters" should mean encounters.
    if weight == FLAT:
        worth = lambda unit: 1.0                              # noqa: E731
    else:
        common = frequency(grouped, target)
        worth = lambda unit: float(common[unit])              # noqa: E731

    def useful(video):
        texts: dict = {}
        for s in grouped[video]:
            missing = s.units - have
            # Everything the gate lets through is learned, not just the
            # first: a rule that admits two unknowns and then teaches one of
            # them is not the rule being tested, it is i+1 with extra steps.
            hit = (missing if missing
                   and allow(len(missing), len(s.text.split())) else set())
            for w in hit:
                if w in target and len(seen[w]) < need[w] and s.text not in seen[w]:
                    texts.setdefault(w, set()).add(s.text)
        return (sum(worth(w) * len(t) for w, t in texts.items()),
                sum(len(t) for t in texts.values()), texts)

    queue = list(order) if order is not None else None
    score = {} if queue is not None else {v: useful(v) for v in grouped}
    pool, spent, views, uniq = set(grouped), 0.0, 0, set()
    picks: list = []
    while pool:
        if queue is not None:
            if not queue:
                break
            best = queue.pop(0)
            score[best] = useful(best)
        else:
            best = max(pool, key=lambda v: (score[v][0] / (cost.get(v) or 1e9),
                                            score[v][0], str(v)))
        rate, gain, texts = score[best]
        if not gain:
            break
        minutes = cost.get(best, 0.0)
        finished = []
        for w, ts in texts.items():
            seen[w] |= ts
            charge[w] += minutes * len(ts) / gain
            if len(texts) == 1:
                alone[w] += minutes
            if minutes > worst.get(w, (0.0, None))[0]:
                worst[w] = (minutes, best)
            if len(seen[w]) >= need[w]:
                have.add(w)
                finished.append(w)
                done_at[w] = (spent + minutes) / 60
        spent += minutes
        views += 1
        uniq.add(best)
        picks.append({"item": best, "minutes": minutes,
                      "encounters": gain, "completed": len(finished),
                      "again": best not in uniq or views > len(uniq),
                      "words": sorted(w.key for w in finished)})
        if not rewatch:
            pool.discard(best)
        if queue is None:
            touched = {best} | {x for w in texts for x in says.get(w, set())}
            for v in touched & pool:
                score[v] = useful(v)
    met = sum(1 for w in target if len(seen[w]) >= need[w])
    return {"hours": spent / 60, "viewings": views, "videos": len(uniq),
            "met": met, "picks": picks, "charge": charge, "alone": alone,
            "done_at": done_at, "worst": worst, "need": need,
            "got": {w: len(t) for w, t in seen.items()},
            "mean_encounters":
                statistics.mean([min(len(seen[w]), k) for w in target])}


def slug(gate: str) -> str:
    """A gate's name, as a filename will take it: `i+2` -> `i2`, `15%` -> `15pct`."""
    return gate.replace("+", "").replace("%", "pct").replace("-", "")


def opens(grouped, goals, target, reach, seed, gate: str) -> set:
    """Goals this gate could teach that are out of reach under i+1.

    `target` is the i+1 closure and every arm is walked against it, so that
    the arms answer one question. That fixes the comparison and hides a real
    part of what a looser gate buys: words with no i+1 sentence anywhere,
    which a line carrying two unknowns could still teach. Counted here rather
    than folded in, because a word this finds is *reachable*, not scheduled --
    saying how long it would take needs the whole closure reopened under the
    new rule, which is a bigger question than the one being asked.
    """
    allow = GATES[gate]
    # `goals - target` is not "the words i+1 cannot reach": it also holds
    # every goal already known, which is why the first run of this reported
    # i+1 opening 369 words it had by definition not opened. What is left
    # after the known ones is the question -- and the answer turns out to be
    # small, which is worth knowing precisely because the hours are not.
    want = frozenset(goals) - target - frozenset(seed.units)
    out = set()
    for ss in grouped.values():
        for s in ss:
            blocked = s.units - reach
            words = len(s.text.split())
            for w in s.units & want:
                if allow(len(blocked - {w}) + 1, words):
                    out.add(w)
    return out


def depth(app, seed, k: int = 1, say=print) -> list[dict]:
    """What relaxing i+1 is worth, and what it costs.

    One shelf, one goal set, one K, six gates. Every gate here admits
    everything i+1 admits (see `GATES`), so the hours can only fall and the
    words met can only rise -- which makes the size of the fall the answer
    and any row that moves the other way a bug worth chasing.
    """
    t = time.perf_counter()
    _, grouped, cost, says, reach, target = shelf(app, seed, with_episodes=True)
    goals = frozenset(app.goal_units)
    eps = sum(1 for key in grouped if key[0] == "e")
    say(f"  shelf: {len(grouped) - eps:,} videos + {eps:,} episodes · "
        f"{len(target):,} words · K={k} ({time.perf_counter() - t:.0f}s)")
    with Database(app.settings.own) as database:
        titles = dict(database.rows("SELECT video_id, title FROM video"))

    # How much of the corpus each gate admits at all, before any walking:
    # the share of well-formed lines whose unknown count and length it
    # accepts against what is known right now.
    lines = [(len(s.units - set(seed.units)), len(s.text.split()))
             for ss in grouped.values() for s in ss]
    teaching = [(u, w) for u, w in lines if u]

    rows = []
    for gate in GATES:
        t = time.perf_counter()
        allow = GATES[gate]
        admits = sum(1 for u, w in teaching if allow(u, w))
        supply = chances(grouped, target, reach, gate)
        extra = opens(grouped, goals, target, reach, seed, gate)
        r = walk(grouped, cost, says, target, supply, seed, k, gate,
                 rewatch=True)
        # Named by the gate alone, with no marker saying which run wrote
        # them, so the Plan page reads a new gate as a new setting of the
        # knob it already has. `i+1` and `any` are left to `sweep`, which
        # writes the same two walks under the same two names -- a second
        # copy would be a race while both run and a lie afterwards, since
        # only one of them could be the one being read.
        if gate not in ("i+1", "any"):
            name = f"07-plan-{slug(gate)}-k{k}.csv"
            write_plan(r["picks"], titles, name)
            write_words(
                hardest(r["charge"], r["alone"], target, supply, supply,
                        sourced_by(grouped, supply, target), titles,
                        got=r["got"], need=r["need"], done_at=r["done_at"],
                        worst=r["worst"]),
                name.replace("plan-", "words-"))
        rows.append({"gate": gate, "k": k,
                     "hours": round(r["hours"], 1), "videos": r["videos"],
                     "viewings": r["viewings"], "words_met": r["met"],
                     "words_total": len(target),
                     "teaching_lines": admits,
                     "share_of_lines": round(admits / len(teaching), 3),
                     "words_with_a_source": len(supply),
                     "opens_beyond_i1": len(extra),
                     "mean_encounters": round(r["mean_encounters"], 2)})
        say(f"  {gate:>9}: {r['hours']:>7.1f} h · {r['videos']:>4} videos · "
            f"{r['met']:,}/{len(target):,} met · admits "
            f"{admits / len(teaching):>5.1%} of teachable lines · "
            f"opens {len(extra):>3} more words "
            f"({time.perf_counter() - t:.0f}s)")
    write(rows, "07-depth-of-gate.csv")
    return rows


def one_walk(app, seed, gate: str, k: int, drop_machine: bool,
             drop_seg: bool, shelved=None, say=print) -> dict:
    """One arm, written out as a plan and a per-word cost file.

    `shelved` is passed in when a caller runs several arms over the same
    shelf: building it is forty seconds and the walk itself is often less,
    so re-reading the corpus per arm would be most of the cost.
    """
    if shelved is None:
        shelved = shelf(app, seed, with_episodes=True,
                        drop_machine=drop_machine, drop_seg=drop_seg)
    _, grouped, cost, says, reach, target = shelved
    with Database(app.settings.own) as database:
        titles = dict(database.rows("SELECT video_id, title FROM video"))
    t = time.perf_counter()
    supply = chances(grouped, target, reach, gate)
    r = walk(grouped, cost, says, target, supply, seed, k, gate, rewatch=True)
    name = (f"07-plan-{slug(gate)}-k{k}"
            f"{suffix(ENOUGH_LINES, drop_machine, drop_seg)}.csv")
    write_plan(r["picks"], titles, name)
    write_words(
        hardest(r["charge"], r["alone"], target, supply, supply,
                sourced_by(grouped, supply, target), titles,
                got=r["got"], need=r["need"], done_at=r["done_at"],
                worst=r["worst"]),
        name.replace("plan-", "words-"))
    say(f"  {gate:>4} K={k} · machine {'out' if drop_machine else 'in'} · "
        f"SEG {'out' if drop_seg else 'in'}: {r['hours']:>7.1f} h · "
        f"{r['videos']:>4} videos · {r['met']:,}/{len(target):,} met "
        f"({time.perf_counter() - t:.0f}s)")
    say(f"    -> {name}")
    return {"seed": "you",
            "episodes": sum(1 for x in grouped if x[0] == "e"),
            "gate": gate, "k": k, "rewatch": "yes",
            "hours": round(r["hours"], 1), "videos": r["videos"],
            "viewings": r["viewings"], "words_met": r["met"],
            "words_total": len(target),
            "mean_encounters": round(r["mean_encounters"], 2),
            # The scoring is named in the row, because the file holds runs
            # from before it changed and a row that does not say which one it
            # is cannot be told from a row that does.
            "note": ("frequency-weighted; machine-made dropped"
                     + ("; super easy german dropped" if drop_seg else "")
                     + f"; {sum(1 for w in target if len(supply.get(w, ())) >= k):,}"
                       f" words have {k}+ chances")}


# The arms asked for, in the order asked for: the strict gate without Super
# Easy German first, because that is the one to be watched, and the rest so
# that each gate's two SEG settings land together and can be read against
# each other as they arrive.
QUEUE = (("i+1", True), ("i+1", False),
         ("i+2", True), ("i+2", False),
         ("i+3", True), ("i+3", False))


def queue(app, seed, k: int = 5, say=print) -> list[dict]:
    """Six arms at K=5 with the machine-made channels out."""
    rows, shelves = [], {}
    for gate, drop_seg in QUEUE:
        if drop_seg not in shelves:
            t = time.perf_counter()
            shelves[drop_seg] = shelf(app, seed, with_episodes=True,
                                      drop_machine=True, drop_seg=drop_seg)
            _, grouped, cost, _, _, target = shelves[drop_seg]
            eps = sum(1 for x in grouped if x[0] == "e")
            say(f"  shelf · machine out · SEG "
                f"{'out' if drop_seg else 'in'}: {len(grouped) - eps:,} videos"
                f" + {eps:,} episodes · {sum(cost.values())/60:,.0f} h · "
                f"{len(target):,} words ({time.perf_counter() - t:.0f}s)")
        rows.append(one_walk(app, seed, gate, k, True, drop_seg,
                             shelved=shelves[drop_seg], say=say))
        # Written after every arm rather than at the end: six K=5 walks is a
        # long time to hold results in a process that might not finish.
        with (OUT / SUMMARY).open("a", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=list(rows[-1])).writerows(rows[-1:])
    return rows


def hunt(app, seed, gate: str = "i+1", k: int = 5, drop_machine: bool = True,
         drop_seg: bool = True, say=print) -> list[dict]:
    """Which words force a long video, and how short a new one would have to be.

    Not the same question as "which words did the plan spend the most on".
    A word that appears in a three-hour parliamentary session is charged a
    share of it, but so is every other word in that session -- rank by the
    longest video a word was met in and you get a list of whatever the
    longest video says, which is a fact about the video.

    What can be acted on is the *cheapest* thing on the shelf that could
    ever teach the word. If that is four minutes, no hunting will help; if
    it is two hundred, a shorter video carrying that word removes two
    hundred minutes of forced watching. `floor` is the whole supply, so this
    also says how much room there is: a word with one source at 204 minutes
    and nothing else is a different job from one with forty sources whose
    shortest happens to be long.

    `shortest_minutes` prices only the last step, though, and takes the
    prerequisites as free -- which they are not. `roadmap.effort` prices the
    chain in front of the word as well, by Knuth's generalisation of
    Dijkstra over the same hypergraph, and adds two columns:

    * `bottleneck_minutes` -- the longest single video on the cheapest way
      in. Every route to the word passes through a video at least this long,
      so it is the honest floor on the sitting the word costs, and it is
      never below `shortest_minutes`: the last step is one of the videos it
      maximises over.
    * `chain_minutes` -- every video on that derivation added up. A plan
      that certainly works, so an upper bound. The gap between the two is
      how much the word's real cost turns on sharing, which no derivation
      can settle.

    Both are computed under the i+1 rule, because that is the rule `effort`
    implements -- a sentence hands a word over when it is the last unknown.
    Under a looser gate a word can only get cheaper, so on an `i+2` run
    these two are bounds on the i+1 cost and not on that run's.
    """
    _, grouped, cost, says, reach, target = shelf(
        app, seed, with_episodes=True, drop_machine=drop_machine,
        drop_seg=drop_seg)
    with Database(app.settings.own) as database:
        titles = dict(database.rows("SELECT video_id, title FROM video"))
    supply = chances(grouped, target, reach, gate)
    where = sourced_by(grouped, supply, target)
    # One pass of Knuth per reading, over every sentence on the shelf priced
    # by whatever it was said in. Two and a half seconds for both.
    # How often the word is said at all, against how often it can teach.
    # `sowie` is said in 73 sentences across 49 videos and can teach from
    # one of them: it is a conjunction, so it joins two nouns, and a
    # specific noun is exactly what is not on a study list. A word like that
    # is not scarce and no shorter video will fix it -- the gate will.
    # Without these two columns the list says "hunt for it", which is the
    # wrong instruction for every common word whose company is unusual.
    said_in: dict = {}
    for item, lines in grouped.items():
        for line in lines:
            for unit in line.units & target:
                said_in.setdefault(unit, set()).add(item)
    priced = [(cost.get(item, 0.0), line.units)
              for item, lines in grouped.items() for line in lines]
    # `reach` is the same closure at budget=0, so the list has to be passed
    # or these price a rule the rest of the row is not using.
    held = frozenset(app.goal_units)
    floor_of = effort(priced, set(seed.units), BOTTLENECK, goals=held)
    chain_of = effort(priced, set(seed.units), CHAIN, goals=held)

    rows = []
    for unit in target:
        holds = where.get(unit, ())
        if not holds:
            rows.append({"kind": unit.kind, "key": unit.key, "sources": 0,
                         "bottleneck_minutes": "", "chain_minutes": "",
                         "shortest_minutes": "", "shortest_is": "", "where": "",
                         "longest_minutes": "", "total_minutes": "",
                         "teaching_sentences": len(supply.get(unit, ())),
                         "videos_saying_it": len(said_in.get(unit, ())),
                         "worth_hunting": "yes — nothing teaches it at all",
                         "note": "no source at all — needs a new video"})
            continue
        lengths = sorted((cost.get(item, 0.0), item) for item in holds)
        cheap, item = lengths[0]
        kind, name, link = watch_at(item, titles)
        rows.append({
            "kind": unit.kind, "key": unit.key, "sources": len(holds),
            "bottleneck_minutes": (round(floor_of[unit], 1)
                                   if unit in floor_of else ""),
            "chain_minutes": (round(chain_of[unit], 1)
                              if unit in chain_of else ""),
            "shortest_minutes": round(cheap, 1),
            "shortest_is": name, "where": link,
            "longest_minutes": round(lengths[-1][0], 1),
            "total_minutes": round(sum(x for x, _ in lengths), 1),
            "teaching_sentences": len(supply.get(unit, ())),
            # A new video replaces the *last* step and nothing before it. So
            # it only helps where the last step is the whole cost -- where
            # the bottleneck and the cheapest source are the same number. If
            # the floor is higher, something has to be learned first and a
            # shorter video for this word buys almost nothing, which is
            # worth saying outright rather than leaving in two columns for
            # the reader to subtract.
            "videos_saying_it": len(said_in.get(unit, ())),
            "worth_hunting": (
                "no — gated by what comes first"
                if floor_of.get(unit, 0.0) > cheap + 1e-6 else
                # Said in plenty of places and teachable in almost none: the
                # company it keeps is the problem, and a looser gate is the
                # answer, not another video.
                "no — common, but its sentences carry off-list words"
                if len(said_in.get(unit, ())) >= 8 and len(holds) <= 2 else
                "yes"),
            "note": ("only one source" if len(holds) == 1 else
                     "every source is long" if cheap >= 60 else ""),
        })
    # By the bottleneck, not by the last step: a word whose own video is
    # four minutes but which sits behind a two-hour prerequisite is a
    # two-hour word, and the old ordering put it near the bottom.
    rows.sort(key=lambda r: (-(r["bottleneck_minutes"]
                               or r["shortest_minutes"] or 1e9), r["key"]))
    name = (f"07-hunt-{slug(gate)}-k{k}"
            f"{suffix(ENOUGH_LINES, drop_machine, drop_seg)}.csv")
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    forced = [r for r in rows if r["bottleneck_minutes"]
              and r["bottleneck_minutes"] >= 60]
    worse = sum(1 for r in rows if r["bottleneck_minutes"]
                and r["shortest_minutes"]
                and r["bottleneck_minutes"] > r["shortest_minutes"])
    say(f"  {len(target):,} words · {sum(1 for r in rows if not r['sources']):,} "
        f"with no source · {len(forced):,} behind an hour or more")
    say(f"  {worse:,} cost more than their own video says, because of what "
        f"has to come first")
    worth = [r for r in rows if r["worth_hunting"].startswith("yes")
             and (r["shortest_minutes"] or 0) >= 30]
    common = sum(1 for r in rows if "off-list words" in r["worth_hunting"])
    say(f"  {len(worth):,} are worth hunting for right now — a shorter video "
        f"replaces the whole cost")
    say(f"  {common:,} are common words the gate blocks, not the shelf — "
        f"a looser gate is the fix, not another video")
    say(f"    -> {OUT / name}")
    return rows


def by_word(grouped, cost, says, target, supply, seed, k: int,
            order: list) -> dict:
    """Serve the words in a given order, cheapest way to each in turn.

    The other walk picks a video and takes whatever it teaches. This picks a
    *word* -- the commonest first -- and buys its K encounters as cheaply as
    it can, then moves to the next. Same corpus, same gate, same cap of
    `min(K, chances)`; only the thing being optimised is different.

    The one detail that decides whether this is sane: a viewing is absorbed
    for **every** word, not just the one it was bought for. Watching four
    videos for `hoch` hands out encounters to hundreds of others, and a loop
    that ignored them would buy the same minutes again and again. With them
    credited, most later words arrive already finished.

    The inner choice is exact rather than greedy. A word needs at most five
    distinct sentences and has a handful of videos that can give them, so
    the cheapest covering set is found by enumeration -- which is the whole
    subproblem, solved, not approximated. It is exact for the state it is
    asked in; the state then moves, because watching teaches other words.
    """
    need = {w: min(k, len(supply.get(w, ()))) or 1 for w in target}
    have = set(seed.units)
    seen: dict = {w: set() for w in target}
    spent, views, uniq, picks = 0.0, 0, set(), []
    done_at: dict = {}

    def offers(video):
        """New i+1 texts this video would give, per word, as things stand."""
        texts: dict = {}
        for line in grouped[video]:
            missing = line.units - have
            if len(missing) != 1:
                continue
            unit = next(iter(missing))
            if (unit in target and len(seen[unit]) < need[unit]
                    and line.text not in seen[unit]):
                texts.setdefault(unit, set()).add(line.text)
        return texts

    def absorb(video):
        """Watch it once, and credit every word it teaches."""
        nonlocal spent, views
        texts = offers(video)
        finished = []
        minutes = cost.get(video, 0.0)
        for unit, lines in texts.items():
            seen[unit] |= lines
            if len(seen[unit]) >= need[unit]:
                have.add(unit)
                finished.append(unit)
                done_at[unit] = (spent + minutes) / 60
        spent += minutes
        views += 1
        uniq.add(video)
        picks.append({"item": video, "minutes": minutes,
                      "encounters": sum(len(t) for t in texts.values()),
                      "completed": len(finished),
                      "again": video in uniq,
                      "words": sorted(w.key for w in finished)})

    def cheapest_set(word):
        """The least watching that finishes this word from here, or None.

        Enumerated over subsets, shortest videos first. The word wants at
        most five more texts, so no useful set is larger than five, and the
        candidates are only the videos that say it.
        """
        want = need[word] - len(seen[word])
        gives = {}
        for video in says.get(word, ()):
            if video not in grouped:
                continue
            lines = offers(video).get(word)
            if lines:
                gives[video] = lines
        if not gives:
            return None
        ranked = sorted(gives, key=lambda v: (cost.get(v, 0.0), str(v)))[:14]
        best, price = None, None
        for size in range(1, min(want, len(ranked)) + 1):
            for pick in itertools.combinations(ranked, size):
                if len(set().union(*(gives[v] for v in pick))) < want:
                    continue
                total = sum(cost.get(v, 0.0) for v in pick)
                if price is None or total < price:
                    best, price = pick, total
            if best is not None:
                break          # no larger set can be cheaper at equal cover
        if best is not None:
            return best
        # Cannot finish it in one go; take the best single step and return.
        return (max(ranked, key=lambda v: (len(gives[v]) / (cost.get(v) or 1e9),
                                           str(v))),)

    for word in order:
        while len(seen[word]) < need[word]:
            chosen = cheapest_set(word)
            if not chosen:
                break                    # nothing on the shelf can help now
            for video in chosen:
                absorb(video)
    met = sum(1 for w in target if len(seen[w]) >= need[w])
    return {"hours": spent / 60, "viewings": views, "videos": len(uniq),
            "met": met, "picks": picks, "done_at": done_at, "need": need,
            "got": {w: len(t) for w, t in seen.items()},
            "mean_encounters":
                statistics.mean([min(len(seen[w]), k) for w in target])}


# The chart is written by hand rather than drawn by a library. One plot does
# not earn matplotlib and the forty megabytes under it, and an SVG sits in
# `experiment_results/` beside the CSVs it came from, readable in a browser
# and in a diff.
PLOT_W, PLOT_H, PAD = 720, 420, 56
INK = ("#c0392b", "#2c7fb8", "#2e8b57")


def plot(series, name: str, title: str, x_label: str, y_label: str) -> Path:
    """A line chart, as SVG. `series` is (label, [(x, y), ...]) pairs."""
    points = [xy for _, rows in series for xy in rows]
    top_x = max(x for x, _ in points) or 1.0
    top_y = max(y for _, y in points) or 1.0

    def at(x, y):
        return (PAD + (x / top_x) * (PLOT_W - 2 * PAD),
                PLOT_H - PAD - (y / top_y) * (PLOT_H - 2 * PAD))

    out = [f"<svg xmlns='http://www.w3.org/2000/svg' width='{PLOT_W}' "
           f"height='{PLOT_H}' viewBox='0 0 {PLOT_W} {PLOT_H}' "
           "font-family='system-ui,sans-serif' font-size='12'>",
           f"<rect width='{PLOT_W}' height='{PLOT_H}' fill='#fff'/>",
           f"<text x='{PAD}' y='26' font-size='15' font-weight='600'>"
           f"{escape(title)}</text>"]
    for step in range(5):                       # gridlines and their labels
        y = PLOT_H - PAD - step / 4 * (PLOT_H - 2 * PAD)
        out.append(f"<line x1='{PAD}' y1='{y:.1f}' x2='{PLOT_W - PAD}' "
                   f"y2='{y:.1f}' stroke='#eee'/>")
        out.append(f"<text x='{PAD - 8}' y='{y + 4:.1f}' text-anchor='end' "
                   f"fill='#888'>{top_y * step / 4:,.0f}</text>")
        x = PAD + step / 4 * (PLOT_W - 2 * PAD)
        out.append(f"<text x='{x:.1f}' y='{PLOT_H - PAD + 18:.1f}' "
                   f"text-anchor='middle' fill='#888'>"
                   f"{top_x * step / 4:,.0f}</text>")
    out.append(f"<text x='{PLOT_W / 2}' y='{PLOT_H - 12}' "
               f"text-anchor='middle' fill='#555'>{escape(x_label)}</text>")
    out.append(f"<text x='14' y='{PLOT_H / 2}' fill='#555' "
               f"transform='rotate(-90 14 {PLOT_H / 2})' "
               f"text-anchor='middle'>{escape(y_label)}</text>")
    for n, (label, rows) in enumerate(series):
        path = " ".join(("M" if i == 0 else "L") + f"{at(*xy)[0]:.1f},{at(*xy)[1]:.1f}"
                        for i, xy in enumerate(rows))
        out.append(f"<path d='{path}' fill='none' stroke='{INK[n % 3]}' "
                   "stroke-width='2'/>")
        out.append(f"<text x='{PLOT_W - PAD - 6}' y='{PAD + 16 * n + 4}' "
                   f"text-anchor='end' fill='{INK[n % 3]}'>"
                   f"{escape(label)}</text>")
    out.append("</svg>")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def curves(app, seed, k: int = 5, say=print) -> list[dict]:
    """Three ways to order the same corpus, and what each buys when.

    They are not competing at the same thing, which is the point. The two
    video-driven walks minimise total hours; the word-driven one front-loads
    the commonest words and will take longer. Hours alone cannot separate
    them -- all three end in the same place -- so the measure is the shape:
    after so many hours, how much of the German you will actually hear can
    you read?
    """
    _, grouped, cost, says, reach, target = shelf(
        app, seed, with_episodes=True, drop_machine=True, drop_seg=True)
    supply = chances(grouped, target, reach, "i+1")
    count = frequency(grouped, target)
    whole = sum(count.values()) or 1
    order = sorted(target, key=lambda w: (-count[w], w.key))
    say(f"  {len(target):,} words · commonest: "
        f"{', '.join(w.key for w in order[:4])}")

    runs = []
    t = time.perf_counter()
    plain = walk(grouped, cost, says, target, supply, seed, k, "i+1",
                 rewatch=True, weight=FLAT)
    runs.append(("by video, encounters per minute", plain,
                 time.perf_counter() - t))
    t = time.perf_counter()
    weighed = walk(grouped, cost, says, target, supply, seed, k, "i+1",
                   rewatch=True, weight=FREQUENCY)
    runs.append(("by video, frequency per minute", weighed,
                 time.perf_counter() - t))
    t = time.perf_counter()
    worded = by_word(grouped, cost, says, target, supply, seed, k, order)
    runs.append(("by word, commonest first", worded, time.perf_counter() - t))

    def shape(run):
        """(hours, words finished, share of the corpus readable) over time.

        Built here and not inside the walks, because it has to be the same
        measure for all three. Recording it inside `walk` meant each one
        measured in whatever unit it happened to be maximising -- the
        unweighted walk counted words and the weighted one counted
        occurrences, and dividing the first by the corpus mass put it at
        0.8% where it had in fact finished 3,017 words.
        """
        landed = sorted((hours, count[w]) for w, hours in run["done_at"].items())
        seen, out = 0, []
        for hours, mass in landed:
            seen += mass
            out.append((hours, len(out) + 1, seen))
        return out

    rows, series = [], []
    for label, run, took in runs:
        run["curve"] = shape(run)
        say(f"  {label:34}{run['hours']:>7.1f} h · {run['videos']:>4} videos · "
            f"{run['met']:,}/{len(target):,} words ({took:.0f}s)")
        series.append((label, [(hours, seen / whole * 100)
                               for hours, _, seen in run["curve"]]))
        rows.append({"plan": label, "k": k, "hours": round(run["hours"], 1),
                     "videos": run["videos"], "viewings": run["viewings"],
                     "words_met": run["met"], "words_total": len(target),
                     "corpus_covered_pct": round(
                         run["curve"][-1][2] / whole * 100, 1) if run["curve"] else 0,
                     "hours_to_half": next(
                         (round(h, 1) for h, _, seen in run["curve"]
                          if seen / whole >= 0.5), "")})
    write(rows, f"07-curves-k{k}.csv")
    # The curve itself, thinned: 600 viewings is more points than a chart
    # can show and more rows than anyone reads.
    with (OUT / f"07-curves-k{k}-points.csv").open(
            "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["plan", "hours", "words_met", "corpus_covered_pct"])
        for label, run, _ in runs:
            for n, (hours, met, seen) in enumerate(run["curve"]):
                if n % 5 and n != len(run["curve"]) - 1:
                    continue
                writer.writerow([label, round(hours, 2), met,
                                 round(seen / whole * 100, 2)])
    where = plot(series, f"07-curves-k{k}.svg",
                 f"What you can read, as you watch (K={k})",
                 "hours watched", "% of corpus occurrences readable")
    say(f"    -> {where}")
    return rows


def chunked(grouped, cost, says, target, supply, seed, k: int, size: int,
            order: list, say=print) -> dict:
    """Plan by solving `size` words at a time, exactly, and watching the result.

    `walk` takes the single best video by marginal rate and never reconsiders.
    That is a one-step greedy, and the move it cannot make is the obvious
    one: two short videos that together finish a group of words, where each
    alone scores worse than a long video that also finishes them. An ILP over
    a handful of words at a time sees the pair, because it is choosing a
    *set*.

    So `size` is how far ahead the solver looks, in words. At 1 it is close
    to serving one word at a time; at every word at once it would be the
    joint cover `bound` solves. Between them is the question: how much of
    what joint solving buys can be had from a small window.

    **Every viewing costs its full length, including a rewatch.** There is no
    discount for a video already seen, and that is not an oversight: under
    i+1 a viewing hands over only the sentences that are the last unknown at
    that moment, so coming back later for the ones that have since opened
    means sitting through it again. The current plans do that 632 times for
    169 of their 598 hours. Sharing is carried instead by absorbing each
    viewing against *all* the words, so a later chunk finds its words already
    part-done -- which is where the saving actually comes from.

    One optimism worth naming: the constraint adds up each video's count of
    teaching sentences, and two videos can hold the same sentence, so a
    chosen set can promise five distinct encounters and deliver four. The
    absorb step sees the truth and the word simply stays pending for another
    round, so it costs a viewing rather than correctness.
    """
    import pulp                                        # noqa: PLC0415 — heavy

    need = {w: min(k, len(supply.get(w, ()))) or 1 for w in target}
    have = set(seed.units)
    seen: dict = {w: set() for w in target}
    spent, views, uniq, picks, done_at = 0.0, 0, set(), [], {}

    def offers(video):
        """New i+1 texts this video would hand over, per word, right now."""
        texts: dict = {}
        for line in grouped[video]:
            missing = line.units - have
            if len(missing) != 1:
                continue
            unit = next(iter(missing))
            if (unit in target and len(seen[unit]) < need[unit]
                    and line.text not in seen[unit]):
                texts.setdefault(unit, set()).add(line.text)
        return texts

    def absorb(video):
        nonlocal spent, views
        texts = offers(video)
        minutes = cost.get(video, 0.0)
        finished = []
        for unit, lines in texts.items():
            seen[unit] |= lines
            if len(seen[unit]) >= need[unit]:
                have.add(unit)
                finished.append(unit)
                done_at[unit] = (spent + minutes) / 60
        spent += minutes
        views += 1
        picks.append({"item": video, "minutes": minutes,
                      "encounters": sum(len(t) for t in texts.values()),
                      "completed": len(finished),
                      "again": video in uniq,
                      "words": sorted(w.key for w in finished)})
        uniq.add(video)

    def solve(chunk):
        """The cheapest set of viewings that advances these words furthest."""
        gives: dict = {}
        for word in chunk:
            for video in says.get(word, ()):
                if video in grouped and video not in gives:
                    gives[video] = offers(video)
        useful = {v: t for v, t in gives.items()
                  if any(w in t for w in chunk)}
        if not useful:
            return []
        problem = pulp.LpProblem("chunk", pulp.LpMinimize)
        pick = {v: pulp.LpVariable(f"v{n}", cat="Binary")
                for n, v in enumerate(sorted(useful, key=str))}
        problem += pulp.lpSum(cost.get(v, 0.0) * pick[v] for v in pick)
        asked = 0
        for word in chunk:
            # Capped at what is actually on offer, or the problem is
            # infeasible for every word the corpus cannot finish today.
            here = len(set().union(*(useful[v].get(word, set()) for v in pick))
                       or set())
            want = min(need[word] - len(seen[word]), here)
            if want <= 0:
                continue
            problem += pulp.lpSum(len(useful[v].get(word, ())) * pick[v]
                                  for v in pick) >= want
            asked += 1
        if not asked:
            return []
        problem.solve(pulp.PULP_CBC_CMD(msg=False))
        if pulp.LpStatus[problem.status] != "Optimal":
            return []
        return [v for v in pick if pick[v].value() and pick[v].value() > 0.5]

    rounds = 0
    while True:
        pending = [w for w in order if len(seen[w]) < need[w]]
        if not pending:
            break
        rounds += 1
        moved = False
        for start in range(0, len(pending), size):
            chunk = [w for w in pending[start:start + size]
                     if len(seen[w]) < need[w]]     # some finished en route
            if not chunk:
                continue
            for video in solve(chunk):
                absorb(video)
                moved = True
        if not moved:
            break            # a whole pass bought nothing; nothing left to buy
    met = sum(1 for w in target if len(seen[w]) >= need[w])
    say(f"  chunk {size:>3}: {spent / 60:>7.1f} h · {len(uniq):>4} videos · "
        f"{views:,} viewings · {met:,}/{len(target):,} met · {rounds} passes")
    return {"hours": spent / 60, "viewings": views, "videos": len(uniq),
            "met": met, "picks": picks, "done_at": done_at, "need": need,
            "got": {w: len(t) for w, t in seen.items()},
            "mean_encounters":
                statistics.mean([min(len(seen[w]), k) for w in target])}


def chunks(app, seed, k: int = 5, sizes=(1, 10, 50), say=print) -> list[dict]:
    """The greedy against an ILP that plans several words at a time.

    Same shelf, same gate, same K, same cap, same cost for every viewing.
    The only thing that varies is how many words the planner is allowed to
    consider at once before it commits to watching something.
    """
    _, grouped, cost, says, reach, target = shelf(
        app, seed, with_episodes=True, drop_machine=True, drop_seg=True)
    supply = chances(grouped, target, reach, "i+1")
    count = frequency(grouped, target)
    whole = sum(count.values()) or 1
    order = sorted(target, key=lambda w: (-count[w], w.key))
    with Database(app.settings.own) as database:
        titles = dict(database.rows("SELECT video_id, title FROM video"))
    say(f"  {len(target):,} words · K={k} · i+1 · machine out · SEG out")

    runs = []
    t = time.perf_counter()
    greedy = walk(grouped, cost, says, target, supply, seed, k, "i+1",
                  rewatch=True)
    say(f"  greedy   : {greedy['hours']:>7.1f} h · {greedy['videos']:>4} videos · "
        f"{greedy['viewings']:,} viewings · {greedy['met']:,}/{len(target):,} met")
    runs.append(("greedy, one video at a time", greedy, time.perf_counter() - t))
    for size in sizes:
        t = time.perf_counter()
        run = chunked(grouped, cost, says, target, supply, seed, k, size,
                      order, say=say)
        runs.append((f"ILP, {size} words at a time", run, time.perf_counter() - t))

    rows, series = [], []
    for label, run, took in runs:
        landed = sorted((hours, count[w]) for w, hours in run["done_at"].items())
        seen_mass, curve = 0, []
        for hours, mass in landed:
            seen_mass += mass
            curve.append((hours, seen_mass / whole * 100))
        series.append((label, curve))
        rows.append({"plan": label, "k": k, "hours": round(run["hours"], 1),
                     "videos": run["videos"], "viewings": run["viewings"],
                     "words_met": run["met"], "words_total": len(target),
                     "corpus_covered_pct": round(curve[-1][1], 1) if curve else 0,
                     "seconds": round(took)})
        name = (f"07-plan-chunk{label.split()[1].rstrip(',')}-k{k}.csv"
                if label.startswith("ILP") else f"07-plan-greedy-k{k}.csv")
        write_plan(run["picks"], titles, name)
    write(rows, f"07-chunks-k{k}.csv")
    where = plot(series, f"07-chunks-k{k}.svg",
                 f"Greedy against an ILP with a wider window (K={k})",
                 "hours watched", "% of corpus occurrences readable")
    say(f"    -> {where}")
    return rows


def bound(grouped, cost, supply, target, limit: int = 900) -> dict:
    """Min-cost cover under the relaxed rule. A lower bound, not a plan."""
    import pulp                                        # noqa: PLC0415 — heavy

    can: dict = {}
    for v, ss in grouped.items():
        for s in ss:
            for w in s.units & target:
                if w in supply and s.text in supply[w]:
                    can.setdefault(w, set()).add(v)
    problem = pulp.LpProblem("cover", pulp.LpMinimize)
    videos = sorted({v for vs in can.values() for v in vs})
    pick = {v: pulp.LpVariable(f"v{i}", cat="Binary")
            for i, v in enumerate(videos)}
    problem += pulp.lpSum(cost[v] * pick[v] for v in videos)
    for vs in can.values():
        problem += pulp.lpSum(pick[v] for v in vs) >= 1
    problem.solve(pulp.PULP_CBC_CMD(msg=False, gapRel=0.0, timeLimit=limit))
    status = pulp.LpStatus[problem.status]
    if status == "Optimal":
        chosen = [v for v in videos if pick[v].value() and pick[v].value() > 0.5]
        return {"hours": sum(cost[v] for v in chosen) / 60, "videos": len(chosen),
                "sourced": len(can), "chosen": chosen, "kind": "exact"}
    # Timed out. The incumbent is a *feasible cover*, so its cost is an upper
    # bound on this cover's optimum — reporting it as a lower bound would
    # overstate, and could put it above the true ordered optimum, which is the
    # one thing a bound must never do. The LP relaxation is a valid lower
    # bound whatever happens, and solves in seconds.
    for v in videos:
        pick[v].cat = "Continuous"
        pick[v].upBound = 1
    problem.solve(pulp.PULP_CBC_CMD(msg=False))
    return {"hours": pulp.value(problem.objective) / 60, "videos": 0,
            "sourced": len(can), "chosen": [],
            "kind": f"LP relaxation (integer solve was {status} at {limit}s)"}


def watch_at(item, titles: dict) -> tuple[str, str, str]:
    """(kind, name, where) for one thing on the shelf.

    An Easy German episode has no video id — the transcripts are prose, and
    the reader watches them on the channel — so its `where` is the file the
    text came from and the episode number in its name is the way to find it.
    """
    if item[0] == "v":
        return ("video", titles.get(item[1], item[1]),
                f"https://www.youtube.com/watch?v={item[1]}")
    return ("episode", Path(item[1]).stem, item[1])


def run(app, seeds, ks=(1, 2, 3, 4, 5), with_episodes: bool = True,
        say=print) -> list[dict]:
    rows = []
    for name, seed in seeds:
        _, grouped, cost, says, reach, target = shelf(app, seed, with_episodes)
        eps = sum(1 for k in grouped if k[0] == "e")
        say(f"\n=== {name} — {len(target):,} words to learn · "
            f"{len(grouped) - eps:,} videos + {eps:,} Easy German episodes · "
            f"{sum(cost.values())/60:.0f} h shelf")
        for gate in ("i+1", "any"):
            supply = chances(grouped, target, reach, gate)
            enough = {k: sum(1 for w in target if len(supply.get(w, ())) >= k)
                      for k in ks}
            if gate == "i+1":
                lb = bound(grouped, cost, supply, target)
                say(f"  lower bound (K=1, i+1): {lb['videos']} videos, "
                    f"{lb['hours']:.1f} h, {lb['sourced']:,} words have a source")
                rows.append({"seed": name, "episodes": eps,
                             "gate": gate, "k": 0,
                             "rewatch": "", "hours": round(lb["hours"], 1),
                             "videos": lb["videos"], "viewings": "",
                             "words_met": lb["sourced"], "mean_encounters": "",
                             "note": "lower bound, ordering relaxed away"})
            for k in ks:
                for rewatch in (False, True):
                    r = walk(grouped, cost, says, target, supply, seed,
                             k, gate, rewatch)
                    rows.append({"seed": name, "episodes": eps,
                                 "gate": gate, "k": k,
                                 "rewatch": "yes" if rewatch else "no",
                                 "hours": round(r["hours"], 1),
                                 "videos": r["videos"],
                                 "viewings": r["viewings"],
                                 "words_met": r["met"],
                                 "mean_encounters": round(r["mean_encounters"], 2),
                                 "note": f"{enough[k]:,} words have {k}+ chances"})
                    say(f"  {gate:>3} K={k} rewatch={'yes' if rewatch else 'no ':<3}"
                        f" {r['videos']:>4} videos {r['viewings']:>5} viewings "
                        f"{r['hours']:>7.1f} h  {r['met']:>5,}/{len(target):,} met")
    return rows


def write(rows, name="05-video-order.csv") -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path

def open_walk(grouped, cost, says, target, seed, k: int = 1,
              rewatch: bool = True, order: list | None = None) -> dict:
    """The walk when off-list words may be learned as stepping stones.

    `walk` above holds you to the list: a sentence carrying any word that is
    not a goal can never be i+1, so it teaches nothing, ever. That is the
    strictest reading and it is what makes `sowie` cost 204 minutes — its only
    sentence with no off-list word in it happens to sit inside a long film.

    Here every sentence with exactly one unknown teaches that word, on the
    list or not. Off-list words are not the point, so they count as learned at
    the first encounter; goal words still need K. They are bought, in effect,
    whenever a video is watched for other reasons.

    That creates a move a greedy on goal-words-per-minute cannot see: a cheap
    video teaching nothing on the list, which unlocks a goal somewhere else.
    So when nothing teaches a goal directly, the walk looks one step further
    and takes whatever most increases the goals that are *about* to become
    reachable, per minute — the same shape as `RoadmapBuilder._relaxed_step`,
    which exists for the same reason.
    """
    need = {w: k for w in target}
    have = set(seed.units)
    seen: dict = {w: set() for w in target}
    # Charged as in `walk`, with one addition: a stepping stone teaches no
    # goal at all, so its minutes are split across the goals it *opens*.
    # Leaving them uncharged would hide the whole point -- the ten minutes
    # spent to make `sowie` cost twenty instead of two hundred belong to
    # `sowie`, and to nothing else.
    charge: dict = {w: 0.0 for w in target}
    alone: dict = {w: 0.0 for w in target}
    done_at: dict = {}
    worst: dict = {}

    def teaches(video):
        """(goal encounters, texts per goal, off-list words picked up)."""
        texts: dict = {}
        spare = set()
        for s in grouped[video]:
            missing = s.units - have
            if len(missing) != 1:
                continue
            w = next(iter(missing))
            if w in target:
                if len(seen[w]) < need[w] and s.text not in seen[w]:
                    texts.setdefault(w, set()).add(s.text)
            else:
                spare.add(w)
        return sum(len(t) for t in texts.values()), texts, spare

    def unlocks(video):
        """Goals that would become sole-unknown somewhere, if this were seen.

        Counted over the sentences the off-list words it teaches would open,
        which is the whole reason to watch a video that teaches nothing. The
        goals themselves and not their number, because whoever pays for a
        stepping stone is exactly this set.
        """
        _, _, spare = teaches(video)
        if not spare:
            return set()
        after = have | spare
        opened = set()
        for w in spare:
            for other in says.get(w, ()):  # only videos that say those words
                for s in grouped[other]:
                    missing = s.units - after
                    if len(missing) == 1:
                        got = next(iter(missing))
                        if got in target and len(seen[got]) < need[got]:
                            opened.add(got)
        return opened

    queue = list(order) if order is not None else None
    score = {} if queue is not None else {v: teaches(v) for v in grouped}
    pool, spent, views, uniq, picks = set(grouped), 0.0, 0, set(), []
    while pool:
        if queue is not None:
            if not queue:
                break
            best = queue.pop(0)
            score[best] = teaches(best)
        else:
            best = max(pool, key=lambda v: (score[v][0] / (cost.get(v) or 1e9),
                                            score[v][0], str(v)))
        gain, texts, spare = score[best]
        stepping, opened = False, set()
        if not gain:
            if queue is not None:
                # Replaying one that was chosen for what it opens, not what
                # it teaches. Only this video needs asking, not the pool.
                opened = unlocks(best)
            else:
                # Nothing teaches a goal now. Buy the cheapest unlock instead.
                rated = [(unlocks(v), v) for v in pool]
                opened, best = max(rated, key=lambda p: (
                    len(p[0]) / (cost.get(p[1]) or 1e9), str(p[1])))
            if not opened:
                break
            gain, texts, spare = score[best]
            stepping = True
        minutes = cost.get(best, 0.0)
        finished = []
        for w, ts in texts.items():
            seen[w] |= ts
            charge[w] += minutes * len(ts) / gain
            if len(texts) == 1:
                alone[w] += minutes
            if minutes > worst.get(w, (0.0, None))[0]:
                worst[w] = (minutes, best)
            if len(seen[w]) >= need[w]:
                have.add(w)
                finished.append(w)
                done_at[w] = (spent + minutes) / 60
        for w in opened:
            charge[w] += minutes / len(opened)
        have |= spare
        spent += minutes
        views += 1
        picks.append({"item": best, "minutes": minutes,
                      "encounters": gain, "completed": len(finished),
                      "stepping_stone": stepping, "spare": len(spare),
                      "words": sorted(w.key for w in finished)})
        uniq.add(best)
        if not rewatch:
            pool.discard(best)
        if queue is None:
            touched = {best} | {x for w in list(texts) + list(spare)
                                for x in says.get(w, set())}
            for v in touched & pool:
                score[v] = teaches(v)
    met = sum(1 for w in target if len(seen[w]) >= need[w])
    extra = len(have - set(seed.units) - target)
    return {"hours": spent / 60, "viewings": views, "videos": len(uniq),
            "met": met, "picks": picks, "off_list_learned": extra,
            "charge": charge, "alone": alone, "done_at": done_at,
            "worst": worst, "need": need,
            "got": {w: len(t) for w, t in seen.items()},
            "mean_encounters":
                statistics.mean([min(len(seen[w]), k) for w in target])}


def sourced_by(grouped, supply, target) -> dict:
    """unit -> the things on the shelf that could ever teach it.

    `chances` counts sentences, which is what K needs; this counts the
    videos and episodes those sentences sit in, which is what a hunt needs.
    One source means one thing in the world stands between you and that
    word, and if it is three hours long you pay three hours.
    """
    out: dict = {}
    for item, ss in grouped.items():
        for s in ss:
            for w in s.units & target:
                if w in supply and s.text in supply[w]:
                    out.setdefault(w, set()).add(item)
    return out


def cover_charge(grouped, cost, supply, target, chosen) -> tuple[dict, dict, set]:
    """Split a cover's minutes over the words that put each video in it.

    A cover has no order and no encounters, so the walk's rule does not
    apply. What holds instead: a word is assigned to its cheapest source in
    the cover -- the video it is plausibly *there* for -- and each video's
    minutes are split evenly across its assignees. Totals still match.

    `alone` is the stronger claim, and the one to hunt on: the video exists
    for this word and no other, so taking the word off the list takes the
    whole video with it.
    """
    picked = set(chosen)
    can = {w: vs & picked for w, vs in
           sourced_by(grouped, supply, target).items()}
    can = {w: vs for w, vs in can.items() if vs}
    mine: dict = {}
    for w, vs in can.items():
        mine.setdefault(min(vs, key=lambda v: (cost.get(v, 0.0), str(v))),
                        []).append(w)
    charge = {w: 0.0 for w in target}
    for v, words in mine.items():
        for w in words:
            charge[w] += cost.get(v, 0.0) / len(words)
    forced: dict = {}
    for w, vs in can.items():
        if len(vs) == 1:
            forced.setdefault(next(iter(vs)), []).append(w)
    alone = {w: 0.0 for w in target}
    for v, words in forced.items():
        if len(words) == 1:
            alone[words[0]] = cost.get(v, 0.0)
    return charge, alone, set(can)


HARD_FIELDS = ["kind", "key", "met", "minutes_charged", "hours_charged",
               "sole_minutes", "encounters", "needed", "finish_hour",
               "longest_minutes", "longest_is", "where", "sources",
               "teaching_sentences", "any_sentences"]


def hardest(charge, alone, target, supply, anywhere, sources, titles,
            got=None, need=None, done_at=None, worst=None,
            covered=None) -> list[dict]:
    """Every word, and what it cost, dearest first.

    Words never met come first whatever their charge, because their real
    cost is not a number: nothing here can teach them at any length, so they
    are the first thing worth going to look for. Among those, the ones said
    least often anywhere in the corpus come first -- a word with no line at
    all needs a new video, while one said sixteen times is already here and
    only ever blocked, which a shorter video will not fix.
    """
    rows = []
    for w in target:
        # A cover has no encounters to count, so it says outright which words
        # it sources. Without that every row here read `met`, and the words a
        # cover cannot reach at all -- the ones worth going to find -- sank to
        # the bottom of the two files that exist to show them.
        done = (w in covered if covered is not None
                else got is None or got.get(w, 0) >= need.get(w, 1))
        long_min, long_at = worst.get(w, (0.0, None)) if worst else (0.0, None)
        kind, name, where = (watch_at(long_at, titles) if long_at
                             else ("", "", ""))
        rows.append({
            "kind": w.kind, "key": w.key, "met": "yes" if done else "no",
            "minutes_charged": round(charge.get(w, 0.0), 1),
            "hours_charged": round(charge.get(w, 0.0) / 60, 2),
            "sole_minutes": round(alone.get(w, 0.0), 1),
            "encounters": "" if got is None else got.get(w, 0),
            "needed": "" if need is None else need.get(w, ""),
            "finish_hour": ("" if not done_at or w not in done_at
                            else round(done_at[w], 2)),
            "longest_minutes": round(long_min, 1) if long_min else "",
            "longest_is": name, "where": where,
            "sources": len(sources.get(w, ())),
            "teaching_sentences": len(supply.get(w, ())),
            "any_sentences": len(anywhere.get(w, ())),
        })
    rows.sort(key=lambda r: (r["met"] == "yes",
                             r["any_sentences"] if r["met"] == "no" else 0,
                             -r["minutes_charged"], r["key"]))
    return rows


def write_words(rows, name) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HARD_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


# The eight experiments, as the plans on disk name them: which file holds
# the order, how it was walked, and what the per-word costs are called.
RUNS = (
    ("07-plan-i1-k1.csv",   "i+1",  1, "walk"),
    ("07-plan-i1-k5.csv",   "i+1",  5, "walk"),
    ("07-plan-any-k1.csv",  "any",  1, "walk"),
    ("07-plan-any-k5.csv",  "any",  5, "walk"),
    ("07-plan-open-k1.csv", "i+1",  1, "open"),
    ("07-plan-open-k5.csv", "i+1",  5, "open"),
    ("07-cover-i1-k0.csv",  "i+1",  0, "cover"),
    ("07-cover-any-k0.csv", "any",  0, "cover"),
)


def item_of(kind: str, where: str):
    """The shelf key a written plan row came from."""
    return ("v", where.rsplit("v=", 1)[1]) if kind == "video" else ("e", where)


def saved_plan(path: Path) -> tuple[list, list[dict]]:
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [item_of(r["kind"], r["where"]) for r in rows], rows


def check(replayed: list[dict], rows: list[dict], name: str) -> None:
    """A replay is only worth having if it lands where the plan landed."""
    if len(replayed) != len(rows):
        raise SystemExit(f"{name}: replayed {len(replayed)} of {len(rows)} steps"
                         " — the corpus or your known words have moved since")
    for n, (pick, row) in enumerate(zip(replayed, rows), 1):
        got, want = pick["encounters"], int(row["encounters"] or 0)
        if got != want:
            raise SystemExit(f"{name}: step {n} gave {got} encounters, "
                             f"the plan says {want}")
        if " ".join(pick["words"]) != row["words"]:
            raise SystemExit(f"{name}: step {n} finished different words")


def costs(app, seed, say=print) -> None:
    """Per-word costs for every experiment 07 run, from the saved plans."""
    t = time.perf_counter()
    _, grouped, cost, says, reach, target = shelf(app, seed, with_episodes=True)
    say(f"  shelf ready ({time.perf_counter() - t:.0f}s) · "
        f"{len(target):,} words to learn")
    with Database(app.settings.own) as database:
        titles = dict(database.rows("SELECT video_id, title FROM video"))
    supplies = {g: chances(grouped, target, reach, g) for g in ("i+1", "any")}
    sources = {g: sourced_by(grouped, supplies[g], target)
               for g in ("i+1", "any")}

    for plan, gate, k, how in RUNS:
        path = OUT / plan
        if not path.exists():
            say(f"  {plan}: not written yet, skipped")
            continue
        order, rows = saved_plan(path)
        missing = [i for i in order if i not in grouped]
        if missing:
            raise SystemExit(f"{plan}: {len(missing)} of its items are not on "
                             f"the shelf, e.g. {missing[0]}")
        t = time.perf_counter()
        # A stepping stone can reach a word no strictly-i+1 sentence can, so
        # what counts as a source depends on how the plan was walked, not
        # only on its gate. Getting this wrong would sort `sowie` among the
        # hopeless in the one file that shows it being learned cheaply.
        seen_as = "any" if how == "open" else gate
        if how == "cover":
            charge, alone, covered = cover_charge(grouped, cost,
                                                  supplies[gate], target, order)
            extra = {"covered": covered}
        else:
            if how == "open":
                r = open_walk(grouped, cost, says, target, seed, k=k,
                              rewatch=True, order=order)
            else:
                r = walk(grouped, cost, says, target, supplies[gate], seed,
                         k, gate, rewatch=True, order=order)
            check(r["picks"], rows, plan)
            charge, alone = r["charge"], r["alone"]
            extra = {"got": r["got"], "need": r["need"],
                     "done_at": r["done_at"], "worst": r["worst"]}
        spent = sum(float(r["minutes"]) for r in rows)
        short = abs(sum(charge.values()) - spent)
        if short > 0.5:
            say(f"  {plan}: WARNING {short:.1f} of {spent:.0f} minutes "
                "went uncharged")
        out = write_words(
            hardest(charge, alone, target, supplies[gate], supplies["any"],
                    sources[seen_as], titles, **extra),
            plan.replace("plan-", "words-").replace("cover-", "words-"))
        # Where the hours actually sit. A plan is not dear because 3,600
        # words each cost a little; it is dear because a few hundred do,
        # and nearly all of those have exactly one thing on the shelf that
        # can teach them. That is the number a hunt acts on.
        paid = sorted((charge.get(w, 0.0) for w in target), reverse=True)
        lonely = [w for w in target
                  if len(sources[seen_as].get(w, ())) == 1 and charge.get(w)]
        say(f"  {plan}: {spent/60:.1f} h over "
            f"{sum(1 for c in paid if c > 0):,} words · top 100 carry "
            f"{sum(paid[:100])/60:.0f} h ({sum(paid[:100])/spent:.0%}) · "
            f"{len(lonely):,} words have one source and cost "
            f"{sum(charge[w] for w in lonely)/60:.0f} h "
            f"({time.perf_counter() - t:.0f}s)")
        say(f"    -> {out}")


def write_plan(picks, titles, name) -> Path:
    """One viewing a row, with a link, so the plan can be watched."""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    seen: set = set()
    cumulative = 0.0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["position", "kind", "name", "where", "minutes",
                         "cumulative_hours", "repeat", "stepping_stone",
                         "encounters", "words_completed", "off_list_gained",
                         "words"])
        for n, pick in enumerate(picks, 1):
            kind, what, where = watch_at(pick["item"], titles)
            cumulative += pick["minutes"]
            writer.writerow([n, kind, what, where, round(pick["minutes"], 1),
                             round(cumulative / 60, 2),
                             "yes" if pick["item"] in seen else "",
                             "yes" if pick.get("stepping_stone") else "",
                             pick["encounters"], pick["completed"],
                             pick.get("spare", ""), " ".join(pick["words"])])
            seen.add(pick["item"])
    return path


def stepping(app, seed, ks=(1, 5), say=print) -> list[dict]:
    """The walks that may learn a word off the list to reach one on it."""
    t = time.perf_counter()
    _, grouped, cost, says, _, target = shelf(app, seed, with_episodes=True)
    say(f"  shelf ready ({time.perf_counter() - t:.0f}s) · "
        f"{len(target):,} goal words")
    with Database(app.settings.own) as database:
        titles = dict(database.rows("SELECT video_id, title FROM video"))
    rows = []
    for k in ks:
        t = time.perf_counter()
        r = open_walk(grouped, cost, says, target, seed, k=k, rewatch=True)
        stones = sum(1 for p in r["picks"] if p["stepping_stone"])
        say(f"  K={k}: {r['videos']:>4} videos · {r['viewings']:>4} viewings · "
            f"{r['hours']:>6.1f} h · {r['met']:,}/{len(target):,} met · "
            f"{stones} stepping stones · {r['off_list_learned']:,} off-list "
            f"words ({time.perf_counter() - t:.0f}s)")
        say(f"    -> {write_plan(r['picks'], titles, f'07-plan-open-k{k}.csv')}")
        rows.append({"seed": "you",
                     "episodes": sum(1 for x in grouped if x[0] == "e"),
                     "gate": "i+1 open", "k": k, "rewatch": "yes",
                     "hours": round(r["hours"], 1), "videos": r["videos"],
                     "viewings": r["viewings"], "words_met": r["met"],
                     "words_total": len(target),
                     "mean_encounters": round(r["mean_encounters"], 2),
                     "note": f"off-list allowed; {stones} stepping stones, "
                             f"{r['off_list_learned']:,} extra words learned"})
    return rows


def suffix(floor: int, drop_machine: bool, drop_seg: bool = False) -> str:
    """What a run's files are called, beyond the gate and K.

    The default shelf carries no suffix at all, so the first runs keep the
    names they were written under and the page that reads them needs no
    special case for "the original one".
    """
    return (("" if floor == ENOUGH_LINES else f"-floor{floor}")
            + ("-nomachine" if drop_machine else "")
            + ("-noseg" if drop_seg else ""))


def sweep(app, seed, floor: int = ENOUGH_LINES, drop_machine: bool = False,
          say=print) -> list[dict]:
    """The whole suite again over a differently-made shelf.

    Written to its own files rather than over the originals: the point is
    the difference between two shelves, so both have to survive. `target` is
    untouched by either knob -- reachability is computed over the corpus and
    not over what is watchable -- so the runs stay comparable word for word,
    and thinning the material shows up as words unmet rather than as a
    smaller question cheaply answered.
    """
    t = time.perf_counter()
    shelved = shelf(app, seed, with_episodes=True, episode_floor=floor,
                    drop_machine=drop_machine)
    _, grouped, cost, says, reach, target = shelved
    eps = sum(1 for k in grouped if k[0] == "e")
    say(f"  shelf · episode floor {floor} · machine-made channels "
        f"{'dropped' if drop_machine else 'kept'}: "
        f"{len(grouped) - eps:,} videos + "
        f"{eps:,} episodes · {sum(cost.values())/60:,.0f} h · "
        f"{len(target):,} words ({time.perf_counter() - t:.0f}s)")
    with Database(app.settings.own) as database:
        titles = dict(database.rows("SELECT video_id, title FROM video"))
    supplies = {g: chances(grouped, target, reach, g) for g in ("i+1", "any")}
    sources = {g: sourced_by(grouped, supplies[g], target)
               for g in ("i+1", "any")}

    rows = []
    for gate, k, how in (("i+1", 0, "cover"), ("i+1", 1, "walk"),
                         ("i+1", 5, "walk"), ("any", 0, "cover"),
                         ("any", 1, "walk"), ("any", 5, "walk"),
                         ("i+1", 1, "open")):
        t = time.perf_counter()
        # `i1`, not `i+1`: the floor-40 files are named that way and a `+`
        # in a filename is a nuisance to glob.
        tag = "open" if how == "open" else gate.replace("i+1", "i1")
        name = (f"07-{'cover' if how == 'cover' else 'plan'}-{tag}-k{k}"
                f"{suffix(floor, drop_machine)}.csv")
        if how == "cover":
            lb = bound(grouped, cost, supplies[gate], target)
            if not lb["chosen"]:
                # The integer solve timed out and `bound` fell back to the LP
                # relaxation, which gives a number but no set of videos. There
                # is nothing to price per word, and writing the file anyway
                # would show 3,660 words costing nothing, which reads as an
                # answer rather than as a missing one.
                rows.append({"seed": "you", "episodes": eps, "gate": gate,
                             "k": k, "rewatch": "", "hours": round(lb["hours"], 1),
                             "videos": "", "viewings": "",
                             "words_met": lb["sourced"], "words_total": len(target),
                             "mean_encounters": "",
                             "note": f"episode floor {floor}"
                                     + ("; machine-made dropped"
                                        if drop_machine else "")
                                     + f"; {lb['kind']}"})
                say(f"  {gate:>8} K={k}: {lb['hours']:>7.1f} h · "
                    f"{lb['kind']} — no cover to price "
                    f"({time.perf_counter() - t:.0f}s)")
                continue
            charge, alone, covered = cover_charge(grouped, cost, supplies[gate],
                                                  target, lb["chosen"])
            hours, met, videos, viewings = (lb["hours"], lb["sourced"],
                                            lb["videos"], "")
            picks = [{"item": v, "minutes": cost.get(v, 0.0), "encounters": "",
                      "completed": "", "words": []} for v in sorted(
                          lb["chosen"], key=lambda v: -cost.get(v, 0.0))]
            extra, note = {"covered": covered}, f"minimum cover, {lb['kind']}"
        else:
            if how == "open":
                r = open_walk(grouped, cost, says, target, seed, k=k,
                              rewatch=True)
                stones = sum(1 for x in r["picks"] if x["stepping_stone"])
                note = (f"off-list allowed; {stones} stepping stones, "
                        f"{r['off_list_learned']:,} extra words learned")
            else:
                r = walk(grouped, cost, says, target, supplies[gate], seed,
                         k, gate, rewatch=True)
                note = (f"{sum(1 for w in target if len(supplies[gate].get(w, ())) >= k):,}"
                        f" words have {k}+ chances")
            hours, met = r["hours"], r["met"]
            videos, viewings, picks = r["videos"], r["viewings"], r["picks"]
            charge, alone = r["charge"], r["alone"]
            extra = {"got": r["got"], "need": r["need"],
                     "done_at": r["done_at"], "worst": r["worst"]}
        write_plan(picks, titles, name)
        write_words(
            hardest(charge, alone, target, supplies[gate], supplies["any"],
                    sources["any" if how == "open" else gate], titles, **extra),
            name.replace("plan-", "words-").replace("cover-", "words-"))
        rows.append({"seed": "you", "episodes": eps,
                     "gate": "i+1 open" if how == "open" else gate, "k": k,
                     "rewatch": "" if how == "cover" else "yes",
                     "hours": round(hours, 1), "videos": videos,
                     "viewings": viewings, "words_met": met,
                     "words_total": len(target),
                     "mean_encounters": ("" if how == "cover"
                                         else round(r["mean_encounters"], 2)),
                     "note": f"episode floor {floor}"
                             + ("; machine-made dropped" if drop_machine else "")
                             + f"; {note}"})
        say(f"  {rows[-1]['gate']:>8} K={k}: {hours:>7.1f} h · "
            f"{met:,}/{len(target):,} met ({time.perf_counter() - t:.0f}s)")
    return rows


def main() -> None:
    import sys                                        # noqa: PLC0415

    from context import Application                   # noqa: PLC0415

    what = sys.argv[1] if len(sys.argv) > 1 else "costs"
    app = Application()
    if what == "costs":
        costs(app, app.known_set())
    elif what == "chunks":
        chunks(app, app.known_set(),
               int(sys.argv[2]) if len(sys.argv) > 2 else 5)
    elif what == "curves":
        curves(app, app.known_set(),
               int(sys.argv[2]) if len(sys.argv) > 2 else 5)
    elif what == "hunt":
        hunt(app, app.known_set())
    elif what == "queue":
        k = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        queue(app, app.known_set(), k)
    elif what == "queue":
        k = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        queue(app, app.known_set(), k)
    elif what == "depth":
        k = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        depth(app, app.known_set(), k)
    elif what == "sweep":
        rest = sys.argv[2:]
        floor = next((int(x) for x in rest if x.isdigit()), ENOUGH_LINES)
        rows = sweep(app, app.known_set(), floor,
                     drop_machine="nomachine" in rest)
        with (OUT / SUMMARY).open("a", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=list(rows[0])).writerows(rows)
    elif what == "stepping":
        rows = stepping(app, app.known_set())
        with (OUT / SUMMARY).open("a", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=list(rows[0])).writerows(rows)
    else:
        raise SystemExit("usage: video_order.py costs|stepping|"
                         "depth [K] | queue [K] | hunt | curves [K] | chunks [K] | "
                         "sweep [episode-floor] [nomachine]")


if __name__ == "__main__":
    main()
