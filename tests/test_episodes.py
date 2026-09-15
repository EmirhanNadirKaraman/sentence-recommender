"""Clips joined into episodes, with timestamps you can seek by.

Three thousand nine hundred clips of half a minute is not a thing anyone
plays; fifty of them is a walk. The timestamps are the part that has to be
exactly right — a chapter list slightly out of step is harder to notice than
one that is obviously broken, and it drifts worse the further into the
episode you go.
"""
from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from deck import Card, Example
from deck.episodes import (Chapter, concat_list, plan, timestamp,
                           write)

RATE = 22050


def clip(path: Path, seconds: float, rate: int = RATE,
         channels: int = 1, width: int = 2) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(b"\x01\x00" * int(seconds * rate))


def card(position: int, word: str = "wort") -> Card:
    return Card(position, word, False,
                (Example("Satz.", "Sentence.", f"{word} means word."),),
                None, 100)


class TimestampTest(unittest.TestCase):
    def test_it_starts_at_zero(self) -> None:
        """YouTube reads a description as chapters only when the first is
        0:00."""
        self.assertEqual(timestamp(0), "0:00")

    def test_minutes_and_seconds(self) -> None:
        self.assertEqual(timestamp(27.1), "0:27")
        self.assertEqual(timestamp(59.9), "0:59")
        self.assertEqual(timestamp(60), "1:00")
        self.assertEqual(timestamp(1355), "22:35")

    def test_hours_appear_only_when_there_are_any(self) -> None:
        """`1:05` means one minute five to a reader and to YouTube."""
        self.assertEqual(timestamp(65), "1:05")
        self.assertEqual(timestamp(3723), "1:02:03")

    def test_a_chapter_line_is_a_timestamp_and_a_word(self) -> None:
        self.assertEqual(Chapter(90, card(7, "die Zeit")).line(),
                         "1:30 die Zeit")


class PlanTest(unittest.TestCase):
    def test_chapters_follow_the_real_durations(self) -> None:
        """Measured from the files, not from what was intended: a clip that
        wrote short would push every later timestamp out of step."""
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp)
            cards = [card(i) for i in range(1, 4)]
            for at, seconds in zip(cards, (10.0, 5.0, 20.0)):
                clip(audio / f"{at.stem}.wav", seconds)
            episodes = plan(cards, audio, per=50)
        self.assertEqual([c.at for c in episodes[0].chapters], [0.0, 10.0, 15.0])
        self.assertEqual(episodes[0].seconds, 35.0)

    def test_it_splits_at_the_episode_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp)
            cards = [card(i) for i in range(1, 8)]
            for one in cards:
                clip(audio / f"{one.stem}.wav", 1.0)
            episodes = plan(cards, audio, per=3)
        self.assertEqual([len(e.chapters) for e in episodes], [3, 3, 1])
        self.assertEqual([e.number for e in episodes], [1, 2, 3])

    def test_every_episode_starts_at_zero(self) -> None:
        """Each is its own video, so each restarts the clock."""
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp)
            cards = [card(i) for i in range(1, 7)]
            for one in cards:
                clip(audio / f"{one.stem}.wav", 3.0)
            episodes = plan(cards, audio, per=2)
        self.assertEqual([e.chapters[0].at for e in episodes], [0.0, 0.0, 0.0])

    def test_a_card_with_no_clip_is_left_out(self) -> None:
        """Left out rather than given a timestamp, which would point at
        whatever audio happened to be there instead."""
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp)
            cards = [card(1), card(2), card(3)]
            clip(audio / f"{cards[0].stem}.wav", 4.0)
            clip(audio / f"{cards[2].stem}.wav", 4.0)
            episodes = plan(cards, audio, per=50)
        self.assertEqual([c.card.position for c in episodes[0].chapters], [1, 3])


