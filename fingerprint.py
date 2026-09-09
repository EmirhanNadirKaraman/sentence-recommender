"""What produced a cached result.

Analysing the corpus is expensive, so it is cached — and the cache has no
idea what made it. Change the matcher, the dictionary it reads, or the spaCy
model, and every cached unit keeps whatever the old rules produced while
every page carries on reporting it as fact. That has cost this project real
time twice: a bad pattern match stayed visible for a whole session after
being fixed, and the resolved vocabulary survived a model change that
altered every lemma in it.

A fingerprint is the cheapest fix that cannot lie: hash everything that
decides how a unit is derived, store it beside the result, and say so when
they no longer agree. Whole files are hashed rather than the rules picked
out of them, so editing a comment raises a false alarm — which is the right
way round. A warning you can dismiss costs a second; a stale cache you
cannot see costs an afternoon.
"""
from __future__ import annotations

import hashlib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Everything that decides what units a sentence yields: the matcher and the
# analyser that drive it, and the two data files they read.
SOURCES = (
    ROOT / "matcher" / "phrase_finder.py",
    ROOT / "corpus" / "analyzer.py",
    # Not how a unit is derived, but which sentences exist to derive one
    # from — a filter change alters the cached corpus just as surely.
    ROOT / "corpus" / "filter.py",
    ROOT / "data" / "final_result.txt",
    ROOT / "data" / "lemma_overrides.txt",
)

PACKAGES = ("spacy", "de_core_news_md", "de_core_news_sm")


def analyser_fingerprint() -> str:
    """A short digest of the rules currently in force."""
    digest = hashlib.sha256()
    for path in SOURCES:
        digest.update(path.name.encode())
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
    for name in PACKAGES:
        try:
            version = metadata.version(name)
        except metadata.PackageNotFoundError:
            version = "-"
        digest.update(f"{name}={version}".encode())
    return digest.hexdigest()[:16]
