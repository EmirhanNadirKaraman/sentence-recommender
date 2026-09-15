"""A study-list key as something a voice can say, or a model can gloss.

The list writes its keys for a matcher: `jdm. (Dat) passieren`, `etw./jdn.
(Akk) lassen`, `mit jdm. / über etw./jdn. sprechen`. Those are exact about
which slot takes which case, and unspeakable -- read out they become letters,
spoken case labels and abbreviations. 72% of the plan's steps are patterns,
so this is most of the deck rather than an edge of it.

The frame is worth keeping rather than discarding. `nach etwas aussehen`
teaches the preposition the verb takes, which is the thing a learner actually
gets wrong; `aussehen` alone teaches half of it. So the abbreviations are
expanded into the words they stand for instead of being cut:

    jdm. (Dat) passieren               -> jemandem passieren
    etw./jdn. (Akk) lassen             -> etwas lassen
    mit jdm. / über etw./jdn. sprechen -> mit jemandem sprechen
    die Zeit                           -> die Zeit
    gern, gerne                        -> gern

Articles stay, because `die Zeit` is how the gender is learned and `Zeit`
alone throws it away.
"""
from __future__ import annotations

import re

from vocab.aliases import heads

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
    if _BRANCH not in first:
        return _expand(first)

    branches = [b.strip() for b in first.split(_BRANCH)]
    found = heads(first)
    frame = _expand(branches[0])
    if len(found) == 1 and frame:
        return f"{frame} {next(iter(found))}".strip()
    return _expand(branches[-1])
