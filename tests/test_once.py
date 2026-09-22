"""`Once`, the cache that fills a key exactly once however many threads ask.

The bug it exists for: `serve` answers every request on its own thread, and a
cold corpus load is ten seconds. A plain `if key not in cache` lets every
thread arriving inside those ten seconds start its own load. Measured, sixty
concurrent cold requests reached 1.6 GB resident and answered none of them
inside five minutes.

No sleeps anywhere below. Threads announce themselves through an `Event` or a
`Barrier`, and the builds under test block until the test releases them, so
the interleaving is forced rather than waited for.
"""
from __future__ import annotations

import threading
import unittest

from web.handlers import Once

# Long enough that a correct implementation never reaches it, short enough
# that a deadlocked one fails the suite instead of hanging it.
NEVER = 10.0


class OnceTest(unittest.TestCase):
    def test_one_build_per_key_under_concurrent_callers(self) -> None:
        """Twelve threads, one load, one object handed to all of them."""
        threads = 12
        calls: list[int] = []
        counted = threading.Lock()
        arrived = threading.Semaphore(0)
        release = threading.Event()
        cache = Once()

        def make() -> list[str]:
            with counted:
                calls.append(1)
            # Held open until every caller is inside `get`, so the others
            # have to queue on the key rather than find the work done.
            self.assertTrue(release.wait(NEVER), "build was never released")
            return ["loaded"]

        results: list[object] = [None] * threads

        def worker(i: int) -> None:
            arrived.release()
            results[i] = cache.get("subtitle|all", make)

        pool = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
        for t in pool:
            t.start()
        for _ in range(threads):          # every worker is inside `worker`
            self.assertTrue(arrived.acquire(timeout=NEVER))
        release.set()
        for t in pool:
            t.join(NEVER)
            self.assertFalse(t.is_alive())

        self.assertEqual(len(calls), 1, "the corpus was loaded more than once")
        # The same object, not merely an equal one: two loads that happened to
        # agree would still be two copies in memory.
        for got in results:
            self.assertIs(got, results[0])

    def test_a_key_being_built_does_not_block_another_key(self) -> None:
        """One corpus loading must not hold up a different one.

        A single lock over the whole cache would pass every other test here
        and fail this one, which is the reason it is a lock per key.
        """
        cache = Once()
        holding = threading.Event()
        release = threading.Event()

        def slow() -> str:
            holding.set()
            self.assertTrue(release.wait(NEVER), "build was never released")
            return "subtitle"

        blocked = threading.Thread(target=lambda: cache.get("subtitle", slow))
        blocked.start()
        try:
            self.assertTrue(holding.wait(NEVER), "the slow build never started")
            # On the main thread, while `subtitle` is mid-build. If this
            # blocks, the cache is serialising unrelated keys.
            self.assertEqual(cache.get("transcript", lambda: "transcript"),
                             "transcript")
        finally:
            release.set()
            blocked.join(NEVER)
        self.assertFalse(blocked.is_alive())

    def test_a_failed_build_is_not_cached_and_can_be_retried(self) -> None:
        cache = Once()

        def boom() -> str:
            raise RuntimeError("postgres is down")

        with self.assertRaises(RuntimeError):
            cache.get("subtitle", boom)
        self.assertNotIn("subtitle", cache)
        # The failure is not remembered: the next caller gets a real attempt.
        self.assertEqual(cache.get("subtitle", lambda: "loaded"), "loaded")
        self.assertIn("subtitle", cache)

    def test_a_failed_build_releases_its_waiters(self) -> None:
        """A thread queued behind a build that raises must not be stranded.

        Each waiter then makes its own attempt, which is what allows the
        retry above to work from any thread rather than only the first.
        """
        cache = Once()
        attempts: list[int] = []
        counted = threading.Lock()
        first = threading.Event()
        release = threading.Event()

        def flaky() -> str:
            with counted:
                attempts.append(1)
                mine = len(attempts)
            if mine == 1:
                first.set()
                self.assertTrue(release.wait(NEVER))
                raise RuntimeError("postgres is down")
            return "loaded"

        failed: list[BaseException] = []

        def failing_caller() -> None:
            try:
                cache.get("subtitle", flaky)
            except BaseException as exc:      # noqa: BLE001 - recorded, asserted below
                failed.append(exc)

        one = threading.Thread(target=failing_caller)
        one.start()
        self.assertTrue(first.wait(NEVER), "the first build never started")

        waited: list[object] = []
        two = threading.Thread(target=lambda: waited.append(
            cache.get("subtitle", flaky)))
        two.start()
        release.set()
        for t in (one, two):
            t.join(NEVER)
            self.assertFalse(t.is_alive())

        self.assertEqual(len(failed), 1)
        self.assertIsInstance(failed[0], RuntimeError)
        self.assertEqual(waited, ["loaded"])
        self.assertEqual(cache.get("subtitle", flaky), "loaded")

    def test_clear_forgets_and_rebuilds(self) -> None:
        cache = Once()
        self.assertEqual(cache.get("k", lambda: "first"), "first")
        self.assertEqual(cache.get("k", lambda: "second"), "first")
        cache.clear()
        self.assertEqual(cache.get("k", lambda: "second"), "second")

    def test_a_build_that_outlives_its_invalidation_is_not_stored(self) -> None:
        """`adopt()` clears the corpus while a load is in flight.

        The caller still gets the rows it asked for — they were read after its
        request began — but they must not land in the cache, or a load that
        started before the new sentence existed would serve every reader after
        it. The next caller reloads.
        """
        cache = Once()
        loading = threading.Event()
        release = threading.Event()
        got: list[object] = []

        def slow() -> str:
            loading.set()
            self.assertTrue(release.wait(NEVER))
            return "stale"

        reader = threading.Thread(target=lambda: got.append(
            cache.get("subtitle", slow)))
        reader.start()
        self.assertTrue(loading.wait(NEVER), "the load never started")
        cache.clear()                      # the corpus changed under it
        release.set()
        reader.join(NEVER)
        self.assertFalse(reader.is_alive())

        self.assertEqual(got, ["stale"])   # the caller is still answered
        self.assertNotIn("subtitle", cache)
        self.assertEqual(cache.get("subtitle", lambda: "fresh"), "fresh")

    def test_falsey_values_are_cached(self) -> None:
        """An empty corpus is an answer, not a miss.

        A build with nothing in it is exactly what an unbuilt source returns,
        and testing the value for truth rather than for `None` would reload it
        on every request — the slowest possible answer to the emptiest page.
        """
        cache = Once()
        calls: list[int] = []

        def make() -> list[str]:
            calls.append(1)
            return []

        self.assertEqual(cache.get("empty", make), [])
        self.assertEqual(cache.get("empty", make), [])
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
