"""The deck as an Anki package, for reviewing it away from a desk.

`deck.tsv` already imports — Anki understands `[sound:...]` — but it leaves
the media to be copied by hand into `collection.media`, which is fine on a
laptop and unpleasant on a train. An `.apkg` carries its audio inside it, so
it is one file to move and one tap to import.

The audio is re-encoded on the way in. 5.2 GB of WAV is not a thing to sync
to a phone; at 64 kbit mono the same deck is under a gigabyte and sounds no
different through earphones, because a single voice reading slowly is about
the easiest thing there is to compress.

Split into several packages rather than one. A single gigabyte import is slow
enough on a phone to look hung, and a deck you are halfway through is a
better thing to carry than one you have not managed to load.

The card asks the word and answers with everything else, which is the way
round that suits the plan: the roadmap teaches a word and the sentences are
what it means, so a prompt of `die Geschichte` and an answer carrying three
uses of it is the review the deck was built to support. The audio sits on the
answer rather than the question, because the clip says the word first and
would otherwise give itself away.
"""
from __future__ import annotations

import hashlib
import html
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Iterable

from deck import Card

# Anki identifies a model and a deck by number, and re-importing with the
# same number updates rather than duplicates. Derived from the name so the
# number is stable across runs without being written down anywhere.
def _id(name: str) -> int:
    digest = hashlib.sha256(name.encode()).hexdigest()
    return int(digest[:12], 16) % (1 << 31) + (1 << 30)


CSS = """
.card { font-family: -apple-system, Helvetica, Arial, sans-serif;
        font-size: 20px; text-align: left; color: #1a1a1a;
        background: #fafaf8; padding: 18px; }
.word { font-size: 30px; font-weight: 600; color: #1f6fb2; }
.pos { color: #bbb; font-size: 14px; }
.means { color: #1f6fb2; margin: 10px 0 18px; }
.de { margin-top: 14px; }
.en { color: #777; font-size: 17px; }
hr { border: none; border-top: 1px solid #e3e3e0; margin: 16px 0; }
"""

FRONT = '<div class="pos">{{Position}}</div><div class="word">{{Word}}</div>'
BACK = (FRONT + "<hr>{{Meaning}}{{Sentences}}<div>{{Audio}}</div>")


def sentences_html(card: Card) -> str:
    """The examples, with the meaning said once per sense as everywhere else."""
    out, said_already = [], None
    for example in card.examples:
        out.append(f'<div class="de">{html.escape(example.text)}</div>')
        if example.translation:
            out.append(f'<div class="en">{html.escape(example.translation)}</div>')
        if example.means and example.means != said_already:
            out.append(f'<div class="en" style="color:#1f6fb2">'
                       f'{html.escape(example.means)}</div>')
            said_already = example.means
    return "".join(out)


def first_meaning(card: Card) -> str:
    for example in card.examples:
        if example.means:
            return f'<div class="means">{html.escape(example.means)}</div>'
    return ""


def to_mp3(source: Path, target: Path, bitrate: str = "64k") -> Path:
    """One clip, re-encoded. Skipped when it is already there."""
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
         "-codec:a", "libmp3lame", "-b:a", bitrate, "-ac", "1", str(target)],
        capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"ffmpeg failed on {source.name}:\n{done.stderr[:300]}")
    return target


def build(cards: list[Card], audio_dir: Path, out_dir: Path, name: str,
          per_package: int = 500, bitrate: str = "64k",
          on_progress: Callable[[int, int], None] | None = None,
          every: int = 50) -> list[Path]:
    """Write one `.apkg` per chunk of `per_package` cards."""
    import genanki                                       # noqa: PLC0415

    if shutil.which("ffmpeg") is None:
        raise SystemExit(
            "ffmpeg is needed to re-encode the audio and is not installed — "
            "`brew install ffmpeg`")
    model = genanki.Model(
        _id(f"{name}/model"), "Sentence roadmap",
        fields=[{"name": "Position"}, {"name": "Word"}, {"name": "Meaning"},
                {"name": "Sentences"}, {"name": "Audio"}],
        templates=[{"name": "Word to meaning", "qfmt": FRONT, "afmt": BACK}],
        css=CSS,
    )
    media_dir = out_dir / "media"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    done = 0
    for start in range(0, len(cards), per_package):
        chunk = cards[start:start + per_package]
        part = len(written) + 1
        title = (f"{name}::{part:02d} — {chunk[0].position}-"
                 f"{chunk[-1].position}")
        anki_deck = genanki.Deck(_id(title), title)
        media: list[str] = []
        for card in chunk:
            clip = audio_dir / f"{card.stem}.wav"
            sound = ""
            if clip.exists():
                mp3 = to_mp3(clip, media_dir / f"{card.stem}.mp3", bitrate)
                media.append(str(mp3))
                sound = f"[sound:{mp3.name}]"
            # Position first, because Anki sorts a note by its first field
            # and that is what should put the browser in teaching order.
            # Written plainly rather than zero-padded: Anki's `sfld` column
            # has integer affinity, so SQLite stores `412` as a number and
            # orders it numerically — checked across 1, 10, 100 and 1000
            # rather than assumed, since a text sort there would list a
            # 3,902-card deck as 1, 10, 100, 1000, 11.
            anki_deck.add_note(genanki.Note(
                model=model,
                fields=[str(card.position), html.escape(card.spoken),
                        first_meaning(card), sentences_html(card), sound],
            ))
            done += 1
            if on_progress and (done % every == 0 or done == len(cards)):
                on_progress(done, len(cards))
        package = genanki.Package(anki_deck)
        package.media_files = media
        path = out_dir / f"{name.replace(' ', '-')}-{part:02d}.apkg"
        package.write_to_file(str(path))
        written.append(path)
    return written
