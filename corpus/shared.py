"""Web-process sharing of immutable corpus data, never of reader progress."""
from collections import defaultdict
from threading import Lock, RLock
from types import MappingProxyType
from weakref import WeakValueDictionary


class CorpusRows(list):
    """Read-only-by-convention sentences with once-built static indexes.

    Sentence is frozen. Callers must replace/filter this sequence, not edit
    it. A view retains its base so another reader can reuse the original rows.
    """

    def __init__(self, rows, base=None):
        super().__init__(rows)
        self.base = base
        self._memo = {}
        self._lock = RLock()

    def memo(self, name, make):
        with self._lock:
            if name not in self._memo:
                self._memo[name] = make()
            return self._memo[name]

    def videos(self):
        def build():
            groups, units = defaultdict(list), defaultdict(set)
            for sentence in self:
                if sentence.timing is None:
                    continue
                video = sentence.timing.video_id
                groups[video].append(sentence)
                for unit in sentence.units:
                    units[unit].add(video)
            return (MappingProxyType({k: tuple(v) for k, v in groups.items()}),
                    MappingProxyType({k: frozenset(v) for k, v in units.items()}))
        return self.memo('videos', build)


class CorpusPool:
    """Single-flight loads. Weak values let unused lists/vintages disappear."""

    def __init__(self):
        self._values = WeakValueDictionary()
        self._locks = WeakValueDictionary()
        self._guard = Lock()

    def get(self, key, make):
        with self._guard:
            value = self._values.get(key)
            if value is not None:
                return value
            lock = self._locks.get(key)
            if lock is None:
                lock = Lock()
                self._locks[key] = lock
        with lock:
            with self._guard:
                value = self._values.get(key)
            if value is None:
                value = make()
                if not isinstance(value, CorpusRows):
                    value = CorpusRows(value)
                with self._guard:
                    self._values[key] = value
            return value
