"""What a reader other than the installation's own may spend.

Anyone with a Google account can make an account here, so what costs the
owner -- the local model's time, and the memory a reader's pages hold -- is
rationed for everyone else. The installation's own reader is never limited:
it is their machine, and their model.

A reader's `Application` carries their `Allowance` as `guest` (see
`context.Application.spend`); the owner's carries None.
"""
from __future__ import annotations

import os
import time
from collections import deque
from threading import Lock

# Model calls a reader may make in any hour: a word's gloss asked for the
# first time, a sentence tried, a sentence put into the other language.
# Each is a few seconds of the model; sixty is an evening's reading, and a
# ceiling on what one account can take from everyone else.
MODEL_PER_HOUR = 60

# Word lists besides their own that an invited reader keeps open at once,
# and that someone who signed up on their own may open at all. Each is an
# application of its own, and one without a stored plan walks the whole
# corpus on its first page: 2.1 GB and 25 s measured for German. An account
# that saved a dozen lists and opened each would otherwise hold a dozen.
LISTS_OPEN = 1
LISTS_OPEN_SIGNED_UP = 0

# Readers who signed up on their own whose pages are held in memory at once,
# unless `SIGNUPS_IN_MEMORY` in `.env` says otherwise; the least recently
# reading goes first, and their next page builds it again. At 2.1 GB each,
# this, not the number of accounts, is what bounds the memory strangers
# can take. The owner and invited readers are never let go.
SIGNUPS_IN_MEMORY = 2

# What a reader is told when the hour's model calls are spent.
SPENT = ("You have asked the model a lot this hour; it will answer again "
         "within the hour.")

HOUR = 3600.0


def signups_in_memory() -> int:
    from config import load_dotenv                       # noqa: PLC0415
    load_dotenv()
    try:
        return max(1, int(os.environ.get("SIGNUPS_IN_MEMORY",
                                         SIGNUPS_IN_MEMORY)))
    except ValueError:
        return SIGNUPS_IN_MEMORY


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