class WriteTest(unittest.TestCase):
    def test_the_joined_audio_is_as_long_as_its_parts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio, out = Path(tmp) / "in", Path(tmp) / "out"
            audio.mkdir()
            cards = [card(i) for i in range(1, 4)]
            for one in cards:
                clip(audio / f"{one.stem}.wav", 2.0)
            episode = plan(cards, audio, per=50)[0]
            joined, chapters = write(episode, audio, out)
            with wave.open(str(joined)) as handle:
                seconds = handle.getnframes() / handle.getframerate()
            # Inside the block: the directory is gone by the time it exits.
            self.assertTrue(chapters.exists())
        self.assertAlmostEqual(seconds, 6.0, places=3)

    def test_the_chapter_file_is_paste_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio, out = Path(tmp) / "in", Path(tmp) / "out"
            audio.mkdir()
            cards = [card(i, w) for i, w in
                     enumerate(("gehen", "die Zeit", "machen"), 1)]
            for one in cards:
                clip(audio / f"{one.stem}.wav", 30.0)
            episode = plan(cards, audio, per=50)[0]
            _, chapters = write(episode, audio, out)
            lines = chapters.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(lines[-3:], ["0:00 gehen", "0:30 die Zeit",
                                      "1:00 machen"])

    def test_too_few_chapters_says_so(self) -> None:
        """YouTube wants at least three, and a list that silently fails to
        become chapters is worse than one that warns."""
        with tempfile.TemporaryDirectory() as tmp:
            audio, out = Path(tmp) / "in", Path(tmp) / "out"
            audio.mkdir()
            cards = [card(1), card(2)]
            for one in cards:
                clip(audio / f"{one.stem}.wav", 5.0)
            episode = plan(cards, audio, per=50)[0]
        self.assertIn("at least", episode.description())

    def test_a_clip_in_another_format_is_refused(self) -> None:
        """Joining is appending frames, which is only true of one format."""
        with tempfile.TemporaryDirectory() as tmp:
            audio, out = Path(tmp) / "in", Path(tmp) / "out"
            audio.mkdir()
            cards = [card(1), card(2)]
            clip(audio / f"{cards[0].stem}.wav", 2.0)
            clip(audio / f"{cards[1].stem}.wav", 2.0, rate=16000)
            episode = plan(cards, audio, per=50)[0]
            with self.assertRaises(SystemExit):
                write(episode, audio, out)


class ConcatTest(unittest.TestCase):
    """The list ffmpeg reads to hold each still for its own clip.

    Every timestamp in the chapter list is a promise about where a word is,
    and the concat durations are the same promise made to the encoder. They
    have to agree exactly or the video drifts out of step with its chapters.
    """

    def _episode(self, tmp: Path, lengths):
        audio = tmp / "audio"
        audio.mkdir()
        cards = [card(i) for i in range(1, len(lengths) + 1)]
        for one, secs in zip(cards, lengths):
            clip(audio / f"{one.stem}.wav", secs)
        return plan(cards, audio, per=50)[0]

    def test_durations_add_up_to_the_episode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            episode = self._episode(Path(tmp), (10.0, 5.0, 20.0))
            listing = concat_list(episode, Path("/stills"),
                                  Path(tmp) / "e.concat")
            text = listing.read_text(encoding="utf-8")
        said = [float(line.split()[1]) for line in text.splitlines()
                if line.startswith("duration")]
        self.assertEqual(said, [10.0, 5.0, 20.0])
        self.assertAlmostEqual(sum(said), episode.seconds, places=3)

    def test_the_last_still_is_repeated_without_a_duration(self) -> None:
        """The demuxer reads a duration as the gap to the *next* file, so
        without the repeat the final card shows for one frame."""
        with tempfile.TemporaryDirectory() as tmp:
            episode = self._episode(Path(tmp), (4.0, 6.0))
            listing = concat_list(episode, Path("/stills"),
                                  Path(tmp) / "e.concat")
            lines = listing.read_text(encoding="utf-8").strip().splitlines()
        self.assertTrue(lines[-1].startswith("file "))
        self.assertEqual(lines[-1], lines[-3])

    def test_a_still_is_named_for_its_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            episode = self._episode(Path(tmp), (4.0,))
            listing = concat_list(episode, Path("/stills"),
                                  Path(tmp) / "e.concat")
            text = listing.read_text(encoding="utf-8")
        self.assertIn(f"{episode.chapters[0].card.stem}.png", text)


class StillTest(unittest.TestCase):
    def test_a_card_is_drawn_at_1080p(self) -> None:
        from PIL import Image

        from deck import Example
        from deck.stills import SIZE, draw_card
        one = Card(412, "die Geschichte", True,
                   (Example("Was kann man aus der Geschichte lernen?",
                            "What can one learn from history?",
                            "die Geschichte means history."),), None, 3902)
        with tempfile.TemporaryDirectory() as tmp:
            path = draw_card(one, Path(tmp) / f"{one.stem}.png")
            with Image.open(path) as image:
                self.assertEqual(image.size, SIZE)

    def test_a_long_card_still_fits_the_frame(self) -> None:
        """Sized down until it does, rather than running off the bottom
        where nothing reports it."""
        from PIL import Image

        from deck import Example
        from deck.stills import SIZE, draw_card
        long = ("Die beiden kommen aus dem Sudan, studieren gerade in "
                "Deutschland und sie haben uns mit einem sehr interessanten "
                "Thema angesprochen.")
        one = Card(1, "jemanden auf etwas ansprechen", True,
                   tuple(Example(long, long, f"means {i}") for i in range(3)),
                   None, 3902)
        with tempfile.TemporaryDirectory() as tmp:
            path = draw_card(one, Path(tmp) / "x.png")
            with Image.open(path) as image:
                self.assertEqual(image.size, SIZE)


if __name__ == "__main__":
    unittest.main()
