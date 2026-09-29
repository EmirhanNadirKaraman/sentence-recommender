"""What makes a card the same card as last time.

Anki decides whether an imported note updates an existing one or becomes a new
one by its identity, and a new one starts its scheduling from nothing. Left to
itself that identity is a hash of every field -- `genanki` does exactly this,
and Anki's text importer falls back to the first field -- so regenerating a
deck whose sentences have improved threw away every interval the reader had
earned. The identity has to come from the thing being learned, not from what
the card currently says about it.

The format is Anki's own: the first eight bytes of a SHA-256, in the base91
alphabet Anki writes its own guids in. Matching it is not required -- the
importer takes the column as an opaque string -- but a guid that looks like a
guid is one less thing to wonder about when reading a collection by hand.
"""
from __future__ import annotations

import hashlib

# Anki's alphabet, in Anki's order. Not base64 and not the usual base91 table.
BASE91 = (
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "!#$%&()*+,-./:;<=>?@[]^_`{|}~"
)


def guid_for(*values: object) -> str:
    """A stable id for the named thing. The same values always give the same
    id, and no two different things share one short of a hash collision."""
    joined = "__".join(str(v) for v in values)
    number = int.from_bytes(hashlib.sha256(joined.encode()).digest()[:8], "big")
    out: list[str] = []
    while number > 0:
        number, rest = divmod(number, len(BASE91))
        out.append(BASE91[rest])
    return "".join(reversed(out)) or BASE91[0]
