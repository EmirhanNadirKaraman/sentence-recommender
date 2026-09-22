"""The bipartite index the greedy walk runs on.

Nothing is rescanned.  Rebuilding over a hundred thousand sentences after
every step would make the walk quadratic, so the index is built once and
maintained incrementally.  Learning a unit touches only the sentences
containing it, and each of those moves down one state:

  0 unknowns   readable — the goal, counted only
  1 unknown    the frontier; its single unknown is a candidate to teach next
  2 unknowns   the lookahead; learning either one turns the sentence into i+1

Both the candidate map and the lookahead are kept as memberships rather than
recomputed, which is the difference between a walk that takes a minute and one
that takes a moment: at 115k teachable sentences the frontier alone runs to
tens of thousands, and a set difference per sentence per step dominates
everything else.  (The figure was 258k while Tatoeba was imported; the
subtitle corpus alone holds 200,193 rows, 115,462 of them teachable.)
"""
from __future__ import annotations

from collections import defaultdict

from corpus.sentence import Sentence
from roadmap.known_set import KnownSet
from vocab.compounds import Compounds
from vocab.entry import Unit


class CorpusIndex:
    """Sentences, their unknown counts, and which sentences each unit appears in."""

    def __init__(self, sentences: list[Sentence], known: KnownSet,
                 compounds: Compounds | None = None) -> None:
        self._sentences = sentences
        # A snapshot, not the caller's object. The index learns as it walks,
        # and writing that back would silently redefine what the caller thinks
        # is known — which is how a measurement here once reported learning
        # more units than were ever unknown.
        self._units = set(known.units)
        self._by_unit: dict[Unit, set[int]] = defaultdict(set)
        for position, sentence in enumerate(sentences):
            for unit in sentence.units:
                self._by_unit[unit].add(position)

        # A compound whose parts are all known is already readable, so it is
        # known too -- `Krankenhaus` is not a word to teach someone who has
        # `krank` and `Haus`. Resolved against this corpus's own lemmas
        # because the file is written in plain lowercase and the analyser
        # keeps the capital that separates `Essen` from `essen`.
        #
        # Applied to the known set and never to the sentences: the compound
        # stays one unit, stays teachable, and no sentence loses a word it
        # actually says. So this can only make sentences readable earlier --
        # it cannot put a goal out of reach.
        # Resolved over what is known as well as what the corpus says: a
        # part can be a word the reader has and this corpus never uses, and
        # resolving against the corpus alone dropped exactly those entries --
        # which are the ones most likely to grant something.
        # `is None`, not `or`: an empty `Compounds` is falsy, so `or` threw
        # away a caller that deliberately passed one and read the file again.
        self._compounds = compounds if compounds is not None else Compounds.over(
            set(self._by_unit) | self._units)
        self._granted = self._compounds.derivable(self._units)
        self._units |= self._granted

        self._unknown = [len(s.units - self._units) for s in sentences]
        self._candidates: dict[Unit, set[int]] = defaultdict(set)
        # The same frontier, narrowed to the units a goal-driven walk may
        # actually teach. Empty and unused until `track_goals` asks for it.
        # Declared before the loop below, because `_register` maintains it.
        self._goals: frozenset[Unit] = frozenset()
        self._goal_candidates: dict[Unit, set[int]] = {}
        self._pending: dict[Unit, set[int]] = defaultdict(set)
        self._readable = 0
        for position, count in enumerate(self._unknown):
            if count == 0:
                self._readable += 1
            elif count <= 2:
                self._register(position, count)

    def __len__(self) -> int:
        return len(self._sentences)

    def sentence(self, position: int) -> Sentence:
        return self._sentences[position]

    def unknown_count(self, position: int) -> int:
        return self._unknown[position]

    @property
    def granted(self) -> frozenset[Unit]:
        """Units nobody has to learn, because their parts cover them.

        Counted separately from the taught ones so a plan can say so. Without
        it a compound granted free reads as a goal that was never reached,
        which is the reverse of what happened.
        """
        return frozenset(self._granted)

    @property
    def known(self) -> frozenset[Unit]:
        """What this index currently counts as known."""
        return frozenset(self._units)

    def known_units_of_kind(self, kind: str) -> set[Unit]:
        return {u for u in self._by_unit if u.kind == kind}

    @property
    def readable(self) -> int:
        """How many sentences have nothing unknown left in them."""
        return self._readable

    def candidates(self) -> dict[Unit, set[int]]:
        """Every unit that is the *only* unknown in at least one sentence.

        These are exactly the units learnable next: each turns the sentences
        listed against it from i+1 into fully readable.

        The sets are the index's own and must be treated as read-only. They
        used to be copied into lists on the way out, which at tens of
        thousands of frontier sentences cost a fifth of the walk — once per
        step, to hand back something the scorer only takes the length of.
        Emptied entries are dropped as they empty, so a caller may still see
        one and should skip it.
        """
        return self._candidates

    def track_goals(self, goals: frozenset[Unit]) -> None:
        """Keep a goal-only view of the frontier alongside the full one.

        A walk held to a list scans the frontier every step and throws most
        of it away: the frontier grows to 17,710 units by step 600 of the
        subtitle corpus while the goals among them level off around 3,000.
        Measured, that discarded scan is 2.01 ms a step — 7.8 s across a
        3,902-step walk, a quarter of it.

        Maintained, not recomputed. `goals & candidates.keys()` once a step
        would hash every unit on the frontier to build the answer, which is
        the cost being removed. Instead `_register` and `_drop` file a goal
        under both maps as it arrives and leaves.

        The two maps share their position sets — `_goal_candidates[u] is
        _candidates[u]` — so a sentence added to or removed from one is in
        both already. Only creating and deleting a key has to be mirrored.

        Called by `RoadmapBuilder` when it is held to goals, after any steps
        already taken have been learned, so the snapshot below is of the
        frontier as it now stands. One index serves one walk; handing the
        same index to a second builder with different goals would repoint the
        view and leave the first walk reading somebody else's.
        """
        self._goals = goals
        self._goal_candidates = {
            unit: positions for unit, positions in self._candidates.items()
            if unit in goals
        }

    def goal_candidates(self) -> dict[Unit, set[int]]:
        """`candidates()`, narrowed to the tracked goals.

        Empty unless `track_goals` has been called. Read-only, and emptied
        entries are dropped as they empty, exactly as `candidates` documents.
        """
        return self._goal_candidates

    def pairs(self) -> dict[Unit, set[int]]:
        """Every unit that is one of exactly *two* unknowns in some sentence.

        The lookahead, read as a frontier in its own right. `candidates` is
        what can be learned next on its own; this is what can be learned next
        if you are willing to take two words from one sentence, which is what
        the walk falls back on when nothing anywhere is one word away.

        Read-only, and emptied entries are dropped as they empty, exactly as
        `candidates` documents.
        """
        return self._pending

    def containing(self, unit: Unit) -> set[int]:
        """Every sentence with `unit` in it, readable or not.

        `candidates` gives only the sentences where `unit` is the sole
        unknown, which is what the walk scores on. A deck wants the rest too:
        the median unit is the only unknown in one or two sentences, and a
        deck of one cannot be stepped through.

        The set is the index's own and must be treated as read-only, like the
        ones `candidates` hands back. `get` rather than indexing, so asking
        about an absent unit does not mint an entry for it.
        """
        return self._by_unit.get(unit, set())

    def unlocks(self, unit: Unit) -> int:
        """Sentences that would drop from two unknowns to one — the lookahead.

        `get`, not indexing: this is asked about every candidate on every
        step, and a defaultdict would mint an empty set for each one and then
        iterate it forever after.
        """
        pending = self._pending.get(unit)
        return len(pending) if pending else 0

    def learn(self, unit: Unit) -> None:
        """Mark `unit` known and move every sentence containing it down a state.

        Learning something already known is a no-op rather than a second
        decrement. Without that guard a caller that forgets to check drives
        unknown counts below zero — silently, since nothing downstream
        inspects the sign — and the frontier stops meaning anything.
        """
        # A queue rather than recursion, and one unit carried all the way
        # through before the next is touched. Learning a part can complete a
        # compound, whose own sentences need the same pass -- but `_register`
        # reads `self._units` as it stands, so an interleaved second unit
        # would file sentences against a frontier that is halfway updated.
        queue = [unit]
        while queue:
            current = queue.pop()
            if current in self._units:
                continue
            self._units.add(current)
            granted = self._compounds.unlocked_by(current, self._units)
            self._granted.update(granted)
            queue.extend(granted)
            for position in self._by_unit[current]:
                count = self._unknown[position] - 1
                self._unknown[position] = count
                if count == 0:
                    self._drop(self._candidates, current, position)
                    self._readable += 1
                elif count == 1:
                    self._drop(self._pending, current, position)
                    self._register(position, 1, drop_from_pending=True)
                elif count == 2:
                    self._register(position, 2)

    def _register(self, position: int, count: int, drop_from_pending: bool = False) -> None:
        """File a sentence under whichever of its unknowns the walk needs.

        One unknown makes it a candidate for that unit; two put it in both
        units' lookahead.  `drop_from_pending` handles the 2 -> 1 move, where
        the surviving unknown must leave the lookahead as it enters the
        frontier.
        """
        for remaining in self._sentences[position].units - self._units:
            if count == 1:
                if drop_from_pending:
                    self._drop(self._pending, remaining, position)
                bucket = self._candidates[remaining]
                # A unit joins the frontier once and leaves it only by being
                # learned, so the goal view has to be told only when the
                # bucket is new. `not bucket` is a truth test on a set the
                # defaultdict has just made and costs no hash, which keeps
                # the goal lookup off the hot path.
                if not bucket and remaining in self._goals:
                    self._goal_candidates[remaining] = bucket
                bucket.add(position)
            else:
                self._pending[remaining].add(position)

    def _drop(self, mapping: dict, unit: Unit, position: int) -> None:
        """Remove a sentence, and the unit's entry with it once it is empty.

        Both maps are walked in full on every step. Left to grow they keep
        every unit ever seen on the frontier, so the walk gets slower the
        further it goes precisely because it is making progress.

        An instance method rather than a static one so the goal view empties
        with the frontier it mirrors. Discarding the position needs no help —
        the two maps hold the same set — but the key has to go from both, and
        putting that here means a future caller cannot forget it.
        """
        positions = mapping.get(unit)
        if positions is None:
            return
        positions.discard(position)
        if not positions:
            del mapping[unit]
            if mapping is self._candidates:
                self._goal_candidates.pop(unit, None)
