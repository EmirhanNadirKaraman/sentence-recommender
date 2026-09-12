"""Keeping the machine's words out of the hand-written builds.

`SubtitleSource.lines` filtered on `v.language` and nothing else, which was
right while every row in the catalogue was hand-written. It stops being right
the moment one is not: `CorpusUpdater.catch_up` asks this same query for
every build, so an auto-captioned import would be folded into `subtitle`, and
neither the corpus nor the reader would have any way of telling which
sentences a machine wrote.

There is no command to take a video back out of the catalogue, so this is
tested rather than trusted.
"""
from __future__ import annotations

import unittest

from commands.add_videos import BUILD_OF
from corpus.source import BUILD_SOURCES, MANUAL, SubtitleSource, sources_for


class _Db:
    """A database that records the query it was given and answers nothing."""

    def __init__(self) -> None:
        self.sql = ""
        self.params: tuple = ()

    def rows(self, sql: str, params=None):
        self.sql, self.params = sql, tuple(params or ())
        return []


class SourcesForTest(unittest.TestCase):
    def test_the_hand_written_builds_read_hand_written_subtitles(self) -> None:
        self.assertEqual(sources_for("subtitle"), MANUAL)
        self.assertEqual(sources_for("subtitle:llm"), MANUAL)

    def test_the_auto_build_reads_the_machine_ones(self) -> None:
        self.assertEqual(sources_for("subtitle:auto"), ("auto",))

    def test_no_build_reads_both(self) -> None:
        """Mixing is the failure this exists to prevent, not a configuration.

        A build holding both kinds has nothing recorded saying which
        sentences came from which, and the corpus store keys on the build
        name alone.
        """
        for build, sources in BUILD_SOURCES.items():
            self.assertEqual(len(set(sources)), 1, build)

    def test_an_unknown_build_reads_hand_written_subtitles(self) -> None:
        """The safe default: every build that predates this mapping.

        Defaulting the other way would silently widen an existing build the
        first time someone added a name here.
        """
        self.assertEqual(sources_for("subtitle:something-new"), MANUAL)
        self.assertEqual(sources_for(""), MANUAL)


class SubtitleSourceTest(unittest.TestCase):
    def test_it_asks_for_one_kind_of_transcript(self) -> None:
        db = _Db()
        SubtitleSource(db, "de", ("auto",)).lines()
        self.assertIn("transcript_source", db.sql)
        self.assertEqual(db.params, ("de", ["auto"]))

    def test_hand_written_is_what_it_asks_for_unasked(self) -> None:
        """The default matters more than the parameter.

        Every caller that existed before this argument did means `manual`,
        and one that forgets to pass it must not quietly read everything.
        """
        db = _Db()
        SubtitleSource(db, "de").lines()
        self.assertEqual(db.params, ("de", ["manual"]))


class BuildOfTest(unittest.TestCase):
    def test_it_agrees_with_the_corpus_mapping(self) -> None:
        """`BUILD_OF` and `BUILD_SOURCES` are one fact written twice.

        Ingest reads it as "this video feeds that build"; the corpus reads it
        as "that build is made of these videos". If they disagree, a video is
        written to the catalogue and then analysed into a build that will
        never look for it — it simply never appears, with nothing raised.
        """
        for transcript_source, build in BUILD_OF.items():
            self.assertEqual(sources_for(build), (transcript_source,))


if __name__ == "__main__":
    unittest.main()
