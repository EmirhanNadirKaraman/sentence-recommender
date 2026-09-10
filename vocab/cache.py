"""Remembering what the vocabulary files resolve to.

Resolving them is a Postgres lookup and a spaCy pass over every word in
`known_words.txt`, `function_words.txt` and `study_list.txt` — twenty-nine
seconds, measured, which is most of what adding a video costs. The answer
changes only when those files do, and they change when the reader edits
them, not when a video lands.

So the result is kept beside the corpus cache, stamped with what each input
file looked like when it was computed. A stamp that no longer matches is
simply ignored, which means editing a word list is enough to invalidate it —
there is nothing to remember to run.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fingerprint import analyser_fingerprint


class ResolvedCache:
    """Resolved vocabulary, keyed on the files it came from."""

    def __init__(self, path: Path) -> None:
        self._path = path.with_name("resolved.json")

    def get(self, name: str, sources: list[Path]) -> list | None:
        """The stored value for `name`, or None if the files have moved on."""
        stored = self._read().get(name)
        if stored and stored.get("stamp") == self._stamp(sources):
            return stored["value"]
        return None

    def put(self, name: str, sources: list[Path], value: list) -> None:
        entries = self._read()
        entries[name] = {"stamp": self._stamp(sources), "value": value}
        self._path.write_text(json.dumps(entries), encoding="utf-8")

    def _read(self) -> dict:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A missing or half-written cache is not an error — it just means
            # the work has to be done again.
            return {}

    @staticmethod
    def _stamp(sources: list[Path]) -> list:
        """What the inputs look like now: a content hash, per file.

        It used to be the absolute path, the mtime and the size, which is
        cheaper and cannot travel. Every one of those three is a fact about
        this filesystem rather than about the words: `git clone` on another
        machine writes identical bytes under a different root with fresh
        mtimes, so the cache was guaranteed to miss — and missing costs a
        Postgres round trip and a spaCy pass, on a machine that may have
        neither.

        The five files come to about 250 KB, so hashing them is microseconds
        against the twenty-nine seconds it guards. The original objection —
        that this had to be cheaper than the work — was answered the moment
        `analyser_fingerprint` joined the stamp and started hashing whole
        source files anyway.

        Names, not paths, for the same reason.
        """
        # The rules join the stamp: the vocabulary is resolved *by* the
        # parser, so changing the model changes every lemma in here while
        # every file it was read from stays exactly as it was.
        out = [["rules", analyser_fingerprint(), 0]]
        for path in sources:
            try:
                data = path.read_bytes()
            except OSError:
                out.append([path.name, None, None])
            else:
                out.append([path.name,
                            hashlib.sha256(data).hexdigest()[:16], len(data)])
        return out
