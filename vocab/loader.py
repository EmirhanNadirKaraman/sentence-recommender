"""Parsing for the plain-text vocabulary files.

The files were written for humans, so the format is loose:

    der Abend            leading article, stripped
    der, die, das        several entries on one line, comma-separated
    # a comment          ignored, as are blank lines

Everything is NFC-normalised and lowercased on the way out, because the
database is C-locale and `lower()` there folds ASCII only.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path

ARTICLES = frozenset({"der", "die", "das", "den", "dem", "des"})


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip()).lower()


@dataclass(frozen=True)
class WordList:
    """An ordered, de-duplicated list of surface forms."""

    path: Path
    surfaces: tuple[str, ...]

    def __len__(self) -> int:
        return len(self.surfaces)

    def ranks(self) -> dict[str, int]:
        """surface -> 0-based position, for frequency-ordered files."""
        return {surface: i for i, surface in enumerate(self.surfaces)}


class WordListLoader:
    """Reads a vocabulary file into a `WordList`."""

    def load(self, path: Path) -> WordList:
        seen: dict[str, None] = {}
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            for surface in self._split_entry(line):
                seen.setdefault(surface, None)
        return WordList(path=path, surfaces=tuple(seen))

    @staticmethod
    def _split_entry(line: str) -> list[str]:
        out: list[str] = []
        for part in line.split(","):
            tokens = part.split()
            if len(tokens) > 1 and tokens[0].lower() in ARTICLES:
                tokens = tokens[1:]      # "der Abend" -> "Abend"
            if tokens:
                out.append(normalize(" ".join(tokens)))
        return out
