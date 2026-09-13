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
    # Which nouns are kept apart from the verb they share a lemma with.
    ROOT / "data" / "noun_verb_splits.txt",
    # Lemmas the parser invented, and what they should have been.
    ROOT / "data" / "lemma_fixes.txt",
)

# The parser, and only what is actually loaded. `de_core_news_sm` was
# hashed here too and is loaded by nothing: the matcher asks for `md` by
# name, because under `sm` it lemmatises `schreien` to `schreie`. Hashing
# a package nobody parses with meant installing or removing it announced a
# parser change that had not happened.
PACKAGES = ("spacy", "de_core_news_md")


def analyser_fingerprint() -> str:
    """A short digest of the rules currently in force.

    The rules only — the files above. The installed package versions used to
    be hashed in here too, which made the digest a property of the *machine*
    rather than of the rules. A host that serves these caches without ever
    parsing anything would compute a different answer purely by not having
    spaCy installed, and every page would fall off the fast path onto a
    full-corpus walk. Asking "did the rules change?" and being told "you are
    a different computer" is not a useful answer.

    The versions still matter — the parser decides what a lemma is — so they
    are kept, separately, by `packages_fingerprint`, recorded beside this and
    warned about rather than used to invalidate. See `CorpusStore.stale`.
    """
    digest = hashlib.sha256()
    for path in SOURCES:
        digest.update(path.name.encode())
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()[:16]


def packages_fingerprint() -> str:
    """A short digest of the parser that produced a cache.

    A missing package hashes as "-", so a machine that never installed spaCy
    is distinguishable from one that changed its version — which is the whole
    point of keeping this apart from the rules.
    """
    digest = hashlib.sha256()
    for name in PACKAGES:
        try:
            version = metadata.version(name)
        except metadata.PackageNotFoundError:
            version = "-"
        digest.update(f"{name}={version}".encode())
    return digest.hexdigest()[:16]
