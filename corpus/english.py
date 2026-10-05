"""English: what a sentence holds, for a reader learning English.

German needs most of `corpus.analyzer`. Its parser cannot be trusted on the
capital at the start of a sentence, its verbs come apart in the middle of a
clause, and a corpus-wide vote has to repair the lemmas it gets wrong.
English needs little of that. Its capitals mean what they say, its verbs stay
in one piece, and spaCy's English lemmatiser is a rule table over a
part-of-speech tag that is right far more often than the German one.

What English has instead is the phrasal verb. `give up` is not `give` and
`up`; it is a third word, and a learner who knows both halves still does not
know it. So beside the lemmas, a sentence yields the expressions it says --
read from `data/en/expressions.txt`, in the format German's file uses:

    give up                       found by its words, in order, with up to
                                  two others between them: `gave it up`
    take sth into account         `sth`, `sb`, `one's`... stand for a phrase
    in spite of\tin spite of      a pattern after a tab: words in a row,
                                  `[x]` optional, `*` any one word or none
    rely on\trely :: on           a verb and the words that hang from it,
                                  anywhere in its clause: `relied heavily on`

An expression is a unit only if it is in that file. Every phrasal verb in the
language would make every sentence with an unlisted one unreadable for good
under strict counting, the same reason German keeps only the patterns it
registers.

The same interface as `UnitAnalyzer`, private methods included, because
`corpus.parallel` drives either one: it parses on workers, reads the units
off each parse there, and merges the tallies the second pass votes on.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from corpus.analyzer import Evidence
from corpus.filter import ALPHANUMERIC, LATIN, LETTER, FOREIGN_SCRIPT, SentenceFilter
from corpus.sentence import Sentence
from languages import ENGLISH
from vocab.entry import Unit

ROOT = Path(__file__).resolve().parents[1]
EXPRESSIONS = ROOT / "data" / "en" / "expressions.txt"
MODEL = "en_core_web_md"

# Not vocabulary: names and numbers are free to read, the rest is not words.
FREE = frozenset({"PROPN", "NUM", "PUNCT", "SYM", "SPACE", "X"})

# What speech is padded with. Not by tag: `hello` and `wow` share the
# interjection tag and are words a learner is taught.
FILLERS = frozenset("""
uh um umm uhm er erm hmm hm mm mmm mhm huh eh ah oh ooh aw
""".split())

# What a dictionary writes where a phrase goes: `take sth into account`.
SLOTS = ENGLISH.slots

# Tokens an expression's words may have between them when the file gives no
# pattern: `gave it up`, `take good care of`. A slot allows a phrase.
GAP = 2
SLOT_SPAN = 4

# What a preposition leads: its object, or the clause it takes.
OBJECTS = frozenset({"pobj", "pcomp"})

# Lemmas spaCy's English rules get wrong, and what they are. A plural that
# looks like a singular with an `s` on (`species`, `lens`), and `data`, which
# no learner calls `datum`. Applied to every lemma, the corpus's and the
# word list's alike, so the two still meet.
LEMMA_FIXES = {"specie": "species", "len": "lens", "datum": "data"}


def _is_vocabulary(lemma: str) -> bool:
    return (any(c.isalpha() for c in lemma)
            and not any(c.isdigit() for c in lemma)
            and not lemma.endswith(".")
            and lemma not in FILLERS)


def _lemma(token) -> str:
    lemma = token.lemma_.lower().strip()
    return LEMMA_FIXES.get(lemma, lemma)


def _forms(token) -> tuple[str, str]:
    return token.lower_, _lemma(token)


def _says(token, words: frozenset[str]) -> bool:
    lower, lemma = _forms(token)
    return lower in words or lemma in words


@dataclass(frozen=True)
class Expression:
    """One line of the file: its name, and how it is found."""

    canonical: str
    # A run of words: each step is the words it may be, or None for a slot.
    steps: tuple[frozenset[str] | None, ...] = ()
    # Words in a row, from a written pattern: (words, optional).
    row: tuple[tuple[frozenset[str] | None, bool], ...] = ()
    # A verb and the words that hang from it, and for each whether it leads
    # a phrase of its own -- written with `sth` or `sb` after it.
    verb: frozenset[str] = frozenset()
    hangers: tuple[frozenset[str], ...] = ()
    leads: tuple[bool, ...] = ()

    @classmethod
    def parse(cls, line: str) -> "Expression | None":
        canonical, _, pattern = line.partition("\t")
        canonical, pattern = canonical.strip(), pattern.strip()
        if not canonical:
            return None
        if "::" in pattern:
            verb, _, rest = pattern.partition("::")
            hangers: list[frozenset[str]] = []
            leads: list[bool] = []
            for word in rest.split():
                if word.lower() in SLOTS:
                    if leads:
                        leads[-1] = True
                    continue
                hangers.append(frozenset(word.lower().split("/")))
                leads.append(False)
            return cls(canonical,
                       verb=frozenset(verb.strip().lower().split("/")),
                       hangers=tuple(hangers), leads=tuple(leads))
        if pattern:
            row = []
            for word in pattern.split():
                optional = word.startswith("[") and word.endswith("]")
                word = word.strip("[]").lower()
                row.append((None if word == "*" else frozenset(word.split("/")),
                            optional or word == "*"))
            return cls(canonical, row=tuple(row))
        steps = tuple(None if word.lower() in SLOTS
                      else frozenset({word.lower()})
                      for word in canonical.split())
        # A slot at either end says what the expression takes, not a word of
        # it: `get rid of sth` is found by `get rid of`.
        while steps and steps[0] is None:
            steps = steps[1:]
        while steps and steps[-1] is None:
            steps = steps[:-1]
        if len(steps) < 2:
            return None
        return cls(canonical, steps=steps)

    def find(self, doc) -> list[int] | None:
        """The token indices this expression is said with, or None."""
        if self.verb:
            return self._hanging(doc)
        if self.row:
            return self._in_a_row(doc)
        return self._in_order(doc)

    def _in_order(self, doc) -> list[int] | None:
        first = self.steps[0]
        for start in range(len(doc)):
            if _says(doc[start], first):
                found = self._continue(doc, start, 1, [start])
                if found:
                    return found
        return None

    def _continue(self, doc, at: int, step: int,
                  taken: list[int]) -> list[int] | None:
        if step == len(self.steps):
            return taken
        reach = GAP
        while step < len(self.steps) and self.steps[step] is None:
            reach += SLOT_SPAN
            step += 1
        words = self.steps[step]
        for nxt in range(at + 1, min(len(doc), at + 2 + reach)):
            if doc[nxt].is_punct and doc[nxt].text not in ("'", "’"):
                return None          # an expression does not cross a comma
            if _says(doc[nxt], words):
                found = self._continue(doc, nxt, step + 1, taken + [nxt])
                if found:
                    return found
        return None

    def _in_a_row(self, doc) -> list[int] | None:
        def walk(i: int, step: int, taken: list[int]) -> list[int] | None:
            if step == len(self.row):
                return taken
            words, optional = self.row[step]
            if i < len(doc) and (words is None or _says(doc[i], words)):
                found = walk(i + 1, step + 1,
                             taken + ([] if words is None else [i]))
                if found is not None:
                    return found
            if optional:
                return walk(i, step + 1, taken)
            return None

        for start in range(len(doc)):
            found = walk(start, 0, [])
            if found:
                return found
        return None

    def _hanging(self, doc) -> list[int] | None:
        """A verb and its words, each hanging from it, each leading a phrase
        exactly when the file says it does.

        The second half is what tells a particle from a preposition. `go
        on` is `The show must go on`, where `on` leads nothing; in `went to
        London on Monday` the same `on` hangs from the same verb and leads
        `Monday`, and is not `go on` at all. A word the file writes with
        `sth` after it is the other way round: `depends on the weather`.
        What a word leads may be another word of the expression -- `take
        into account`, where `into` leads `account`.
        """
        for verb in doc:
            if verb.pos_ not in ("VERB", "AUX") or not _says(verb, self.verb):
                continue
            taken = [verb.i]
            for words, leads in zip(self.hangers, self.leads):
                found = next((t.i for t in doc
                              if t.i not in taken and _says(t, words)
                              and _hangs_from(t, verb)
                              and (not leads or _leads(t))), None)
                if found is None:
                    break
                taken.append(found)
            else:
                mine = set(taken)
                if all(leads or all(c.i in mine for c in doc[i].children
                                    if c.dep_ in OBJECTS)
                       for i, leads in zip(taken[1:], self.leads)):
                    return sorted(taken)
        return None


def _leads(token) -> bool:
    return any(child.dep_ in OBJECTS for child in token.children)


def _hangs_from(token, verb, depth: int = 3) -> bool:
    for _ in range(depth):
        if token.head == token:
            return False
        token = token.head
        if token == verb:
            return True
    return False


def read_expressions(path: Path = EXPRESSIONS) -> tuple[Expression, ...]:
    if not path.exists():
        return ()
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        expression = Expression.parse(line)
        if expression is not None:
            out.append(expression)
    return tuple(out)


class EnglishAnalyzer:
    """English units, with the interface `corpus.parallel` drives."""

    def __init__(self, pattern_vocabulary: frozenset[str], language: str = "en",
                 processes: int = 1, expressions: Path = EXPRESSIONS) -> None:
        self._patterns = pattern_vocabulary
        self._language = language
        self._processes = processes
        self._expressions_path = expressions
        self._matcher = None
        self._expressions: tuple[Expression, ...] | None = None

    @property
    def matcher(self):
        """The parser, as `matcher.nlp` -- the shape the German matcher
        module has, which is what ingestion and the workers ask for."""
        if self._matcher is None:
            import spacy                                  # noqa: PLC0415
            self._matcher = SimpleNamespace(nlp=spacy.load(MODEL))
        return self._matcher

    @property
    def verb_lemmas(self):
        """German's repair table. English has none to load."""
        return None

    @property
    def expressions(self) -> tuple[Expression, ...]:
        if self._expressions is None:
            self._expressions = tuple(
                e for e in read_expressions(self._expressions_path)
                if e.canonical in self._patterns)
        return self._expressions

    def analyze_all(self, sentences: list[Sentence]) -> list[Sentence]:
        docs = self.matcher.nlp.pipe(
            [s.text for s in sentences], batch_size=500,
            n_process=self._processes if len(sentences) > 5_000 else 1)
        evidence = Evidence()
        analysed = [s.with_units(*self._units(doc, evidence))
                    for s, doc in zip(sentences, docs)]
        return self._normalise(analysed, self._proper_nouns(evidence), {})

    def lemmatise_each(self, texts: list[str]) -> list[str]:
        """One lemma per entry of a word list, aligned with the entries.

        A word alone is its lemma; a phrase that is not a registered
        expression is its head, which is the word the parser says the rest
        hangs from -- `ice cream` is `cream`, and there is no unit `ice
        cream` for it to be. Nothing comes back empty rather than missing.
        """
        out: list[str] = []
        for text, doc in zip(texts, self.matcher.nlp.pipe(texts, batch_size=256)):
            content = [t for t in doc if self._is_content(t)]
            if not content and len(doc) == 1:
                # One word, alone, is often taken for a name -- `data` comes
                # back as a proper noun and would be no word at all. Asked
                # again as a noun phrase it is a noun.
                content = [t for t in self.matcher.nlp(f"the {text.lower()}")
                           if self._is_content(t)][-1:]
            if not content:
                out.append("")
                continue
            root = next((t for t in content if t.head == t), content[-1])
            out.append(_lemma(root))
        return out

    def lemmas(self, texts: list[str]) -> set[str]:
        """Every lemma in `texts`, for resolving a vocabulary file.

        A single word goes through `lemmatise_each`, which asks again when
        the parser takes a lone word for a name -- or `data` on the starter
        list would be known to nobody.
        """
        single = [t for t in texts if len(t.split()) == 1]
        out = {lemma for lemma in self.lemmatise_each(single) if lemma}
        several = [t for t in texts if len(t.split()) > 1]
        for doc in self.matcher.nlp.pipe(several, batch_size=256):
            out.update(_lemma(t) for t in doc if self._is_content(t))
        return out

    # --- the first pass ---------------------------------------------------

    def _units(self, doc, evidence: Evidence):
        units: set[Unit] = set()
        surfaces: dict[Unit, str] = {}
        # Expressions first, longest first, each taking its words: `looks
        # up to him` is `look up to`, not `look up` as well, and the words
        # an expression was said with are not also words of their own.
        found = sorted(((expression, where) for expression in self.expressions
                        if (where := expression.find(doc))),
                       key=lambda pair: -len(pair[1]))
        taken: set[int] = set()
        for expression, where in found:
            if taken.intersection(where):
                continue
            taken.update(where)
            unit = Unit.pattern(expression.canonical)
            units.add(unit)
            surfaces.setdefault(unit, " ".join(doc[i].text for i in where))
        for token in doc:
            lemma = _lemma(token)
            if token.pos_ == "PROPN" and _is_vocabulary(lemma):
                evidence.names[lemma] += 1
            if not self._is_content(token):
                continue
            evidence.content[lemma] += 1
            if token.i in taken:
                continue
            unit = Unit.lemma(lemma)
            units.add(unit)
            surfaces.setdefault(unit, token.text)
        return frozenset(units), tuple(surfaces.items())

    @staticmethod
    def _is_content(token) -> bool:
        """A word someone could learn: not punctuation, a name or a number,
        and not a possessive `'s`, which is grammar rather than a word."""
        if token.is_punct or token.is_space or token.pos_ in FREE:
            return False
        if token.tag_ == "POS":
            return False
        return _is_vocabulary(_lemma(token))

    # --- the second pass --------------------------------------------------
    #
    # Only the vote on names survives into English. The lemma repairs German
    # needs -- a verb the parser gave up on, a separable prefix -- have no
    # English counterpart, so these two answer nothing and change nothing.

    @staticmethod
    def _lemma_corrections(evidence: Evidence) -> dict[str, str]:
        return {}

    @staticmethod
    def _prefixed_corrections(evidence: Evidence,
                              corrections: dict[str, str]) -> dict[str, str]:
        return {}

    @staticmethod
    def _proper_nouns(evidence: Evidence) -> frozenset[str]:
        """Lemmas the parser more often called a name than a word.

        A word tagged as a name somewhere and as a word more often than that
        stays a word: `will` is mostly the modal, whatever the occasional
        Will. One that is mostly a name was a name all along -- and a name is
        not something to learn before a sentence can be read.
        """
        return frozenset(lemma for lemma, count in evidence.names.items()
                         if count > evidence.content.get(lemma, 0))

    @staticmethod
    def _normalise(sentences: list[Sentence], proper: frozenset[str],
                   corrections: dict[str, str]) -> list[Sentence]:
        dropped = {Unit.lemma(lemma) for lemma in proper}
        if not dropped:
            return sentences
        out = []
        for sentence in sentences:
            if sentence.units & dropped:
                sentence = sentence.with_units(
                    frozenset(u for u in sentence.units if u not in dropped),
                    tuple((u, s) for u, s in sentence.surfaces
                          if u not in dropped))
            out.append(sentence)
        return out


