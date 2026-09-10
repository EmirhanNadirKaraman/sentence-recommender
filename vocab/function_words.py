"""Renders the closed-class review file.

The starting known set is `known_words.txt` — 771 entries, almost all content
nouns.  It contains virtually no function words, so without this file `der`,
`weil` and `nicht` all count as unknown and the roadmap spends its first
hundred steps teaching articles.  Rather than assume, the closed classes are
written out for the reader to confirm or strike.
"""
from __future__ import annotations

import re
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

    # A struck line and a live one differ only by the leading `#`; both carry
    # the generated `# 123x  forms` comment, which is what tells either apart
    # from the prose in the header.
    STRUCK = re.compile(r"^#\s*(\S+)\s+#\s+\d+x")
    LIVE = re.compile(r"^(\S+)\s+#\s+\d+x")

    @classmethod
    def struck(cls, path: Path) -> set[str]:
        """The lemmas a reader has already said they do not know.

        Held in the file as a leading `#`, which is what the header asks for
        and what the quiz writes when the answer is no.
        """
        if not path.exists():
            return set()
        return {m.group(1) for m in map(
            cls.STRUCK.match, path.read_text(encoding="utf-8").splitlines()) if m}

    def write(self, path: Path, words: list[FunctionWord]) -> int:
        """Regenerate the file, keeping the decisions already recorded in it.

        This overwrote blindly. Every `#` in the file is a reader saying they
        do not know a word — twenty-four of them by hand, plus every "no" the
        quiz has recorded — and regenerating threw the lot away without
        saying so. The word list is derived and can be rebuilt; the judgements
        about it cannot.
        """
        struck = self.struck(path)
        rendered = self.render(words)
        if struck:
            kept = []
            for line in rendered.splitlines():
                found = self.LIVE.match(line)
                kept.append(f"# {line}" if found and found.group(1) in struck
                            else line)
            rendered = "\n".join(kept) + "\n"
        path.write_text(rendered, encoding="utf-8")
        return len(words)
