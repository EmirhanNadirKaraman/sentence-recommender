"""Placeholder — filled in with the corpus queries next."""
from __future__ import annotations


class SentenceRepository:
    def __init__(self, db, language: str = "de") -> None:
        self._db = db
        self._language = language