# --- which sentences are worth teaching --------------------------------------

# German enough to say a line is not English, and the reverse: the words
# each language uses constantly and the other never does. The lookalikes --
# `in`, `so`, `was`, `will`, `man` -- are in neither.
GERMAN = frozenset("""
der die das und ist sind ich nicht ein eine einen zu mit auf für dass aber
wir sie auch noch wie wenn oder schon nur mal ja doch dann jetzt hier gibt
""".split())
ENGLISH = frozenset("""
the and is are you your this that with have has not but they would could
about from just there what for my his her she he of on to it at be by or if
were been their don't it's i'm we're going know like think really because
""".split())


class EnglishFilter(SentenceFilter):
    """`SentenceFilter`, asking whether a line is English.

    Everything else it tests -- artifacts, the length band, duplicates,
    repetition -- is not about a language. The one test that is, German's
    `_not_german`, is answered here the other way round, under the same
    name: it is the hook the filter calls, and its rejections are counted
    under the reason it reports.
    """

    @staticmethod
    def _not_german(text: str, words: list[str]) -> bool:
        letters = LETTER.findall(text)
        if letters:
            foreign = sum(1 for c in letters if not LATIN.match(c))
            if foreign / len(letters) > FOREIGN_SCRIPT:
                return True
        plain = [ALPHANUMERIC.sub("", w.lower()) for w in words]
        german = sum(1 for w in plain if w in GERMAN)
        english = sum(1 for w in plain if w in ENGLISH)
        return german >= 2 and german > english

