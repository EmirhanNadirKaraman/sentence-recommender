"""A card as a still, so a video of the deck is worth looking at.

YouTube needs a video track whether or not you have anything to show, and the
usual answer is one motionless image for an hour. That wastes the one thing a
video adds: the reader can *see* the sentence while hearing it, which is how
a written form and a spoken form get attached to each other.

So each card is drawn once and held for exactly as long as its own clip. The
layout follows the slideshow deliberately — the same four things in the same
order, the same colours — because they are the same card, and a learner
moving between the PDF, the slides and the video should not have to relearn
where to look.

Drawn with Pillow rather than by rendering the PDF, because the sizes differ
by an order of magnitude: a page is sized for paper and a frame for a screen,
and scaling one into the other gives either hairlines or mush.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from deck import Card

# 1080p, which is what YouTube wants and what a phone will play without
# re-encoding on the way.
SIZE = (1920, 1080)
MARGIN = 110

PAPER = (250, 250, 248)
INK = (26, 26, 26)
QUIET = (140, 140, 140)
ACCENT = (31, 111, 178)
WARN = (160, 64, 0)

# Fonts that exist on a Mac and cover the umlauts and the eszett. Pillow's
# built-in is a bitmap face at one small size, so a missing file has to be
# noticed rather than silently accepted.
FACES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Verdana.ttf",
    "/System/Library/Fonts/Geneva.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
BOLD_FACES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Verdana Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _face(size: int, bold: bool = False):
    for path in (BOLD_FACES if bold else FACES):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    for path in FACES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit(
        "no usable font found for the card stills — looked in "
        + ", ".join(FACES))


def _wrap(draw, text: str, font, width: int) -> list[str]:
    """Break a line to fit, on spaces, measuring rather than counting.

    German compounds are long and a character count guesses badly at them:
    `Geschwindigkeitsbegrenzung` is one word wider than six ordinary ones.
    """
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _plan(draw, card: Card, width: int) -> tuple[list, int]:
    """The card's lines and the size they had to shrink to in order to fit.

    Tried largest first and stepped down until the whole card is inside the
    frame. A fixed size either wastes half the screen on a short card or
    pushes a long one off the bottom, where nothing reports it.
    """
    for scale in (1.0, 0.86, 0.74, 0.62, 0.52):
        body = int(46 * scale)
        small = int(36 * scale)
        gap = int(22 * scale)
        lines: list[tuple[str, object, tuple[int, int, int], int]] = []
        said_already = None
        for example in card.examples:
            font = _face(body)
            for part in _wrap(draw, example.text, font, width):
                lines.append((part, font, INK, body + 8))
            if example.translation:
                font = _face(small)
                for part in _wrap(draw, example.translation, font, width):
                    lines.append((part, font, QUIET, small + 6))
            if example.means and example.means != said_already:
                font = _face(small)
                for part in _wrap(draw, example.means, font, width):
                    lines.append((part, font, ACCENT, small + 6))
                said_already = example.means
            lines.append(("", _face(small), QUIET, gap))
        height = sum(step for _, _, _, step in lines)
        if height <= SIZE[1] - MARGIN * 2 - 170:
            return lines, height
    return lines, height


def draw_card(card: Card, path: Path) -> Path:
    """Write one card as a 1080p still."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", SIZE, PAPER)
    draw = ImageDraw.Draw(image)
    width = SIZE[0] - MARGIN * 2

    head = _face(74, bold=True)
    draw.text((MARGIN, MARGIN - 20), card.spoken, font=head, fill=ACCENT)
    if card.beside:
        draw.text((MARGIN + draw.textlength(card.spoken, font=head) + 30,
                   MARGIN + 18), f"+ {card.beside}", font=_face(30), fill=WARN)

    lines, height = _plan(draw, card, width)
    # Centred in what is left under the word rather than stacked at the top.
    # A short card top-aligned leaves a third of a 1080p frame empty, which
    # reads as a broken slide rather than a brief one.
    top = MARGIN + 150
    room = SIZE[1] - MARGIN - top
    y = top + max((room - height) // 2, 0)
    for text, font, colour, step in lines:
        if text:
            draw.text((MARGIN, y), text, font=font, fill=colour)
        y += step

    mark = f"{card.position} / {card.total}"
    small = _face(28)
    draw.text((SIZE[0] - MARGIN - draw.textlength(mark, font=small),
               SIZE[1] - MARGIN + 20), mark, font=small, fill=QUIET)
    image.save(path)
    return path
