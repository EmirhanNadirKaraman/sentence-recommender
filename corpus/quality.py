"""What makes an example sentence worth showing.

Separate from `filter.py` on purpose. The filter decides what belongs in the
corpus at all and runs before analysis, so it sees only text, and what it
rejects is gone. This ranks the survivors — a sentence can be perfectly good
German and still be a poor thing to learn a word from — and rejects nothing:
a word whose only example is four words long is still taught with it.

Lives here rather than in `experiments/` because the roadmap picks by it. The
experiments measure the same function the reader sees, so the history in
`experiment_results/` keeps describing what is actually being shown.
"""
from __future__ import annotations

import re

# Bump when the scale changes. Recorded against every experiment row, because
# a mean score from one definition cannot be compared with a mean from
# another — the history would show quality "improving" when only the ruler
# moved. It is also part of `current_stamp`, so a bump tells every stored
# roadmap that the corpus it was walked over is not the one here now.
#
# 4: the band's floor from eight words to five.
# 5: the band's ceiling from fifteen to twenty-five.
# 6: a sentence whose first letter is lowercase is a fragment, and so is one
#    opening with punctuation that cannot begin a sentence, and so is one
#    with an ellipsis anywhere in it.
# 7: a pronoun with nothing in its own sentence to attach to is charged for,
#    once per pronoun.
# 8: a sentence with an ellipsis in it is refused rather than charged.
VERSION = 8

# Speech, not prose. Long enough to show the word doing something, short
# enough to hold in mind while reading it.
#
# The floor was eight, and eight was measured against prose intuition rather
# than against this corpus. Subtitle German peaks at five words a line and
# falls away from there monotonically, so the bar sat in the middle of the
# mass: it admitted 33% of 169,155 sentences, and the three lengths it cut
# off — five, six and seven — hold 75,171 of them between them.
#
# It also stranded goals the corpus does say. Of the 66 the b1 walk cannot
# reach, 24 have a sentence and every one of those sentences was refused for
# length alone: `Die Arbeitslosigkeit ist hoch und steigt weiter.` is seven
# words. Five is where `filter.py` already stops, so this admits everything
# that survived it and draws no second line of its own.
#
# Nothing is preferred for being short. `score` still peaks at 9-11 and
# tapers both ways, so a five-word sentence wins only where there is no
# longer one — which is the stranded case this exists for.
#
# The ceiling moved for the same reason and on the same evidence. At fifteen
# it refused every sentence there was for 63 goals the corpus does say — 74
# of those sentences were merely long, none was short — and raising it to
# twenty-five gives 52 of the 63 an example for 9% more of the corpus.
# Twenty-five rather than a rounder number because nothing here is longer:
# `filter.py` stops first, so this again draws no second line of its own.
#
# This is the asymmetry noted below, taken seriously. Falling short means
# missing context and teaching less; running long means being harder to
# read. The second is the cheaper error, and `score` charges for it anyway.
BAND = (5, 25)          # the binary bar: is this worth showing at all
IDEAL = (9, 11)         # equally good, and the tie is broken on merit

# Deliberately asymmetric, where it used to be so by accident: a sentence
# below the peak is missing context and teaches less, while one above it is
# merely harder to read. Falling short costs more per word than running long.
SHORT_PENALTY = 0.08
LONG_PENALTY = 0.06

INTERNAL_BREAK = re.compile(r"[.!?]\s+\S")
# The first letter, past any quote, bracket or ellipsis it opens with. German
# capitalises the first word of a sentence, so a lowercase one is the middle
# of something — `das hab' ich denen bis heute auch nicht gesagt.` is the
# tail of a sentence whose beginning went to another subtitle line. That is
# the same fault the length floor exists for, stated the other way round:
# missing context, and less taught.
#
# Checked as the first *letter* rather than the first character so a sentence
# opening with `"`, `(` or `...` is judged on its word, and so a number or a
# noun is not mistaken for one — `islower` is false for both.
FIRST_LETTER = re.compile(r"[^\W\d_]")

# Punctuation that cannot begin a sentence. Opening quotes and brackets can
# and do — 311 of the 376 sentences in this corpus that start with a mark
# start with a quote, and `"Schaun mer mol, dann seng ma scho".` is a whole
# sentence that happens to open in speech. Penalising the class would demote
# all of them to catch the rest.
#
# What is left is punctuation that only ever continues something: an ellipsis
# where the first half went to the previous subtitle line, a closing bracket
# with no opening one, a dash or comma dangling off a cut. Most of these are
# already caught by the lowercase rule above — `...weil mir ist das nie
# passiert` fails on its `w` — and this is for the ones that are not, like a
# tail that happens to resume at a capitalised noun.
CANNOT_OPEN = frozenset(".…,;:)]}»-–—")

