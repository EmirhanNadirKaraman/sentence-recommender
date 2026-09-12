"""What a corpus can eventually teach, and at what price in off-list words.

`_stranded` asks which goals the roadmap can never reach. It used to answer
by running the teaching walk to exhaustion and seeing what it missed, which
is more work than the question needs: the walk exists to choose a good
*order*, and reachability does not depend on order. Learning a word never
makes another word harder to reach, so whatever the walk would eventually
reach is a fixpoint, and every order arrives at the same one.

So the free part is a closure -- learn anything that is currently the only
unknown in some sentence, repeat -- which visits each sentence a constant
number of times instead of scoring thousands of candidates per step.

The part that is not free is teaching a word that is *not* on the list. Held
to the list, a goal with one ordinary word in front of it is out of reach and
that is the answer. Allowed to step off the list, the walk can clear almost
anything given enough words, so the question is only interesting with a price
attached: **how many words off your list are you willing to learn?**

That is what `budget` is, and it is the reason this replaces a step cap. The
page used to bound the walk at 5,000 steps so a page load could not hang --
a number about page loads, not about learning. Held, it never bound at all.
Unblocked, it bound every time and silently decided the answer: 46 goals
reported out of reach where exhaustion gives 25, the difference being 48,419
off-list words the walk would have had to teach. A budget says the same kind
of thing in a sentence a reader can act on: *out of reach unless you learn up
to N words that are not on your list.*

`budget=0` is exactly the held reading, and is checked against the walk.
"""
from __future__ import annotations

from collections import defaultdict


def reachable(sentences, known, goals, budget: int = 0) -> set:
    """Every unit reachable from `known`, teaching at most `budget` non-goals.

    Goals are free and unlimited: they are what the roadmap exists to teach.
    Anything else is bought out of `budget`, most useful first -- and unlike
    the free part, that order matters, which is why it is chosen rather than
    taken as it comes.
    """
    reached = set(known)
    holds = defaultdict(list)        # unit -> indices of sentences saying it
    units = [s.units for s in sentences]
    left = []                        # per sentence: how many unknowns remain
    for index, sentence_units in enumerate(units):
        unknown = 0
        for unit in sentence_units:
            holds[unit].append(index)
            if unit not in reached:
                unknown += 1
        left.append(unknown)

    def single(index):
        """The one unknown in a sentence, or None if it no longer has one."""
        if left[index] != 1:
            return None
        return next((u for u in units[index] if u not in reached), None)

    def learn(unit) -> None:
        reached.add(unit)
        for index in holds[unit]:
            left[index] -= 1
            if left[index] == 1:
                ready.append(index)

    ready = [i for i, n in enumerate(left) if n == 1]
    # Sentences whose one remaining unknown is *not* a goal. They are the
    # candidates the budget can buy, and holding them here is what keeps this
    # cheap: the first version rescanned all 259,264 sentences on every
    # budget step to find them again, twice, which cost more than the walk it
    # replaced.
    stalled: list[int] = []
    while True:
        # Free: every goal that is currently the only unknown somewhere.
        # Taken in whatever order they surface, which is safe precisely
        # because nothing here is scarce.
        while ready:
            index = ready.pop()
            unit = single(index)
            if unit is None:
                continue                  # already resolved by something else
            if unit in goals:
                learn(unit)               # may append to `ready`
            else:
                stalled.append(index)
        if budget <= 0:
            return reached

        # Scarce: one off-list word, the one that makes the most sentences
        # readable right now. Counted over sentences where it is the only
        # unknown, which is what "buys" anything -- a word appearing beside
        # three other unknowns unlocks nothing yet.
        gain: defaultdict = defaultdict(int)
        for index in stalled:
            unit = single(index)
            if unit is not None and unit not in goals:
                gain[unit] += 1
        if not gain:
            return reached
        # Ties broken on the key so the answer does not depend on dict order.
        best = max(gain, key=lambda u: (gain[u], u.key))
        learn(best)                       # may append to `ready`
        budget -= 1
        # Re-examine the stalled ones: buying that word may have resolved
        # them. `learn` has already queued anything newly down to one unknown,
        # so both lists have to survive here -- overwriting `ready` with
        # `stalled` dropped exactly those.
        ready.extend(stalled)
        stalled = []
