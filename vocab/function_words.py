"""Renders the closed-class review file.

The starting known set is `known_words.txt` — 771 entries, almost all content
nouns.  It contains virtually no function words, so without this file `der`,
`weil` and `nicht` all count as unknown and the roadmap spends its first
hundred steps teaching articles.  Rather than assume, the closed classes are
written out for the reader to confirm or strike.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from db.word_repo import CLOSED_CLASS, FunctionWord

HEADER = """\
# Function words — the closed word classes present in the German corpus.
#
# Every line here counts as ALREADY KNOWN when the roadmap decides which
# sentences are i+1.  These are the classes a learner acquires wholesale
# rather than one item at a time: articles, pronouns, prepositions,
# conjunctions, particles, auxiliaries, modals.
#
# HOW TO REVIEW
#   Delete a line — or put a `#` in front of it — for anything you do NOT
#   know.  What remains is treated as known.  Order does not matter.
#
# The number is how often the word occurs in the corpus; the words after it
# are the surface forms it appears as.
#
# Generated {today} from word_table (language=de) — {count} lemmas.
# Regenerate with:  python main.py function-words
"""


class FunctionWordFile:
    """Writes `FunctionWord`s out as a human-editable list."""

    def render(self, words: list[FunctionWord]) -> str:
        by_category: dict[str, list[FunctionWord]] = {name: [] for name in CLOSED_CLASS}
        for word in words:
            by_category[word.category].append(word)

        lines = [HEADER.format(today=date.today().isoformat(), count=len(words))]
        for category, members in by_category.items():
            if not members:
                continue
            lines.append(f"\n## {category} ({len(members)})")
            width = max(len(w.lemma) for w in members)
            for word in members:
                examples = ", ".join(word.examples)
                lines.append(
                    f"{word.lemma:<{width}}  # {word.frequency:>5}x  {examples}"
                )
        return "\n".join(lines) + "\n"

    def write(self, path: Path, words: list[FunctionWord]) -> int:
        path.write_text(self.render(words), encoding="utf-8")
        return len(words)
