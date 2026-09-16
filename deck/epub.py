"""The plan as a book you can read on a phone.

The PDF is a fixed page: it is right for printing and wrong for a phone,
where a reader wants text that reflows to the screen it is on and a table of
contents it can jump around in. An EPUB is that, and it is a ZIP of XHTML
with a manifest -- so it is written here directly rather than through a
library. Nothing else in the project needs one, and `zipfile` is already in
the standard library.

The typography follows the PDF for the same reason the PDF chose it: the
translation is set in grey under the German, so a thumb over the lower line
leaves a usable test. What a word means in *that* sentence is set apart
again, because it is the one line on the card that changes between examples.

Split into chapters of a hundred steps. One XHTML file holding all 3,902
cards parses slowly on a phone and makes every reader scroll from the start;
a hundred is small enough to open instantly and large enough that the
contents list stays readable.
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from deck import Card

PER_CHAPTER = 100

# Grey enough to recede on a bright phone in daylight, dark enough to read.
# The same two greys the PDF uses, so the two documents look like one deck.
STYLE = """\
html { -webkit-hyphens: auto; hyphens: auto; }
body { margin: 0 6%; font-family: Georgia, "Times New Roman", serif;
       line-height: 1.5; }
h1 { font-size: 1.4em; margin: 1.4em 0 0.8em; font-weight: normal;
     letter-spacing: 0.02em; }
h2 { font-size: 1em; margin: 0; font-weight: bold; page-break-after: avoid; }
/* One word to a page. A reader flicking through a deck wants the next
   word to start where the last one ended, not three lines down a page it
   is sharing — and on a phone a card that straddles a page turn hides
   either its word or its last example. `break-*` beside `page-break-*`
   because readers are split between the two spellings. */
.card { margin: 0; page-break-inside: avoid; break-inside: avoid;
        page-break-before: always; break-before: page; }
/* Except the first on a chapter, which would otherwise leave the heading
   alone on a page of its own. */
.card:first-of-type { page-break-before: avoid; break-before: avoid; }
.step { font-size: 0.75em; color: #999999; letter-spacing: 0.08em;
        margin: 0 0 0.15em; }
.kind { font-size: 0.7em; color: #999999; letter-spacing: 0.08em;
        font-weight: normal; }
.beside { font-size: 0.8em; color: #a04000; margin: 0.2em 0 0; }
.de { margin: 0.55em 0 0; }
.en { margin: 0.1em 0 0; color: #777777; font-size: 0.92em; }
.means { margin: 0.15em 0 0; color: #2b5797; font-size: 0.88em;
         font-style: italic; }
.front { margin-top: 25%; text-align: center; }
.front p { color: #777777; font-size: 0.9em; }
nav ol { list-style: none; padding-left: 0; }
nav li { margin: 0.4em 0; }
"""


def _page(title: str, body: str) -> bytes:
    """One XHTML file. EPUB readers are strict, so this is real XHTML."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" lang="de">\n'
        f'<head><meta charset="utf-8"/><title>{escape(title)}</title>'
        '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
        f'<body>\n{body}</body>\n</html>\n'
    ).encode("utf-8")


def _card(card: Card) -> str:
    """One step: the word, then each sentence with its English and its sense."""
    kind = ' <span class="kind">PATTERN</span>' if card.is_pattern else ""
    out = ['<div class="card">',
           f'<p class="step">{card.position} of {card.total}</p>',
           f'<h2>{escape(card.word)}{kind}</h2>']
    if card.beside:
        # Not an i+1 step. The reader is owed the difference rather than
        # being handed a sentence with an unexplained second new word.
        out.append('<p class="beside">taught together with '
                   f'{escape(card.beside)}</p>')
    for example in card.examples:
        out.append(f'<p class="de">{escape(example.text)}</p>')
        if example.translation:
            out.append(f'<p class="en">{escape(example.translation)}</p>')
        if example.means:
            out.append(f'<p class="means">{escape(example.means)}</p>')
    out.append('</div>')
    return "\n".join(out)


def _chapters(cards: list[Card], per: int):
    """The deck in runs of `per`, each with the title it will be listed by."""
    for start in range(0, len(cards), per):
        block = cards[start:start + per]
        yield (f"Steps {block[0].position}–{block[-1].position}", block)


def _opf(title: str, book_id: str, names: list[str], titles: list[str]) -> bytes:
    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
        'properties="nav"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
        '<item id="front" href="front.xhtml" '
        'media-type="application/xhtml+xml"/>',
    ]
    spine = ['<itemref idref="front"/>', '<itemref idref="nav"/>']
    for index, name in enumerate(names):
        manifest.append(f'<item id="c{index}" href="{name}" '
                        'media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{index}"/>')
    # `dcterms:modified` is required by EPUB 3 and must be to the second.
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="bookid">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'<dc:identifier id="bookid">urn:uuid:{book_id}</dc:identifier>\n'
        f'<dc:title>{escape(title)}</dc:title>\n'
        '<dc:language>de</dc:language>\n'
        f'<meta property="dcterms:modified">'
        f'{date.today().isoformat()}T00:00:00Z</meta>\n'
        '</metadata>\n'
        f'<manifest>{"".join(manifest)}</manifest>\n'
        f'<spine>{"".join(spine)}</spine>\n'
        '</package>\n'
    ).encode("utf-8")


