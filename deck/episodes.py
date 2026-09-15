"""The deck as episodes you can listen to, with chapters you can seek by.

Three thousand nine hundred clips of half a minute each is not a thing anyone
plays. Joined into episodes of fifty it is twenty-three minutes a sitting,
which is a walk — and every word keeps a timestamp, so the episode is
seekable rather than a wall of audio.

The timestamps are the format YouTube reads out of a description: one
`M:SS Title` per line, the first at `0:00`. That is also what a podcast
chapter list wants, so the same file serves either.

Joining is done here rather than by calling out to a converter, because
every clip this project writes is 16-bit mono at one rate and appending
frames is all that joining such files means. ffmpeg is wanted only for what
it is actually good at -- compressing to MP3, or laying stills over the
audio -- and neither is needed to listen.

Durations are measured from the files rather than from what was intended.
A clip that failed to write, or wrote short, would otherwise push every
timestamp after it out of step, and a chapter list that is slightly wrong is
harder to notice than one that is obviously broken.
"""
from __future__ import annotations

import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from deck import Card

PER_EPISODE = 50


def timestamp(seconds: float) -> str:
    """`0:00`, `9:59`, `1:02:03` — what YouTube parses from a description.

    Hours are written only when there are any: `1:05` means one minute five
    to a reader and to YouTube, and writing `0:01:05` for it is both uglier
    and a chapter title away from being misread.
    """
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


@dataclass(frozen=True)
class Chapter:
    at: float
    card: Card

    def line(self) -> str:
        return f"{timestamp(self.at)} {self.card.spoken}"


@dataclass(frozen=True)
class Episode:
    number: int
    chapters: tuple[Chapter, ...]
    seconds: float

    @property
    def stem(self) -> str:
        return f"episode-{self.number:02d}"

    def description(self) -> str:
        """The chapter list, ready to paste into a description.

        YouTube wants the first at 0:00 and at least three of them, which is
        satisfied by any episode of any sensible length; a final short
        episode with one or two words would not be, and says so rather than
        producing a list that silently fails to become chapters.
        """
        head = (f"Words {self.chapters[0].card.position}–"
                f"{self.chapters[-1].card.position} of the roadmap, in "
                "teaching order.\n\n")
        if len(self.chapters) < 3:
            head += ("(Too few chapters for YouTube, which wants at least "
                     "three.)\n\n")
        return head + "\n".join(chapter.line() for chapter in self.chapters)


def concat_list(episode: "Episode", stills_dir: Path, path: Path) -> Path:
    """ffmpeg's concat demuxer, one still held for its own clip's length.

    The last entry is repeated without a duration, which is what the demuxer
    wants: it reads a `duration` as the gap until the *next* file, so the
    final image would otherwise flash for one frame and end the video before
    its audio.
    """
    lines = []
    for at, chapter in enumerate(episode.chapters):
        still = (stills_dir / f"{chapter.card.stem}.png").resolve()
        ends = (episode.chapters[at + 1].at if at + 1 < len(episode.chapters)
                else episode.seconds)
        lines.append(f"file '{still}'")
        lines.append(f"duration {ends - chapter.at:.3f}")
    last = (stills_dir / f"{episode.chapters[-1].card.stem}.png").resolve()
    lines.append(f"file '{last}'")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_video(episode: "Episode", stills_dir: Path, audio: Path,
                out_dir: Path, fps: int = 5) -> Path:
    """One episode as an MP4: its stills over its audio.

    Five frames a second, because nothing moves. libx264 with `stillimage`
    tuning turns that into a file dominated by its audio rather than its
    video, which is the right shape for something that is really a recording
    with pictures.

    `-shortest` so a rounding difference between the concat list and the WAV
    cannot leave a second of silence on a black frame at the end.
    """
    if shutil.which("ffmpeg") is None:
        raise SystemExit(
            "ffmpeg is needed to write video and is not installed — "
            "`brew install ffmpeg`. The audio and chapter files are written "
            "without it.")
    out_dir.mkdir(parents=True, exist_ok=True)
    listing = concat_list(episode, stills_dir, out_dir / f"{episode.stem}.txt.concat")
    video = out_dir / f"{episode.stem}.mp4"
    done = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", str(listing),
         "-i", str(audio),
         "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
         "-pix_fmt", "yuv420p", "-r", str(fps),
         "-c:a", "aac", "-b:a", "128k", "-shortest", str(video)],
        capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"ffmpeg failed on {episode.stem}:\n{done.stderr[:400]}")
    listing.unlink()
    return video


def _duration(path: Path) -> float:
    with wave.open(str(path)) as handle:
        return handle.getnframes() / handle.getframerate()


def plan(cards: Iterable[Card], audio_dir: Path,
         per: int = PER_EPISODE) -> list[Episode]:
    """Group the cards that have audio into episodes, timing each one."""
    have = [(card, audio_dir / f"{card.stem}.wav") for card in cards]
    have = [(card, path) for card, path in have if path.exists()]
    out: list[Episode] = []
    for index in range(0, len(have), per):
        at = 0.0
        chapters = []
        for card, path in have[index:index + per]:
            chapters.append(Chapter(at, card))
            at += _duration(path)
        out.append(Episode(len(out) + 1, tuple(chapters), at))
    return out


def write(episode: Episode, audio_dir: Path, out_dir: Path) -> tuple[Path, Path]:
    """One episode: the joined audio, and its chapters beside it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    audio = out_dir / f"{episode.stem}.wav"
    first = audio_dir / f"{episode.chapters[0].card.stem}.wav"
    with wave.open(str(first)) as probe:
        params = probe.getparams()
    with wave.open(str(audio), "wb") as joined:
        joined.setnchannels(params.nchannels)
        joined.setsampwidth(params.sampwidth)
        joined.setframerate(params.framerate)
        for chapter in episode.chapters:
            with wave.open(str(audio_dir / f"{chapter.card.stem}.wav")) as one:
                if (one.getnchannels(), one.getsampwidth(),
                        one.getframerate()) != (params.nchannels,
                                                params.sampwidth,
                                                params.framerate):
                    raise SystemExit(
                        f"{chapter.card.stem}.wav does not match the others — "
                        "joining frames needs one format throughout")
                joined.writeframes(one.readframes(one.getnframes()))
    chapters = out_dir / f"{episode.stem}.txt"
    chapters.write_text(episode.description() + "\n", encoding="utf-8")
    return audio, chapters
