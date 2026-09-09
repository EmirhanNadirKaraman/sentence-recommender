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
        """What the inputs look like now: size and mtime, per file.

        Content hashing would be surer, but these files run to thousands of
        lines and this has to be cheaper than the work it guards.
        """
        # The rules join the stamp: the vocabulary is resolved *by* the
        # parser, so changing the model changes every lemma in here while
        # every file it was read from stays exactly as it was.
        out = [["rules", analyser_fingerprint(), 0]]
        for path in sources:
            try:
                info = path.stat()
            except OSError:
                out.append([str(path), None, None])
            else:
                out.append([str(path), info.st_mtime_ns, info.st_size])
        return out
