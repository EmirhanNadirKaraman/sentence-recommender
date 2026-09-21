"""The fixed expressions' canonicals, read without the matcher.

`data/expressions.txt` is the matcher's file — it says how each expression
is found. Two other readers want only the first column: the application,
which registers the canonicals as patterns beside `phrase_table`'s, and the
study list, which lists them as goals. Neither needs spaCy loaded to know
the names, so the column is read here.
"""
from __future__ import annotations

from pathlib import Path


def canonicals(path: Path) -> tuple[str, ...]:
    """Every canonical in the file, in its order, comments and blanks
    dropped; a line without a pattern still names one."""
    out: list[str] = []
    if not path.exists():
        return ()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        canonical = line.partition("\t")[0].strip()
        if canonical and canonical not in out:
            out.append(canonical)
    return tuple(out)
