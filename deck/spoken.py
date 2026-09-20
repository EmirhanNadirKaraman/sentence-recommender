"""A study-list key as something a voice can say, or a model can gloss.

The list writes its keys for a matcher: `jdm. (Dat) passieren`, `etw./jdn.
(Akk) lassen`, `mit jdm. / über etw./jdn. sprechen`. Those are exact about
which slot takes which case, and unspeakable -- read out they become letters,
spoken case labels and abbreviations. 72% of the plan's steps are patterns,
so this is most of the deck rather than an edge of it.

A verb's key is spoken as the verb, not as its frame. The frame was kept
at first — `nach etwas aussehen` teaches the preposition, which is the thing
a learner gets wrong — and that held until experiment 04 read the sentences:
the frames were never chosen. `build-study-list` took each verb's one
blueprint from `final_result.txt`, and that blueprint is one use among
several, often a rare one. `jdm. (Dat) stehen` is *to suit someone*, one or
two rows in a hundred of `stehen`; not one of three `aussehen` sentences
carried `nach`; `jdm. etw. bedeuten` never once meant *to someone*. A card
titled by the frame taught a sense its examples did not show. Decided
2026-09-20 (TODO #26): the goal is the verb, and a use that a learner
cannot get from the verb — `es gibt`, `auf jdn. stehen` — is a unit of its
own with its own line. A reflexive keeps its `sich`, since `sich erinnern`
and `erinnern` are two words. Everything else is expanded, not cut:

    jdm. (Dat) passieren               -> passieren
    an jdn./etw. sich erinnern         -> sich erinnern
    etw. (Akk) / sich lassen scheiden  -> sich lassen scheiden   (no one head)
    die Zeit                           -> die Zeit
    gern, gerne                        -> gern

Articles stay, because `die Zeit` is how the gender is learned and `Zeit`
alone throws it away.
"""
from __future__ import annotations

import re

from vocab.aliases import heads
from vocab.goal_list import CASE_FRAME

# What the list's abbreviations stand for, written out.
SPOKEN = {
    "jdm": "jemandem", "jdn": "jemanden", "jds": "jemandes", "jd": "jemand",
    "etw": "etwas",
}

# Anything in brackets is annotation -- a case, a sense hint like `(Zeit)`,
# a pair like `(Akk/Dat)`. None of it is said aloud, so all of it goes. Note
# this differs from `vocab.aliases`, which keeps a bracketed word that turns
# out to be a noun: here nothing bracketed is ever spoken.
_ASIDE = re.compile(r"\([^)]*\)")
# A run of alternatives for one slot, with or without the trailing dots the
# list writes on its abbreviations: `etw./jdn.`, `auf/über`, `für/gegen`.
_ALTERNATIVES = re.compile(r"(?<![\w.])([\w.]+)(?:/[\w.]+)+")
# A slash with space around it separates whole frames that share a verb;
# a slash without space separates two fillers for one slot.
_BRANCH = " / "


def _expand(part: str) -> str:
    """One frame, with its annotations gone and its shorthand written out."""
    # Alternatives first, so `(Akk/Dat)` has collapsed before the brackets
    # are stripped and `auf/über` before anything looks at the words.
    text = _ALTERNATIVES.sub(r"\1", part)
    text = _ASIDE.sub(" ", text).replace("+", " ")
    words = []
    for word in text.split():
        bare = word.rstrip(".").lower()
        words.append(SPOKEN[bare] if bare in SPOKEN else word)
    said = re.sub(r"\s+", " ", " ".join(words)).strip()
    # German puts the reflexive early: the list writes `für etw. sich
    # schämen` to keep the slots in order, but nobody says it that way.
    # Moved rather than left, because the deck is read aloud and a learner
    # repeating what they hear should be repeating German.
    parts = said.split()
    if "sich" in parts[1:]:
        parts.remove("sich")
        said = " ".join(["sich", *parts])
    return said


def spoken(key: str) -> str:
    """The key as German a voice can read and a model can be asked about.

    A key with ` / ` in it offers two frames for one verb, and the verb sits
    at the end of the last of them -- `mit jdm. / über etw./jdn. sprechen` is
    "mit jdm. sprechen" or "über etw. sprechen". Splitting and taking the
    first branch alone would lose the verb, so the first frame is joined to
    the head word instead. `heads` already knows how to find that head; where
    it finds none -- an idiom naming two words at once, like `etw. (Akk) /
    sich lassen scheiden` -- the last branch is spoken whole, which is the
    one reading guaranteed to contain the verb.
    """
    # A comma offers the same word spelled two ways. One of them is enough.
    first = key.split(",")[0].strip()
    # A verb frame is spoken as its verb -- see the module docstring for
    # why. `heads` finds the verb; where it finds none, or more than one,
    # the key is an idiom and is spoken whole below.
    if CASE_FRAME.search(first):
        found = heads(first)
        if len(found) == 1:
            verb = next(iter(found))
            return f"sich {verb}" if "sich" in first.split() else verb
    if _BRANCH not in first:
        return _expand(first)

    branches = [b.strip() for b in first.split(_BRANCH)]
    found = heads(first)
    frame = _expand(branches[0])
    if len(found) == 1 and frame:
        return f"{frame} {next(iter(found))}".strip()
    return _expand(branches[-1])
