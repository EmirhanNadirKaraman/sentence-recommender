"""The plan as a document you can read straight through.

The PDF and the PPTX divide the work rather than duplicating it. A slideshow
shows one step at a time, which is how you drill; a document shows many at
once, which is how you skim, print, or find the step where a word you half
remember was taught. So this packs cards down the page and the slide writer
gives each one a screen.

The translation is set in grey under the German rather than in a column
beside it, so a sheet of paper folded lengthwise hides every translation at
once and the page is still a usable test.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer)

from deck import Card

# Helvetica is one of the fonts every PDF reader is required to have, and it
# covers the umlauts and the eszett. Embedding a file would make the deck
# several megabytes larger to say the same thing.
BODY = "Helvetica"
BOLD = "Helvetica-Bold"


def _styles() -> dict[str, ParagraphStyle]:
    return {
        "word": ParagraphStyle(
            "word", fontName=BOLD, fontSize=11, leading=14,
            textColor=colors.HexColor("#111111"), spaceAfter=1),
        "sentence": ParagraphStyle(
            "sentence", fontName=BODY, fontSize=10.5, leading=14.5,
            textColor=colors.HexColor("#1a1a1a"), alignment=TA_LEFT),
        "translation": ParagraphStyle(
            "translation", fontName=BODY, fontSize=9, leading=12,
            textColor=colors.HexColor("#777777")),
        "means": ParagraphStyle(
            "means", fontName=BODY, fontSize=9.5, leading=12.5,
            textColor=colors.HexColor("#1f6fb2"), leftIndent=0,
            spaceBefore=1),
        "waiting": ParagraphStyle(
            "waiting", fontName=BODY, fontSize=8, leading=10,
            textColor=colors.HexColor("#c0392b")),
        "note": ParagraphStyle(
            "note", fontName=BODY, fontSize=8, leading=10,
            textColor=colors.HexColor("#a04000")),
        "title": ParagraphStyle(
            "title", fontName=BOLD, fontSize=22, leading=26,
            textColor=colors.HexColor("#111111"), spaceAfter=8),
        "subtitle": ParagraphStyle(
            "subtitle", fontName=BODY, fontSize=11, leading=16,
            textColor=colors.HexColor("#555555")),
    }


def _furniture(label: str):
    """Page number and plan name along the bottom of every page."""
    def draw(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(BODY, 7.5)
        canvas.setFillColor(colors.HexColor("#999999"))
        canvas.drawString(18 * mm, 12 * mm, label)
        canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, str(doc.page))
        canvas.restoreState()
    return draw


def write_pdf(cards: list[Card], path: Path, label: str,
              stamp: str | None = None) -> Path:
    """Write the deck as a PDF, one block per step.

    `KeepTogether` per card, so a step never has its sentence on one page and
    its translation on the next -- which is the one thing that would make the
    fold-the-page test stop working.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    style = _styles()
    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"{label} — {len(cards)} steps", author="sentence-recommender",
    )

    flow: list = [
        Paragraph("Sentences in teaching order", style["title"]),
        Paragraph(
            f"{label}<br/>{len(cards):,} steps · built {date.today():%-d %B %Y}"
            + (f"<br/>corpus stamp {escape(stamp)}" if stamp else ""),
            style["subtitle"]),
        Paragraph(
            "Every sentence is i+1 at the point it appears: apart from the "
            "word in bold, every word in it has been taught by an earlier "
            "step or was known at the start. Under each sentence is its "
            "English, and in blue what the word means there — stated once "
            "per sense, so a second blue line means the word has shifted "
            "meaning.", style["subtitle"]),
        PageBreak(),
    ]

    for card in cards:
        block: list = [
            Paragraph(
                f'<font color="#bbbbbb">{card.position}</font>&nbsp;&nbsp;'
                f"{escape(card.spoken)}"
                + ('&nbsp;<font size="7" color="#999999">PATTERN</font>'
                   if card.is_pattern else ""),
                style["word"]),
        ]
        if card.beside:
            # Not i+1, and the reader is owed the difference rather than
            # meeting an unexplained second new word in the sentence.
            block.append(Paragraph(
                f"taught together with {escape(card.beside)}", style["note"]))
        if not card.glossed:
            # Said plainly, because an ungloss'd card and a card the model
            # answered sparsely look identical otherwise — and one needs a
            # rerun while the other is finished.
            block.append(Paragraph("awaiting the model", style["waiting"]))

        said_already: str | None = None
        for example in card.examples:
            block.append(Paragraph(escape(example.text), style["sentence"]))
            if example.translation:
                block.append(Paragraph(escape(example.translation),
                                       style["translation"]))
            # The sense, once per sense rather than once per sentence. The
            # model groups the examples by meaning and gives each group the
            # same words, so repeating them under every sentence would say
            # the same thing three times -- and a word that genuinely shifts
            # meaning between examples still gets a second line, exactly
            # where it shifts.
            if example.means and example.means != said_already:
                block.append(Paragraph(escape(example.means), style["means"]))
                said_already = example.means
            block.append(Spacer(1, 3))
        block.append(Spacer(1, 7))
        flow.append(KeepTogether(block))

    draw = _furniture(label)
    doc.build(flow, onFirstPage=draw, onLaterPages=draw)
    return path
