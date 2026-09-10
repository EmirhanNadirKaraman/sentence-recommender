"""`quiz` — check the words the roadmap assumes you already know.

Nine hundred and sixty-five units are counted as known before the walk starts.
All but the twenty-two marked while reading come from `known_words.txt` and
`function_words.txt`, and nothing has ever verified those — 865 of them are
said somewhere in the corpus, which is what this asks about.

A word wrongly on that list does not block anything — it does something worse
and quieter: sentences containing it are called readable, i+1 counts are wrong
wherever it appears, and every number downstream inherits the error without a
warning.

Asked most-frequent first, because that is where being wrong costs most: a
mistaken `der` misprices thousands of sentences, a mistaken `Volkshochschule`
misprices one. Answering "no" comments the line out, which is what both files
already document as the way to say you do not know something — reversible,
readable, and reviewable in a diff.

A "yes" is written down too, to `checked_units` — not because it changes what
you know, but because otherwise the quiz cannot finish. It asks the most
frequent words first and forty at a time, so if a yes left no trace the next
run would ask the same forty, and the run after that would ask them again.
Confirmed words drop out of the pool and the count creeps forward.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from threading import Lock

from vocab.entry import Unit
from vocab.loader import ARTICLES

PROMPT = "  know it? [Enter]=yes  n=no  s=skip  q=save and quit > "
# Anything not in here is a typo, and a typo used to mean yes: the dispatch
# ended in an `else` that counted the word as known. Now it asks again.
ANSWERS = {"", "y", "yes", "n", "no", "s", "skip", "q", "quit"}

# `jdm. (Dat) etw. (Akk) erzählen` — the study list writes a verb with the
# cases it governs. The bare verb is the same word to a learner.
# The vocabulary files are read-modify-written, and the web server answers on
# a thread per request. Two denials at once would otherwise lose one of them.
FILES = Lock()

CASE_FRAME = re.compile(r"\((?:Akk|Dat|Gen)\)")
# `das Essen`, which is a noun that shares a lemma with `essen` the verb.
ARTICLE_NOUN = re.compile(r"^(?:der|die|das)\s+\S+$", re.IGNORECASE)


class QuizCommand:
    """Walks the assumed-known vocabulary, most frequent first."""

    def run(self, app, limit: int = 40, source: str = "subtitle",
            files: str = "both") -> None:
        counts = self._frequencies(app, source)
        entries = self._entries(app, counts, files)
        # One question per unit, not per line. The same word is often written
        # in both files, and being asked about `sein` twice is a good way to
        # be answered carelessly the second time. A "no" comments out every
        # line that meant it.
        grouped: dict[Unit, list[dict]] = {}
        for entry in entries:
            grouped.setdefault(entry["unit"], []).append(entry)
        self._merge_frames(grouped)
        done = app.checked.units()
        left, pending = self.pool(grouped, counts, done, limit)
        if not pending:
            raise SystemExit("nothing left to check — every assumed-known word "
                             "has been confirmed or commented out")

        where = {"known": " in known_words.txt",
                 "function": " in function_words.txt"}.get(files, "")
        print(f"\n  {len(grouped):,} words are assumed known{where}, {len(done):,} "
              f"already confirmed; checking {len(pending)} of the {len(left):,} "
              "left, most frequent first.")
        print("  Answering no comments the line out; nothing else is touched.\n")

        # Fetched once rather than inside `_example`, which is called per
        # question: a sentence the reader hid through `/fix` should not come
        # back as the example they judge a word by.
        hidden = app.overrides.hidden()
        removed: dict[Path, list[str]] = {}
        asked = known = 0
        for group in pending:
            asked += 1
            unit = group[0]["unit"]
            written = " / ".join(sorted({e["surface"] for e in group}))
            print(f"\n  {asked}/{len(pending)}  {written}"
                  f"   ({counts[unit]:,} times in the corpus)")
            example = self._example(app, unit, source, hidden)
            if example:
                print(f"     {example}")
            answer = self._ask()
            if answer in ("q", "quit"):
                break
            if answer in ("s", "skip"):
                continue
            if answer in ("n", "no"):
                for entry in group:
                    removed.setdefault(entry["path"], []).append(entry["line"])
                # It may have been confirmed on an earlier run and since
                # thought better of; the file is being changed either way.
                app.checked.forget(unit)
            else:
                app.checked.confirm(unit)
                known += 1

        for path, lines in removed.items():
            self._comment_out(path, lines)
        total = sum(len(v) for v in removed.values())
        print(f"\n  asked {asked}, knew {known}, removed {total}")
        print(f"  {len(app.checked):,} of {len(grouped):,} confirmed so far")
        for path, lines in removed.items():
            print(f"    {path.name}: {', '.join(l.split('#')[0].strip() for l in lines)}")
        if total:
            print("\n  The known set has changed, so the roadmap is out of date:"
                  "\n    python main.py build-roadmap --source subtitle --goals --list-only")

    @staticmethod
    def pool(grouped: dict[Unit, list[dict]], counts: Counter,
             done: frozenset[Unit], limit: int) -> tuple[list, list]:
        """What is left to ask, and the next `limit` of it.

        Shared with the web page so the two ask the same questions. A word
        drops out for one of two reasons: it has been confirmed already —
        which is what lets the quiz finish, since a yes used to write nothing
        and the next run asked the same forty — or the corpus never says it,
        in which case being wrong about it costs nothing.

        There was a `sample` here that drew at random so the run could end
        with a bound on how many of the rest would be denied. It answered the
        wrong question. A bound is a statement about a rate, and this is not a
        rate: the known set is a list of particular words, and a sentence is
        mispriced by the particular ones that are wrong. Told that between
        five and three hundred and eighty-five of the pool is wrong, there is
        nothing to do with the answer — you cannot correct a percentage. So
        the pool is worked through instead of sampled, and every answer is
        one word that is now certain rather than a smaller error bar.
        """
        left = [g for g in grouped.values()
                if counts.get(g[0]["unit"], 0) and g[0]["unit"] not in done]
        return left, sorted(left, key=lambda g: -counts[g[0]["unit"]])[:limit]

    @staticmethod
    def _ask() -> str:
        """One answer, or `q` if there is nobody there to give one.

        Reading from a closed stdin raised EOFError and printed a traceback,
        which is what happens whenever this is started somewhere without a
        terminal attached — a pipe, a hook, an agent shelling out. The quiz is
        a conversation; with no one to answer it should say so and keep what
        it already has, not fall over on the first question.
        """
        while True:
            try:
                answer = input(PROMPT).strip().lower()
            except EOFError:
                print("\n\n  Nothing to read answers from — this needs a real "
                      "terminal.\n  Open one in this directory and run the same "
                      "command there.")
                return "q"
            if answer in ANSWERS:
                return answer
            print("  sorry — [Enter]=yes, n=no, s=skip, q=quit")

    @staticmethod
    def _merge_frames(grouped: dict[Unit, list[dict]]) -> None:
        """Fold a verb's case frame into the bare verb — one word, one question.

        The study list writes `etw./jdn. (Akk) haben`; `function_words.txt`
        writes `haben`. They are different units and the corpus counts them
        separately, rightly — the frame matches only where the verb takes an
        accusative object, 19,472 sentences against 21,421. To a reader being
        asked whether they know the word, they are the same question, and
        asking it twice is how you get two different answers.

        The corpus side already reconciles them: `covered_forms` holds the
        bare verb beside the goal that teaches it, so it is not counted as a
        stranger. This is the same reconciliation, applied to the asking.

        Only case frames, and only onto a verb. `das Essen` shares its lemma
        with `essen` and is a different word — the article says so, which is
        the one piece of evidence available here without a parser.
        """
        bare = {unit.key.lower(): unit for unit in grouped if not unit.is_pattern}
        for unit in [u for u in grouped if u.is_pattern]:
            if not CASE_FRAME.search(unit.key):
                continue
            verb = bare.get(unit.key.split()[-1].lower())
            if verb is None or any(ARTICLE_NOUN.match(e["surface"])
                                   for e in grouped[verb]):
                continue
            # Onto the bare verb, which is the more frequent of the two and so
            # the one whose count should order the question.
            grouped[verb].extend(grouped.pop(unit))

    # --- the vocabulary files -------------------------------------------

    def _entries(self, app, counts: Counter, files: str = "both") -> list[dict]:
        """Every live line in the vocabulary files, with the unit it stands for.

        `files` narrows to one of them. They hold different kinds of claim and
        are worth working through separately: `function_words.txt` is
        generated from the dictionary and is closed-class, so most answers
        will be yes and the ones that are not tend to be the generator's
        fault rather than a gap — `aufn`, which is "auf den" run together.
        `known_words.txt` is a published wordlist nobody has checked against
        this reader, which is where the doubt is.

        Matched against the corpus keys rather than run through the parser.
        `lemmatise_each` is the obvious tool and the wrong one here: given
        "der Anschluss" it answers "der", and given a bare "Anschluss" it
        answers nothing at all, because spaCy reads an isolated noun as a
        proper noun and the analyser drops those. A word list has no
        sentences to give it context, so there is nothing to parse — the
        entry is already written in the shape the units are keyed by.
        """
        wanted = {"known": (app.settings.known_words,),
                  "function": (app.settings.function_words,)}.get(
                      files, (app.settings.known_words,
                              app.settings.function_words))
        out: list[dict] = []
        for path in wanted:
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                surface = line.split("#")[0].strip()
                if not surface or line.lstrip().startswith("#"):
                    continue
                out.append({"path": path, "line": line, "surface": surface,
                            "unit": self._unit_for(surface, counts)})
        return out

    @staticmethod
    def _unit_for(surface: str, counts: Counter) -> Unit:
        """The unit a written entry stands for, preferring the one the
        corpus actually uses: `der Anschluss` may be a pattern in its own
        right, or may only ever appear as the bare lemma."""
        words = surface.split()
        bare = " ".join(words[1:]) if len(words) > 1 and words[0].lower() in ARTICLES \
            else surface
        candidates = [Unit.pattern(surface), Unit.lemma(bare.lower()),
                      Unit.lemma(surface.lower())]
        return max(candidates, key=lambda u: counts.get(u, 0))

    MARK = "# not known: "

    @classmethod
    def _comment_out(cls, path: Path, lines: list[str]) -> None:
        """Comment the given lines out, leaving the rest of the file alone."""
        wanted = set(lines)
        with FILES:
            kept = [f"{cls.MARK}{line}" if line in wanted else line
                    for line in path.read_text(encoding="utf-8").splitlines()]
            path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    @classmethod
    def restore(cls, path: Path, lines: list[str]) -> int:
        """Undo `_comment_out` — put the lines back as they were.

        The web page needs this and the terminal never did. On the phone a
        wrong answer is a thumb landing an inch left of where it meant to,
        and the write it causes is to a file under version control; without
        an inverse the only way back is git. Matched on the exact text that
        was struck, so a line commented out by hand for some other reason is
        left alone.
        """
        wanted = {f"{cls.MARK}{line}" for line in lines}
        with FILES:
            read = path.read_text(encoding="utf-8").splitlines()
            kept = [line[len(cls.MARK):] if line in wanted else line
                    for line in read]
            if kept != read:
                path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        return sum(a != b for a, b in zip(read, kept))

    # --- what the corpus says -------------------------------------------

    @staticmethod
    def _frequencies(app, source: str) -> Counter:
        """How often each unit is said, for ranking what to ask about.

        Counted by the database rather than by loading the corpus and
        tallying it, which was nineteen seconds before the first question.
        """
        return Counter({Unit(kind, key): n for (kind, key), n
                        in app.corpus_store.unit_counts(source).items()})

    @staticmethod
    def _example(app, unit: Unit, source: str, hidden: frozenset | set = ()) -> str:
        """One sentence using it, so the word is not judged out of context.

        Asked of the database as text, in three widening passes. The first
        asks only for sentences of the ideal length, which is what `score`
        gives a perfect mark to, and takes the first that has no sentence
        break inside it — the same sentence the old loop stopped at, reached
        without reading the other thirty thousand.

        Two rewrites got here. The first loaded the whole corpus per question,
        nineteen seconds each and thirteen minutes for a quiz of forty. The
        second asked the database for the sentences saying the word, which was
        right but still built every one of them into a Sentence with its unit
        set — ten seconds for `sein` — to read the one string on it. This asks
        for the string.
        """
        from corpus.quality import BAND, IDEAL, score
        # The best seen so far, not the best of the last pass. A widening
        # search that returned whatever the final pass found could hand back
        # something worse than an earlier pass had already located — the last
        # pass is unordered, forty rows in whatever order the table holds
        # them, so it is the least likely to hold the winner.
        best, best_score = "", -1.0
        # The ideal band is widened by one at each end: SQLite counts words by
        # counting spaces, so a double space reads as an extra word and a
        # sentence that belongs here can be excluded from its own range.
        for words in ((IDEAL[0] - 1, IDEAL[1] + 1), BAND, None):
            for text in app.corpus_store.example_texts(
                    unit.kind, unit.key, source, words=words, limit=40):
                if text in hidden:
                    continue
                value = score(text)
                if value > best_score:
                    best, best_score = text, value
            if best_score >= 1.0:
                break          # a perfect mark; widening cannot beat it
        return best
