"""How much watching a word costs at the very least, and at the very most.

`reach.py` answers whether a word can ever be learned. This answers how dear
it is to get to, which is a different question and needs a different kind of
closure -- one with a priority queue rather than a work list, because a
cheaper way to a word can turn up after an expensive one and has to displace
it.

**Why this is not Dijkstra.** In a graph you reach a node from one
predecessor, so relaxation takes a minimum over incoming edges. Here a word
is learned from a *sentence*, and a sentence hands it over only once every
other unit in it is known -- a conjunction, not a choice. Dijkstra over words
answers with the cheapest single neighbour and so undercounts: given `A`
behind a ten-minute video, `B` behind another, and `A B X` inside a third of
five minutes, it prices `X` at fifteen where the honest answer is
twenty-five. Only 129 of this corpus's 229,079 sentences carry a single unit,
which is where the graph reading would have been safe; the rest run to a
median of eight.

Knuth's 1977 generalisation is the fix, and it is Dijkstra's shape exactly:
settle the cheapest unsettled node, then relax what it completes. The
difference is that a hyperedge fires when its *last* prerequisite settles
rather than its first, so each sentence carries a count of what it is still
waiting for -- the same bookkeeping `reach.py` keeps, with an ordering on top.
It is correct for any *superior* cost function: monotone, and never less than
the arguments it combines. Both of the ones here qualify.

**What the two numbers mean, precisely.** Neither is the cost of the
schedule, because a video watched for one word teaches forty others at the
same time and a derivation cannot see that. What they bracket is one word,
learned on its own.

* `BOTTLENECK` takes the longest single video on the best derivation. Every
  way of reaching the word runs through some video at least this long, so it
  is a **lower bound** on the sitting the word costs you -- and a strictly
  better one than "the shortest video that says it", because it prices the
  chain in front of it too.
* `CHAIN` adds every video in the derivation up. That is a plan that
  certainly works, counting a shared video once per use, so it is an **upper
  bound**. The gap between the two is how much a word's cost depends on
  sharing, which is the part no derivation can settle.
"""
from __future__ import annotations

import heapq

# The two superior functions. Each takes a video's length and the costs of
# the prerequisites already settled, and returns what the word costs by that
# reading. Superior means monotone and >= every argument, which is what makes
# settling the cheapest node safe.
BOTTLENECK = "bottleneck"
CHAIN = "chain"


def _combine(how: str, minutes: float, parts: list[float]) -> float:
    if how == BOTTLENECK:
        return max([minutes, *parts])
    return minutes + sum(parts)


def effort(priced, known, how: str = BOTTLENECK, goals=None) -> dict:
    """unit -> what it costs to reach, for every unit reachable at all.

    `priced` is the corpus as (minutes, units) pairs -- one per sentence,
    carrying the length of whatever it was said in. `known` is free and
    settles at zero.

    `goals` is the study list, and leaving it out is a different question
    rather than a convenience. `reach.py` at `budget=0` learns only what is
    on the list for free; a word off it has to be bought, which is what
    makes `sowie` cost two hundred minutes. Without `goals` this settles
    anything that becomes the last unknown, list or not -- the
    stepping-stone reading `open_walk` uses. With it, the held one.

    Mixing them is not a small error. `hocken` settles at 44.6 minutes
    unrestricted, through a sentence whose other words include
    `mietwohnung`, which is off the list and unreachable; held to the list
    its only way in is 104.6. Two numbers from two different rules in one
    table read as a contradiction, which is how this was caught.
    """
    holds: dict = {}          # unit -> the sentences that say it
    rows = []
    for minutes, units in priced:
        if not units:
            continue
        index = len(rows)
        rows.append((float(minutes), tuple(units), len(units)))
        for unit in units:
            holds.setdefault(unit, []).append(index)

    left = [row[2] for row in rows]          # units of each not yet settled
    settled: dict = {}
    # Ties broken on a counter rather than on the unit: `Unit` is frozen and
    # hashable but not ordered, and heapq reaches for the next element of the
    # tuple the moment two costs match -- which the seed does at zero, every
    # time, so this is not an edge case but the first thing that happens.
    queue: list = [(0.0, n, unit)
                   for n, unit in enumerate(u for u in known if u in holds)]
    heapq.heapify(queue)
    tick = len(queue)

    def ready(index: int) -> None:
        """A sentence down to one unknown: offer it at what it now costs."""
        nonlocal tick
        minutes, units, _ = rows[index]
        rest = [settled[u] for u in units if u in settled]
        missing = [u for u in units if u not in settled]
        if len(missing) != 1:
            return
        if goals is not None and missing[0] not in goals:
            return              # off the list: not free, so not settled here
        value = _combine(how, minutes, rest)
        heapq.heappush(queue, (value, tick, missing[0]))
        tick += 1

    for unit in known:
        settled[unit] = 0.0
    for index, row in enumerate(rows):
        left[index] = sum(1 for u in row[1] if u not in settled)
        if left[index] == 1:
            ready(index)

    while queue:
        value, _, unit = heapq.heappop(queue)
        if unit in settled:
            continue                          # a cheaper way already settled it
        settled[unit] = value
        for index in holds.get(unit, ()):
            left[index] -= 1
            if left[index] == 1:
                ready(index)
    for unit in known:
        settled.setdefault(unit, 0.0)
    return settled
