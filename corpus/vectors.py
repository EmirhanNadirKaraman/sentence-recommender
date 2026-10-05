"""What a sentence means, as a number, so two of them can be compared.

Trigrams catch a card that repeats a collocation and a card that shows one
sentence twice. What they cannot catch is `Alles wird gut Lisa darf nicht
noch eine 6 bekommen.` beside `Du machst, was ich sage, oder du bekommst eine
Sechs.` -- both about failing a class, sharing no phrase, because the link
runs through `6` and `Sechs` meaning a bad grade in a German school.

Measured against the alternatives before this was built. spaCy's static
vectors, averaged, score that pair at 0.480 and score a *different* sense of
the same word at 0.480 too -- no discrimination at all. The chat model's own
pooled embeddings were worse, rating an unrelated sentence closer than the
pair. A trained embedding model separates them: 0.560 against 0.300, with an
unrelated control at 0.274.

Stored at 512 dimensions rather than the model's full 2,560. Qwen3-Embedding
is trained so a prefix of the vector is itself a usable vector, and measured
here the truncation does not merely survive -- it widens the gap between
same-topic and different-sense from 0.204 to 0.260. 256 widens it further
still and was rejected: there, an unrelated sentence and a different sense
collapse to the same number, and that distinction is worth keeping.

Keyed by sentence text, like the verdicts and the glosses, so a rebuild of
the corpus does not throw the work away.
"""
from __future__ import annotations

import re
from datetime import datetime

import numpy as np

from state import ensure, open_state

DIMS = 512
# float16 halves the storage for a difference far below the thresholds this
# feeds: 62,000 sentences are 32MB rather than 64MB.
DTYPE = np.float16

SCHEMA = """
CREATE TABLE IF NOT EXISTS sentence_vector (
    text    TEXT COLLATE "C" PRIMARY KEY,
    vector  BYTEA NOT NULL,
    dims    BIGINT NOT NULL,
    model   TEXT COLLATE "C" NOT NULL,
    made_at TEXT COLLATE "C" NOT NULL
);
"""


# How much of a word to strip. German inflects at the end -- `bekommen`,
# `bekommst`, `bekomme` -- so a prefix catches the forms a plain match misses.
# Two characters off anything long enough to spare them; short words whole,
# because trimming `Fall` to `Fa` would take `Familie` with it.
STEM_KEEP = 2
STEM_MIN = 6


def stem(word: str) -> str:
    return word[:-STEM_KEEP] if len(word) >= STEM_MIN else word


def without(text: str, surface: str) -> str:
    """The sentence with the word it teaches taken out.

    Comparing two examples of the same word, that word is in both by
    construction: it is the one thing they are guaranteed to share, so it
    tells you nothing about whether their contexts differ -- and being shared,
    it pulls every pair of them closer together.

    Measured, the difference is not small. Two `der Vater` sentences with the
    same frame scored 0.641 and two with different ones scored 0.632: a gap of
    0.009, which is no signal at all. With `Vater` removed the gap is 0.065.
    On `bekommen` the separation goes from 0.259 to 0.301.

    Only the head of the surface is removed -- the last word of `eine 6
    bekommen` -- because the rest is article and number, and taking those out
    strips the context this exists to compare.
    """
    words = surface.split()
    if not words:
        return text
    return re.sub(rf"\b{re.escape(stem(words[-1]))}\w*", " ", text,
                  flags=re.IGNORECASE)


def pack(raw) -> bytes:
    """A model's answer as the bytes to store: truncated, unit length, f16.

    Normalised on the way in so every reader can use a plain dot product and
    none of them has to remember to divide.
    """
    vector = np.asarray(raw, dtype=np.float32)[:DIMS]
    size = float(np.linalg.norm(vector))
    if size:
        vector = vector / size
    return vector.astype(DTYPE).tobytes()


class VectorStore:
    """Sentence vectors, by the sentence."""

    def __init__(self, config) -> None:
        self._db = config
        ensure(config, SCHEMA)

    def have(self) -> set[str]:
        """Every sentence already answered for, so a run can resume."""
        with open_state(self._db) as conn:
            return {row[0] for row in
                    conn.execute("SELECT text FROM sentence_vector")}

    def add_many(self, vectors: dict[str, bytes], model: str) -> None:
        now = datetime.now().isoformat()
        with open_state(self._db) as conn:
            conn.executemany(
                "INSERT INTO sentence_vector"
                " (text, vector, dims, model, made_at) VALUES (%s, %s, %s, %s, %s)"
                " ON CONFLICT (text) DO UPDATE SET vector = excluded.vector,"
                " dims = excluded.dims, model = excluded.model,"
                " made_at = excluded.made_at",
                [(text, blob, DIMS, model, now)
                 for text, blob in vectors.items()])

    @staticmethod
    def stored(config) -> dict[str, np.ndarray]:
        """`load`, for a reader who may never have stored a vector -- read
        without making the table, so asking does not change anything."""
        with open_state(config) as conn:
            if conn.execute("SELECT to_regclass('sentence_vector')"
                            ).fetchone()[0] is None:
                return {}
            return {text: np.frombuffer(blob, dtype=DTYPE).astype(np.float32)
                    for text, blob in
                    conn.execute("SELECT text, vector FROM sentence_vector")}

    def load(self) -> dict[str, np.ndarray]:
        """Every vector, as float32 arrays ready to dot together.

        Widened on the way out: the storage is f16 to keep the file small,
        but numpy's f16 dot is done in software and is several times slower
        than f32 on every machine this runs on.
        """
        with open_state(self._db) as conn:
            return {text: np.frombuffer(blob, dtype=DTYPE).astype(np.float32)
                    for text, blob in
                    conn.execute("SELECT text, vector FROM sentence_vector")}

    def count(self) -> int:
        with open_state(self._db) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM sentence_vector").fetchone()[0]