# An ellipsis anywhere says the thought is not finished: a speaker trailing
# off, correcting themselves mid-word, or a line cut where the subtitle was.
# `Aber du bist… du bist schon in Italien gewesen` is a stutter written down,
# and `das kann ich eigentlich nicht so genau...` stops before it says what.
#
# Charged rather than refused, like everything here. Of the 42 steps in the
# beginner plan taught by one, every single one had an ellipsis-free
# candidate of its own — so this costs no coverage at all — but the rule has
# to hold for the word where it would, and that word still gets taught.
ELLIPSIS = re.compile(r"\.\.\.|…")

# There is no terminal-punctuation rule here, and the omission is deliberate.
# One was drafted: every sentence in the corpus already ends in `.`, `!` or
# `?` — 0 of 11,398 examples in the beginner plan do not — because
# `filter.py` and the aligner settle it upstream. A rule here would cost a
# regex per sentence to discover something already guaranteed.
FRAGMENT_PENALTY = 0.7

# A pronoun is only as good as what it points at. `Warum hast du ihm nicht
# gesagt, dass Riton Albana ist?` is perfectly clear -- `ihm` is a person the
# sentence goes on to name -- while `Und jetzt erwartet der von ihnen, dass
# sie ihm glauben.` is three pronouns and no one to hang them on. The
# difference is not how many pronouns there are, which is why counting them
# was useless: 53.6% of the roadmap has one and German simply talks that way.
#
# What separates the two is whether the sentence contains its own antecedent,
# and German orthography answers that almost for free. Nouns are capitalised,
# so a capitalised word earlier in the sentence is something a later pronoun
# can refer to. Measured over the 3,902 beginner steps this flags 714 (18.3%),
# and 689 of those steps have a pronoun-free candidate already among the
# examples the picker kept -- so it is nearly all reordering.
#
# First and second person are deliberately absent. `ich` and `du` are fixed by
# the act of speaking: a sentence with `ich` in it is about whoever said it,
# and needs no earlier line to be understood.
THIRD_PERSON = frozenset(("er", "ihn", "ihm", "sie", "ihr", "ihnen", "es"))

# `das` and its relatives do a pronoun's work as often as an article's, and
# only the pronoun reading points outside the sentence. Nouns being
# capitalised settles this one too: an article is followed by its noun, across
# an adjective or two at most, so a determiner with no capitalised word behind
# it is standing in for something that was said earlier.
DETERMINER = frozenset(("das", "dies", "die", "der", "den", "dem", "denen",
                        "deren", "dessen"))
LOOKAHEAD = 3           # how far past a determiner its noun may sit

# Two readings that look like context-dependence and are not. Both were found
# by reading what the rule flagged: `Wie ihr wisst, ist es schwierig, eine
# Sprache zu lernen.` was charged twice and is completely self-contained.
#
#   `ihr` before a lowercase verb is "you", the second person plural, and is
#   fixed by the act of speaking exactly as `du` is. Before a capitalised word
#   it is the possessive, whose noun is right there.
#
#   `es` before a `dass`/`ob` clause or a `zu`-infinitive is a placeholder
#   holding the subject's seat for what comes after it, in the same sentence.
#   So are the fixed frames `es gibt` and the weather verbs.
#
# Together these were 86 of the 800 the rule first flagged -- more than a
# tenth of it, all of them good sentences.
FORWARD = frozenset(("dass", "ob"))
ES_FRAME = frozenset(("gibt", "geht", "regnet", "schneit"))
# `zu` marks an infinitive only when an infinitive follows it. In `Es war
# wirklich viel zu teuer.` it means "too", and reading it as the other `zu`
# excused a pronoun that genuinely points outside the sentence. German
# infinitives end in `-en`; the determiners that also do are listed out,
# because `zu den Gästen` is the same shape and is not an infinitive either.
NOT_INFINITIVE = frozenset((
    "den", "dem", "denen", "einen", "einem", "diesen", "jenen", "allen",
    "vielen", "beiden", "anderen", "seinen", "ihren", "meinen", "deinen",
    "unseren", "euren", "keinen", "welchen", "solchen",
))


def _zu_infinitive(words: list[str]) -> bool:
    """Is there a `zu` here with an infinitive behind it?"""
    for index, word in enumerate(words[:-1]):
        behind = words[index + 1]
        if word == "zu" and behind.endswith("en") \
                and behind not in NOT_INFINITIVE:
            return True
    return False

# Charged per pronoun, so two unresolved ones cost more than one. The size is
# about two words off the ideal length, which is the trade it is meant to
# make: a clean seven-word sentence should beat a nine-word one that opens on
# an `er` nobody has met.
UNBOUND_PENALTY = 0.85

WORD = re.compile(r"[^\W\d_]+")


