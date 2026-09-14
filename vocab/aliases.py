"""One word, one unit.

The study list writes a noun with its article and a verb inside the frame it
takes — `die Schule`, `etw./jdn. (Akk) haben` — while the analyser also
yields the bare lemma, `schule` and `haben`. That is one word arriving twice,
and counting it twice makes a sentence look two words away when it is one.

Strict counting used to collapse the duplicate by *deleting* the bare form
wherever the list taught that word under another name. The deletion is not
conditional on the goal being anywhere nearby, which is where it goes wrong:
`die Technologie` is on the list, so the lemma `technologie` was struck out
of every sentence in the corpus, including the ones that never say
`die Technologie` and never teach it. Measured over the whole corpus, 31% of
sentences lost a word with nothing standing in for it, and 1,206 of 3,910
roadmap steps presented a sentence holding a word the reader had no way to
have learned. A plan that claims i+1 was quietly teaching i+2.

Renaming instead of deleting fixes both halves at once:

  the duplicate still collapses -- both names become the same unit
  the word is still there, so a sentence cannot look easier than it reads
  and it is the *goal* that is left, so the walk can actually teach it

The rename has to be applied to what the reader knows as well as to what a
sentence says. Vocabulary files give bare lemmas, so a reader who knows
`schule` must be credited with `die Schule` or every sentence saying it grows
an unknown that was never there.
"""
from __future__ import annotations

import re
from typing import Iterable

from vocab.entry import Unit

# What a study-list key writes besides the word it teaches.
#
# ROLES are the slots a pattern leaves for its arguments, and an article is
# how the list writes a noun. Neither is ever the word being taught.
ROLES = frozenset({"jdm", "jdn", "jds", "etw", "sich"})
ARTICLES = frozenset({"der", "die", "das", "den", "dem", "des",
                      "ein", "eine", "einer", "einem", "einen"})

# Prepositions are different: `für jdn./etw. sorgen` teaches `sorgen` and the
# preposition is the frame it arrives in -- but `für` is also a goal in its
# own right, and `der Dank` teaches a noun spelled like one. So these are
# stripped only when something else is left to name, which is why `heads`
# makes two passes instead of filtering once.
#
# Deliberately not `Application.PLACEHOLDERS`, which overlaps it. That set
# answers "is this vocabulary the list teaches"; this one answers "which word
# is this goal *about*". Sharing one list would mean either leaving 39 verbs
# unnamed by the goal that teaches them (`gelten`, `nennen`, `stimmen` --
# 7,150 uses) or striking common prepositions out of `covered_by`, which is
# what compound parts resolve against.
PREPOSITIONS = frozenset({
    "an", "auf", "in", "zu", "für", "gegen", "als", "über", "unter", "mit",
    "von", "nach", "bei", "um", "vor", "aus", "durch", "gegenüber", "ohne",
    "wegen", "zwischen", "seit", "trotz", "statt", "während", "bis", "dank",
})

# A role slot, written as the role followed by the case it takes: `etw.
# (Akk)`, `jdm. (Dat)`, `Name (Akk)`. Matched as a unit rather than by
# listing the roles, because `Name` is a role here and an ordinary noun in
# `der Name` -- listing it as frame cost the list its own word for "name".
# Only the four case markers count, so a goal glossed in parentheses keeps
# its head.
_ROLE = re.compile(r"[^\W\d_]+\.?\s*\((?:Akk|Dat|Gen|Nom)\)")

# Hyphenated words are one word: `die E-Mail` names `e-mail`, and splitting
# it left the goal named by nothing and blocked by its own bare form.
_WORD = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")


def heads(key: str) -> set[str]:
    """Every word this goal key names on its own, as written.

    `die Schule` names `Schule`; `etw./jdn. (Akk) haben` names `haben`;
    `jdm. (Dat) etw. (Akk) geben` names `geben`. A key naming two words at
    once names neither -- `etw. (Akk) / sich lassen scheiden` is a phrase
    rather than a word, and letting it stand in for `lassen` would hand a
    reader the verb on the strength of an idiom.

    Comma alternatives are taken one at a time, because the list uses them to
    write the *same* word twice: `gern, gerne` names both spellings, and read
    as one key it would name two words and so name nothing.
    """
    out: set[str] = set()
    for part in key.split(","):
        # Role slots go first, taking their case marker with them; then any
        # parentheses that are left, as whole groups, so a noun that happens
        # to spell a case marker survives -- `das Gen` against `(Gen)`.
        written = re.sub(r"\([^)]*\)", " ", _ROLE.sub(" ", part))
        words: list[str] = []
        for word in _WORD.findall(written):
            # Folded, because a key can say its own head twice --
            # `aus etw. / etw. (Akk) bestehen bestehen` is one verb.
            if (len(word) >= 2 and word.lower() not in ROLES | ARTICLES
                    and word.lower() not in {w.lower() for w in words}):
                words.append(word)
        if len(words) > 1:
            # Only now, and only because something else is left to name.
            words = [w for w in words if w.lower() not in PREPOSITIONS]
        if len(words) == 1:
            out.add(words[0])
    return out


class Aliases:
    """The study list's name for each word it teaches.

    Looked up by written case first and folded case second, which is the same
    order the old keep-rule compared in and for the same reason: lemma keys
    are lowercase except the nouns that share one with a verb, which keep a
    capital to say which they are. `Treffen` finds `das Treffen` exactly;
    `schule` finds `die Schule` only after folding, which is what lets a
    lowercase lemma reach a goal the list wrote with a capital.
    """

    def __init__(self, goals: Iterable[Unit]) -> None:
        exact: dict[str, Unit] = {}
        folded: dict[str, Unit] = {}
        # Sorted, so a word two goals both name resolves the same way on
        # every run. `Band` is `das Band`, `der Band` and `die Band`; one of
        # the three has to win and nothing in the list says which.
        for goal in sorted(goals, key=lambda u: (u.kind, u.key)):
            for word in heads(goal.key):
                exact.setdefault(word, goal)
                folded.setdefault(word.lower(), goal)
        self._exact = exact
        self._folded = folded

    def __len__(self) -> int:
        return len(self._folded)

    def of(self, unit: Unit) -> Unit:
        """This unit under the name the list teaches it by, or unchanged.

        Multi-word keys never match: `heads` yields single words, so a
        pattern unit can only be returned as itself.
        """
        return (self._exact.get(unit.key)
                or self._folded.get(unit.key.lower())
                or unit)