def write_epub(cards, path, stem: str = "", stamp: str | None = None,
               per_chapter: int = PER_CHAPTER) -> Path:
    """Write the deck to `path` as an EPUB 3 book."""
    path = Path(path)
    cards = list(cards)
    title = f"German roadmap · {len(cards):,} steps"
    book_id = hashlib.sha1((stem or title).encode("utf-8")).hexdigest()
    book_id = "-".join((book_id[:8], book_id[8:12], book_id[12:16],
                        book_id[16:20], book_id[20:32]))

    blocks = list(_chapters(cards, per_chapter))
    names = [f"chapter-{n:03d}.xhtml" for n in range(1, len(blocks) + 1)]
    titles = [heading for heading, _ in blocks]

    listed = "\n".join(
        f'<li><a href="{name}">{escape(heading)}</a></li>'
        for name, heading in zip(names, titles))
    nav = _page("Contents",
                '<h1>Contents</h1>\n<nav epub:type="toc" id="toc">\n'
                f'<ol>\n{listed}\n</ol>\n</nav>\n')

    said = [f'<p>{len(cards):,} steps, in the order they are taught.</p>']
    glossed = sum(1 for card in cards if card.glossed)
    if glossed < len(cards):
        # Said plainly rather than left for the reader to notice: a card with
        # no English is not a broken card, it is one the model has not been
        # asked about yet.
        said.append(f'<p>{len(cards) - glossed:,} of them have no English '
                    'yet.</p>')
    if stamp:
        said.append(f'<p>{escape(stamp)}</p>')
    front = _page(title, f'<div class="front">\n<h1>{escape(title)}</h1>\n'
                         + "\n".join(said) + '\n</div>\n')

    with ZipFile(path, "w", ZIP_DEFLATED) as book:
        # The mimetype has to be the first entry and stored uncompressed, or
        # a reader is entitled to refuse the file. `writestr` with its own
        # compress_type is the only way to make one entry differ.
        book.writestr("mimetype", "application/epub+zip",
                      compress_type=ZIP_STORED)
        book.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles>\n'
            '</container>\n')
        book.writestr("OEBPS/style.css", STYLE)
        book.writestr("OEBPS/front.xhtml", front)
        book.writestr("OEBPS/nav.xhtml", nav)
        book.writestr("OEBPS/content.opf", _opf(title, book_id, names, titles))
        for name, (heading, block) in zip(names, blocks):
            body = (f'<h1>{escape(heading)}</h1>\n'
                    + "\n".join(_card(card) for card in block) + "\n")
            book.writestr(f"OEBPS/{name}", _page(heading, body))
    return path