def _noun_at(tokens: list[str]) -> int | None:
    """Where the first word that could be an antecedent stands.

    A capitalised token, ignoring the first position -- every German sentence
    capitalises its opening word, so position zero says nothing.
    """
    for index in range(1, len(tokens)):
        if tokens[index][:1].isupper():
            return index
    return None


def unbound(text: str) -> int:
    """How many pronouns in `text` have nothing inside it to attach to."""
    tokens = WORD.findall(text)
    if not tokens:
        return 0
    lowered = [token.lower() for token in tokens]
    noun = _noun_at(tokens)
    count = 0
    for index, word in enumerate(lowered):
        if noun is not None and noun < index:
            break                       # an antecedent stands before the rest
        if word == "ihr":
            after = tokens[index + 1] if index + 1 < len(tokens) else ""
            if after[:1].isupper() or after.endswith("t"):
                continue                # "ihr Vater", or "ihr wisst"
        elif word == "es":
            rest = lowered[index + 1:]
            if set(rest) & FORWARD or _zu_infinitive(rest):
                continue                # holding a seat for what follows
            if rest[:1] and rest[0] in ES_FRAME:
                continue                # `es gibt`, `es regnet`
        elif word in DETERMINER:
            behind = tokens[index + 1:index + 1 + LOOKAHEAD]
            if any(token[:1].isupper() for token in behind):
                continue                # an article, with its noun behind it
        elif word not in THIRD_PERSON:
            continue
        count += 1
    return count


def well_formed(text: str) -> bool:
    """One whole sentence, of a length worth reading.

    An ellipsis is refused outright here, where everything else in this file
    is merely charged for. A thought that does not finish cannot be understood
    on its own, and being understood on its own is the entire promise of an
    i+1 sentence -- so `das kann ich eigentlich nicht so genau...` is not a
    poor example of the word it teaches, it is not an example of it.

    Refusing rather than charging was measured first, because refusing is how
    coverage gets lost: 2,170 of the 274,947 well-formed sentences carry one,
    0.8%, and every one of the 4,002 goals is said in at least one sentence
    without. So this costs no word its only chance of being taught. The
    penalty in `score` stays for the builds that do not pass through this
    gate, where charging is still the right treatment.
    """
    words = len(text.split())
    return (BAND[0] <= words <= BAND[1]
            and not INTERNAL_BREAK.search(text)
            and not ELLIPSIS.search(text))


def variety(text: str) -> float:
    """Share of the words that are distinct.

    The tie-break, and not an arbitrary one: `Ja, ja, ja, das ist gut genug`
    and a sentence of eight different words score the same on length, and the
    second teaches more. Chosen over character length, which was the previous
    tie-break and simply reintroduced the bias the peak exists to remove.
    """
    words = [w.lower() for w in text.split()]
    return len(set(words)) / len(words) if words else 0.0


def score(text: str) -> float:
    """0..1, higher is better. A narrow plateau, tie broken on merit.

    Two earlier shapes were wrong in opposite directions. A wide plateau of
    eight to twelve, with the tie broken on character length, put forty-seven
    percent of the roadmap on exactly eight words — the shortest-wins bias
    relocated rather than removed. A single peak at ten was worse: fifty-eight
    percent landed on exactly ten, because with thirteen candidates a step
    there is nearly always one of the single best length, so it wins every
    time. A peak concentrates harder than a plateau.

    Three lengths score alike, and `variety` decides between them, which
    spreads the choice on something that is actually a quality rather than on
    a proxy for length.

    Tapered rather than cut: a word whose only example is six words long is
    still taught with it, just ranked below a better one.
    """
    words = len(text.split())
    if words < IDEAL[0]:
        length = max(0.0, 1 - (IDEAL[0] - words) * SHORT_PENALTY)
    elif words > IDEAL[1]:
        length = max(0.0, 1 - (words - IDEAL[1]) * LONG_PENALTY)
    else:
        length = 1.0
    # Ellipses out of the way first: `bist... du` is one thought trailing
    # off, not two sentences on one line, and `[.!?]\s+\S` cannot tell the
    # difference. Left in, the two spellings of the same fault scored two to
    # one — `bist... du` charged for a break as well as for the ellipsis,
    # `bist… du` only for the ellipsis.
    if INTERNAL_BREAK.search(ELLIPSIS.sub(" ", text)):
        length *= 0.5
    opening = text.lstrip()[:1]
    first = FIRST_LETTER.search(text)
    if opening in CANNOT_OPEN or (first is not None
                                  and first.group().islower()):
        length *= FRAGMENT_PENALTY
    if ELLIPSIS.search(text):
        length *= FRAGMENT_PENALTY
    # Last, and multiplicative like the rest: a sentence can be a fragment
    # *and* open on an unresolved pronoun, and it should be charged for both.
    length *= UNBOUND_PENALTY ** unbound(text)
    return length
