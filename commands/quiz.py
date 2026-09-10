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

from collections import Counter
from pathlib import Path

from vocab.entry import Unit
from vocab.loader import ARTICLES

PROMPT = "  know it? [Enter]=yes  n=no  s=skip  q=save and quit > "
# Anything not in here is a typo, and a typo used to mean yes: the dispatch
# ended in an `else` that counted the word as known. Now it asks again.
ANSWERS = {"", "y", "yes", "n", "no", "s", "skip", "q", "quit"}


class QuizCommand:
    """Walks the assumed-known vocabulary, most frequent first."""

    def run(self, app, limit: int = 40, source: str = "subtitle") -> None:
        counts = self._frequencies(app, source)
        entries = self._entries(app, counts)
        # One question per unit, not per line. The same word is often written
        # in both files, and being asked about `sein` twice is a good way to
        # be answered carelessly the second time. A "no" comments out every
        # line that meant it.
        grouped: dict[Unit, list[dict]] = {}
        for entry in entries:
            grouped.setdefault(entry["unit"], []).append(entry)
        # Confirmed words drop out, which is what lets the quiz finish. A yes
        # used to write nothing, so the next run asked the same forty and the
        # one after that asked them again — there was no way past the first
        # forty except to deny them.
        done = app.checked.units()
        left = sorted((g for g in grouped.values()
                       if counts.get(g[0]["unit"], 0)
                       and g[0]["unit"] not in done),
                      key=lambda g: -counts[g[0]["unit"]])
        pending = left[:limit]
        if not pending:
            raise SystemExit("nothing left to check — every assumed-known word "
                             "has been confirmed or commented out")

        print(f"\n  {len(grouped):,} words are assumed known, {len(done):,} already "
              f"confirmed; checking {len(pending)} of the {len(left):,} left, most "
              "frequent first.")
        print("  Answering no comments the line out; nothing else is touched.\n")

        removed: dict[Path, list[str]] = {}
        asked = known = 0
        for group in pending:
            asked += 1
            unit = group[0]["unit"]
            written = " / ".join(sorted({e["surface"] for e in group}))
            print(f"\n  {asked}/{len(pending)}  {written}"
                  f"   ({counts[unit]:,} times in the corpus)")
            example = self._example(app, unit, source)
            if example:
                print(f"     {example}")
            answer = input(PROMPT).strip().lower()
            while answer not in ANSWERS:
                answer = input("  sorry — [Enter], n, s or q > ").strip().lower()
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

    # --- the vocabulary files -------------------------------------------

    def _entries(self, app, counts: Counter) -> list[dict]:
        """Every live line in the two files, with the unit it stands for.

        Matched against the corpus keys rather than run through the parser.
        `lemmatise_each` is the obvious tool and the wrong one here: given
        "der Anschluss" it answers "der", and given a bare "Anschluss" it
        answers nothing at all, because spaCy reads an isolated noun as a
        proper noun and the analyser drops those. A word list has no
        sentences to give it context, so there is nothing to parse — the
        entry is already written in the shape the units are keyed by.
        """
        out: list[dict] = []
        for path in (app.settings.known_words, app.settings.function_words):
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

    @staticmethod
    def _comment_out(path: Path, lines: list[str]) -> None:
        """Comment the given lines out, leaving the rest of the file alone."""
        wanted = set(lines)
        kept = [f"# not known: {line}" if line in wanted else line
                for line in path.read_text(encoding="utf-8").splitlines()]
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")

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
    def _example(app, unit: Unit, source: str) -> str:
        """One sentence using it, so the word is not judged out of context.

        Asked of the database for the sentences saying this word. It used to
        load the whole corpus looking for them — inside the question loop, so
        once per word: nineteen seconds of silence before every question, and
        thirteen minutes for a quiz of forty.
        """
        from corpus.quality import score
        best, best_score = "", -1.0
        for sentence in app.corpus(source, list_only=False,
                                   holding=(unit.kind, unit.key)):
            value = score(sentence.text)
            if value > best_score:
                best, best_score = sentence.text, value
            if best_score >= 1.0:
                break
        return best
