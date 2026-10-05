"""What a reader other than the installation's own may spend.

Anyone with a Google account can make an account here, so what costs the
owner -- the local model's time, and the memory a reader's pages hold -- is
rationed for everyone else. The installation's own reader is never limited:
it is their machine, and their model.

A reader's `Application` carries their `Allowance` as `guest` (see
`context.Application.spend`); the owner's carries None.
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock

# Model calls a reader may make in any hour: a word's gloss asked for the
# first time, a sentence tried, a sentence put into the other language.
# Each is a few seconds of the model; sixty is an evening's reading, and a
# ceiling on what one account can take from everyone else.
MODEL_PER_HOUR = 60

# Word lists besides their own that a reader other than the owner keeps
# open at once. Each is an application of its own -- a parser and its
# caches, about 250 MB measured -- so an account that saved a dozen lists
# and opened each would otherwise hold a dozen of those.
LISTS_OPEN = 1

# What a reader is told when the hour's model calls are spent.
SPENT = ("You have asked the model a lot this hour; it will answer again "
         "within the hour.")

HOUR = 3600.0


class Allowance:
    """At most `per_hour[kind]` uses of each kind in any sixty minutes."""

    def __init__(self, per_hour: dict[str, int] | None = None) -> None:
        self._per_hour = dict(per_hour or {"model": MODEL_PER_HOUR})
        self._spent: dict[str, deque] = {}
        self._lock = Lock()

    def take(self, kind: str) -> bool:
        """Spend one `kind`, if any is left in the last hour."""
        limit = self._per_hour.get(kind)
        if limit is None:
            return True
        now = time.monotonic()
        with self._lock:
            spent = self._spent.setdefault(kind, deque())
            while spent and now - spent[0] >= HOUR:
                spent.popleft()
            if len(spent) >= limit:
                return False
            spent.append(now)
            return True
