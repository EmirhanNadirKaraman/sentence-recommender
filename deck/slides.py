"""The plan as a slideshow, one step to a screen.

Where the PDF packs steps down a page to be skimmed, this gives each one a
screen to be drilled. The German is the only thing on the slide at full size;
the word heads it, and under it every sentence that teaches the word, each
with its English and — once per sense rather than once per sentence — what
the word means there. A second blue line therefore means the word has
shifted meaning between examples, which is the one thing a learner has to
notice and the one thing a single hedged gloss would hide.

Text is sized from the length of the sentence rather than fixed. The corpus
runs from three words to thirty, and a size that suits the short ones sends
the long ones off the bottom of the slide where nothing reports it.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from deck import Card

# 16:9, which is what a laptop and a phone both are. The default template is
# 4:3 and letterboxes on everything made this decade.
WIDE = (Inches(13.333), Inches(7.5))

INK = RGBColor(0x1A, 0x1A, 0x1A)
QUIET = RGBColor(0x99, 0x99, 0x99)
ACCENT = RGBColor(0x1F, 0x6F, 0xB2)
WARN = RGBColor(0xA0, 0x40, 0x00)
MISSING = RGBColor(0xC0, 0x39, 0x2B)
PAPER = RGBColor(0xFA, 0xFA, 0xF8)


def _size_for(text: str) -> int:
    """Point size that keeps a sentence on the slide.

    Thresholds rather than a formula: the jump from 40pt to 32pt is where a
    two-line sentence becomes a three-line one, and a smooth curve puts the
    break in a different place on every slide.
    """
    n = len(text)
    if n <= 40:
        return 44
    if n <= 80:
        return 36
    if n <= 130:
        return 30
    return 24


def _textbox(slide, left, top, width, height, align=PP_ALIGN.LEFT):
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    frame.paragraphs[0].alignment = align
    return frame


def _run(frame, text: str, size: int, colour: RGBColor, bold: bool = False):
    run = frame.paragraphs[0].add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = colour
    run.font.name = "Helvetica Neue"
    return run


def _paint(slide, colour: RGBColor) -> None:
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = colour


def write_pptx(cards: list[Card], path: Path, label: str,
               stamp: str | None = None) -> Path:
    """Write the deck as a PowerPoint file, one slide per step."""
    path.parent.mkdir(parents=True, exist_ok=True)
    prs = Presentation()
    prs.slide_width, prs.slide_height = WIDE
    blank = prs.slide_layouts[6]

    title = prs.slides.add_slide(blank)
    _paint(title, PAPER)
    frame = _textbox(title, Inches(1), Inches(2.4), Inches(11.3), Inches(1.4))
    _run(frame, "Sentences in teaching order", 40, INK, bold=True)
    frame = _textbox(title, Inches(1), Inches(3.8), Inches(11.3), Inches(2))
    _run(frame, f"{label}\n{len(cards):,} steps · built "
                f"{date.today():%-d %B %Y}" + (f"\ncorpus stamp {stamp}"
                                               if stamp else ""), 16, QUIET)

    for card in cards:
        slide = prs.slides.add_slide(blank)
        _paint(slide, PAPER)

        frame = _textbox(slide, Inches(0.9), Inches(0.5), Inches(11.5),
                         Inches(0.9))
        _run(frame, card.spoken, 34, ACCENT, bold=True)
        if card.beside:
            # Not i+1. Said on the slide, not only in the notes, because it
            # changes what the slide is asking of the reader.
            _run(frame, f"   + {card.beside}", 15, WARN)
        if not card.glossed:
            _run(frame, "   awaiting the model", 13, MISSING)

        # Every example on the one slide, because the card is the word and
        # the three sentences are what it means. Sized from how much there is
        # to fit rather than fixed: a card with three long sentences and two
        # senses carries twice the text of a short one.
        body = _textbox(slide, Inches(0.9), Inches(1.6), Inches(11.5),
                        Inches(5.2), align=PP_ALIGN.LEFT)
        body.vertical_anchor = MSO_ANCHOR.TOP
        weight = sum(len(e.text) + len(e.translation or "")
                     for e in card.examples)
        size = 20 if weight <= 240 else 17 if weight <= 400 else 14
        said_already: str | None = None
        first = True
        for example in card.examples:
            para = body.paragraphs[0] if first else body.add_paragraph()
            para.space_before = Pt(0 if first else 10)
            first = False
            run = para.add_run()
            run.text = example.text
            run.font.size, run.font.color.rgb = Pt(size), INK
            if example.translation:
                line = body.add_paragraph()
                run = line.add_run()
                run.text = example.translation
                run.font.size, run.font.color.rgb = Pt(size - 3), QUIET
            # Once per sense, not once per sentence — see `deck.pdf` for why.
            if example.means and example.means != said_already:
                line = body.add_paragraph()
                run = line.add_run()
                run.text = example.means
                run.font.size, run.font.color.rgb = Pt(size - 3), ACCENT
                said_already = example.means

        frame = _textbox(slide, Inches(10.4), Inches(6.7), Inches(2.2),
                         Inches(0.5), align=PP_ALIGN.RIGHT)
        _run(frame, f"{card.position} / {card.total}", 12, QUIET)

        # The audio filename, which is the only place the two halves of the
        # deck are written down together.
        slide.notes_slide.notes_text_frame.text = f"audio: {card.stem}.wav"

    prs.save(str(path))
    return path
