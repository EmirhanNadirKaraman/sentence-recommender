"""`check` — what happens to one word, end to end.

Every wrong goal this project has found looked the same from outside: a word
on the study list that the roadmap never teaches. The cause was different
every time — the parser lemmatised it to something else, the dictionary
listed it under a different form, the corpus only says it inside a compound,
the matcher folded it into a verb. Answering "which of those is it" took a
throwaway script each time.

This asks all four questions at once, for one word, in about a second.
"""
from __future__ import annotations

import re

from vocab.entry import Unit
from vocab.goal_list import GoalList


class CheckWordCommand:
    """Traces one word from the study list to the corpus."""

    def run(self, app, word: str) -> None:
        print(f"\n  {word}\n  " + "─" * 46)
        self._in_files(app, word)
        goal = self._as_goal(app, word)
        self._in_corpus(app, word, goal)

    @staticmethod
    def _in_files(app, word: str) -> None:
        for label, path in (("study list", app.settings.goal_words),
                            ("dictionary", app.settings.form_words),
                            ("corrections", app.settings.goal_lemmas)):
            if not path.exists():
                continue
            # Either column, and with or without an article: the list writes
            # `der Aufsatz` where you would type `Aufsatz`, and looking only
            # for an exact key reports a word as unlisted when it is right
            # there.
            wanted = word.lower()
            rows = []
            for line in path.read_text(encoding="utf-8").splitlines():
                for cell in line.split("\t"):
                    cell = re.sub(r"^(der|die|das)\s+", "", cell.strip()).lower()
                    if cell == wanted:
                        rows.append(line)
                        break
            print(f"  {label:12} {rows[0] if rows else '— not listed —'}")

    def _as_goal(self, app, word: str) -> Unit | None:
        """Which unit the word becomes once resolved, if any.

        Corrections first, exactly as `GoalList` applies them, or this would
        report the parser's answer for a word whose parser answer is the very
        thing being overridden.
        """
        fixed = GoalList.corrections(app.settings.goal_lemmas).get(word)
        lemma = (app.analyzer.lemmatise_each([word]) or [""])[0]
        print(f"  lemmatises to {lemma!r}" + ("" if lemma == word.lower()
                                              else "   <- changed"))
        if fixed:
            print(f"  corrected to {fixed!r}")
            lemma = fixed
        goals = set(app.goal_units)
        # A noun is a goal under its article — `der Aufsatz`, not `Aufsatz` —
        # so those have to be tried too, or the answer is "not a goal" for
        # every noun on the list.
        candidates = [Unit.lemma(lemma), Unit.pattern(lemma),
                      Unit.lemma(word), Unit.pattern(word)]
        candidates += [Unit.pattern(f"{article} {word[:1].upper()}{word[1:]}")
                       for article in ("der", "die", "das")]
        for unit in candidates:
            if unit in goals:
                print(f"  goal unit    {unit.kind}:{unit.key}")
                return unit
        print("  goal unit    — this word is not a goal —")
        return None

    @staticmethod
    def _in_corpus(app, word: str, goal: Unit | None) -> None:
        sentences = app.corpus("subtitle", list_only=False)
        said = [s for s in sentences
                if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", s.text)]
        print(f"  in {len(sentences):,} sentences: said {len(said)} times")

        emitted = [s for s in sentences
                   if goal is not None and goal in s.units]
        if goal is not None:
            print(f"  emitted as {goal.key!r}: {len(emitted)} times"
                  + ("   <- said but never emitted" if said and not emitted else ""))
        known = app.known_set().units
        if goal is not None:
            print(f"  already known: {goal in known}")
        for sentence in (emitted or said)[:3]:
            units = sorted(u.key for u in sentence.units
                           if word.lower() in u.key.lower())
            print(f"    {sentence.text[:66]}")
            print(f"       units: {', '.join(units) or '(none for this word)'}")
