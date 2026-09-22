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
        # Units are numbered, and the walk runs on the numbers.
        #
        # Every map below is asked about a unit millions of times a walk, and
        # a `Unit` answers with a Python-level `__hash__` however cheap that
        # method is made — 12.1M calls in 800 steps, and a dict lookup either
        # side of each. Integers hash in C. Measured on this corpus, the set
        # difference in `_register` alone is 2.2x faster interned.
        #
        # The numbering is an implementation detail and stops at the door:
        # `candidates`, `pairs`, `containing`, `known` and `granted` all speak
        # `Unit`, because everything outside this file does. Only
        # `RoadmapBuilder`, which is the thing doing it millions of times,
        # reaches for the `_ids` variants.
        self._id: dict[Unit, int] = {}
        self._unit: list[Unit] = []
        self._by_unit: dict[int, set[int]] = defaultdict(set)
        # One frozenset of ids per sentence, built once. This is what makes
        # the difference in `_register` an integer operation rather than a
        # conversion pretending to be one.
        self._sentence_units: list[frozenset[int]] = []
        for position, sentence in enumerate(sentences):
            here = set()
            for unit in sentence.units:
                identifier = self._intern(unit)
                here.add(identifier)
                self._by_unit[identifier].add(position)
            self._sentence_units.append(frozenset(here))

        # A snapshot, not the caller's object. The index learns as it walks,
        # and writing that back would silently redefine what the caller thinks
        # is known — which is how a measurement here once reported learning
        # more units than were ever unknown.
        #
        # Kept twice over: `Compounds` speaks `Unit` and so does everything
        # that asks what is known, while the walk wants the numbers. The two
        # are written together in `learn` and nowhere else.
        self._units = set(known.units)

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
        # `self._unit` and not `self._by_unit`: the map is keyed by number
        # now, and `Compounds` is asked which *words* this corpus holds.
        self._compounds = compounds if compounds is not None else Compounds.over(
            set(self._unit) | self._units)
        self._granted = self._compounds.derivable(self._units)
        self._units |= self._granted
        self._known: set[int] = {self._intern(u) for u in self._units}

        self._unknown = [len(su - self._known) for su in self._sentence_units]
        self._candidates: dict[int, set[int]] = defaultdict(set)
        # The same frontier, narrowed to the units a goal-driven walk may
        # actually teach. Empty and unused until `track_goals` asks for it.
        # Declared before the loop below, because `_register` maintains it.
        self._goals: frozenset[int] = frozenset()
        self._goal_candidates: dict[int, set[int]] = {}
        self._pending: dict[int, set[int]] = defaultdict(set)
        self._readable = 0
        for position, count in enumerate(self._unknown):
            if count == 0:
                self._readable += 1
            elif count <= 2:
                self._register(position, count)

    def _intern(self, unit: Unit) -> int:
        """This unit's number, assigning one if it has never been seen.

        `setdefault` would build the fallback on every call; this pays only
        when the unit is new, which over a corpus is once in a few dozen.
        """
        identifier = self._id.get(unit)
        if identifier is None:
            identifier = self._id[unit] = len(self._unit)
            self._unit.append(unit)
        return identifier

    def unit_of(self, identifier: int) -> Unit:
        """The unit a number stands for."""
        return self._unit[identifier]

    def id_of(self, unit: Unit) -> int:
        """The number a unit is filed under, or -1 for one this corpus never
        says. -1 rather than None or a fresh id: callers use it to test
        membership of maps keyed by number, and a unit that is not here
        cannot be in any of them."""
        return self._id.get(unit, -1)

    def numbered(self) -> int:
        """How many distinct units have a number — the width any array a
        caller builds alongside this index has to have."""
        return len(self._unit)

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
        return {u for u in (self._unit[i] for i in self._by_unit)
                if u.kind == kind}

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
        return {self._unit[i]: p for i, p in self._candidates.items()}

    def candidate_ids(self) -> dict[int, set[int]]:
        """`candidates`, by number and without the translation.

        The walk reads this once a step over a frontier of thousands; naming
        every unit on the way past is most of what the numbering removes.
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
        # Goals this corpus never says have no number and can never reach
        # the frontier, so they are simply not in the set.
        self._goals = frozenset(
            i for i in (self._id.get(u, -1) for u in goals) if i >= 0)
        self._goal_candidates = {
            identifier: positions
            for identifier, positions in self._candidates.items()
            if identifier in self._goals
        }

    def goal_candidates(self) -> dict[Unit, set[int]]:
        """`candidates()`, narrowed to the tracked goals.

        Empty unless `track_goals` has been called. Read-only, and emptied
        entries are dropped as they empty, exactly as `candidates` documents.
        """
        return {self._unit[i]: p for i, p in self._goal_candidates.items()}

    def goal_candidate_ids(self) -> dict[int, set[int]]:
        """`goal_candidates`, by number. The walk's innermost loop."""
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
        return {self._unit[i]: p for i, p in self._pending.items()}

    def pending_ids(self) -> dict[int, set[int]]:
        """`pairs`, by number."""
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
        return self._by_unit.get(self._id.get(unit, -1), set())

    def unlocks(self, unit: Unit) -> int:
        """Sentences that would drop from two unknowns to one — the lookahead.

        `get`, not indexing: this is asked about every candidate on every
        step, and a defaultdict would mint an empty set for each one and then
        iterate it forever after.
        """
        return self.unlocks_id(self._id.get(unit, -1))

    def unlocks_id(self, identifier: int) -> int:
        """`unlocks`, by number — asked once per candidate per step."""
        pending = self._pending.get(identifier)
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
        # The queue carries units rather than numbers because `Compounds`
        # speaks units, and it is the thing deciding what a part unlocks.
        queue = [unit]
        while queue:
            current = queue.pop()
            if current in self._units:
                continue
            self._units.add(current)
            identifier = self._intern(current)
            self._known.add(identifier)
            granted = self._compounds.unlocked_by(current, self._units)
            self._granted.update(granted)
            queue.extend(granted)
            for position in self._by_unit[identifier]:
                count = self._unknown[position] - 1
                self._unknown[position] = count
                if count == 0:
                    self._drop(self._candidates, identifier, position)
                    self._readable += 1
                elif count == 1:
                    self._drop(self._pending, identifier, position)
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
        for remaining in self._sentence_units[position] - self._known:
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

    def _drop(self, mapping: dict, identifier: int, position: int) -> None:
        """Remove a sentence, and the unit's entry with it once it is empty.

        Both maps are walked in full on every step. Left to grow they keep
        every unit ever seen on the frontier, so the walk gets slower the
        further it goes precisely because it is making progress.

        An instance method rather than a static one so the goal view empties
        with the frontier it mirrors. Discarding the position needs no help —
        the two maps hold the same set — but the key has to go from both, and
        putting that here means a future caller cannot forget it.
        """
        positions = mapping.get(identifier)
        if positions is None:
            return
        positions.discard(position)
        if not positions:
            del mapping[identifier]
            if mapping is self._candidates:
                self._goal_candidates.pop(identifier, None)
