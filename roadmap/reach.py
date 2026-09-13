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

from vocab.compounds import Compounds


def reachable(sentences, known, goals, budget: int = 0,
              on_buy=None, compounds: Compounds | None = None) -> set:
    """Every unit reachable from `known`, teaching at most `budget` non-goals.

    Goals are free and unlimited: they are what the roadmap exists to teach.
    Anything else is bought out of `budget`, most useful first -- and unlike
    the free part, that order matters, which is why it is chosen rather than
    taken as it comes.

    `on_buy(unit, spent, freed)` is called for each off-list word bought, in
    the order they are bought, with the goals that word set loose. That is
    the answer to "what must I learn from outside my list, and for what" --
    one run at a large budget gives the whole curve, where asking the
    question once per budget value would rerun the closure every time.
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

    # A compound whose parts are all known needs no teaching of its own. It
    # is applied here as well as in the walk, because this function has its
    # own propagation loop and shares none of the walk's bookkeeping -- left
    # out, the page would report goals stranded that the walk reaches.
    # `is None`, not `or`: an empty `Compounds` is falsy, and `or` would
    # quietly read the file over a caller that meant to disable this.
    if compounds is None:
        compounds = Compounds.over(set(holds) | reached)
    granted = compounds.derivable(reached)

    if granted:
        reached |= granted
        for index, sentence_units in enumerate(units):
            left[index] = sum(1 for u in sentence_units if u not in reached)

    def single(index):
        """The one unknown in a sentence, or None if it no longer has one."""
        if left[index] != 1:
            return None
        return next((u for u in units[index] if u not in reached), None)

    def learn(unit) -> None:
        """Learn one unit, and anything its parts now cover.

        Carried one unit at a time to exhaustion rather than recursively:
        `holds[unit]` is being iterated while `left` is written, so a nested
        call would mutate the counts under the loop it is nested in.
        """
        queue = [unit]
        while queue:
            current = queue.pop()
            if current in reached:
                continue
            reached.add(current)
            queue.extend(compounds.unlocked_by(current, reached))
            for index in holds[current]:
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
        before = reached & goals
        learn(best)                       # may append to `ready`
        budget -= 1
        if on_buy is not None:
            # Everything the free closure reached on the back of that one
            # purchase, which is what makes it worth its price.
            while ready:
                index = ready.pop()
                unit = single(index)
                if unit is None:
                    continue
                if unit in goals:
                    learn(unit)
                else:
                    stalled.append(index)
            on_buy(best, len(reached & goals) - len(before),
                   (reached & goals) - before)
        # Re-examine the stalled ones: buying that word may have resolved
        # them. `learn` has already queued anything newly down to one unknown,
        # so both lists have to survive here -- overwriting `ready` with
        # `stalled` dropped exactly those.
        ready.extend(stalled)
        stalled = []
