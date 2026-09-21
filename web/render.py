"""The look of the local viewer.

The palette and structure come from a German school exercise book: cool
squared paper, königsblau fountain-pen ink for the text, and the red margin
rule down the left. That last one is load-bearing rather than decorative — it
separates the rail carrying step numbers from the reading column, which is
exactly what a margin is for. Red also means one thing here, the same thing it
means on returned schoolwork: a correction.

Typographic register carries the pedagogy: German in a reading face, the
interface and the English translations in a plainer one. The German is the
material; everything else is scaffolding.

Both used to be webfonts — Literata and Atkinson Hyperlegible. They are asked
of the device now. A phone reaching this over wifi with no route to the wider
internet spent the whole font timeout showing nothing, and a render-blocking
request to a third party is a poor trade for a face the reader has a close
match to already: Charter ships on Apple platforms and holds the same register.
Self-hosting the originals through `/static/` is the way back if the
difference is missed.
"""
from __future__ import annotations

import hashlib
from html import escape
from urllib.parse import quote
from pathlib import Path

STATIC = Path(__file__).resolve().parent / "static"

# The stylesheet is a file now rather than a string inlined into every page.
# It is twelve kilobytes, and a phone re-fetched all of it on every
# navigation — which, once a swipe becomes a page load, is every swipe.
#
# The hash is in the URL rather than a header, so it can be cached for a year
# and still change the moment it is edited: a different file is a different
# address. Read once, at import; the server is restarted to pick up code
# anyway.
def stamped(name: str) -> str:
    digest = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:12]
    return f"/static/{name}?v={digest}"

NAV = (("/", "Next"), ("/reels", "Reels"), ("/review", "Review"), ("/mine", "Mine"),
       ("/roadmap", "Roadmap"),
       ("/quiz", "Quiz"), ("/blocked", "Blocked"), ("/lists", "Lists"),
       ("/frontier", "Frontier"), ("/subtitles", "Videos"),
       ("/settings", "Settings"))


def layout(title: str, body: str, here: str = "/", source: str = "",
           wordlist: str = "") -> str:
    # Both carried, because a nav link that drops either one silently puts
    # the reader back on the default corpus or the default goal list, which
    # looks like the switch did not work.
    carried = [(k, v) for k, v in (("src", source), ("list", wordlist)) if v]
    suffix = ("?" + "&".join(f"{k}={quote(str(v), safe='')}"
                             for k, v in carried)) if carried else ""
    links = "".join(
        f'<a href="{href}{suffix}" class="{"here" if href == here else ""}">'
        f"{escape(label)}</a>"
        for href, label in NAV
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        # `viewport-fit=cover` lets the page paint under the notch and the
        # home indicator; the safe-area insets below put the content back.
        # No `user-scalable=no` — refusing to let someone zoom a page of
        # foreign-language text is the wrong call for this app in particular.
        "<meta name='viewport' content='width=device-width,initial-scale=1,"
        "viewport-fit=cover'>"
        f"<title>{escape(title)}</title>"
        "<meta name='apple-mobile-web-app-capable' content='yes'>"
        "<meta name='apple-mobile-web-app-title' content='i+1'>"
        # `default`, not `black-translucent`: the latter shifts content up
        # under the notch and brings a class of layout bugs with it.
        "<meta name='apple-mobile-web-app-status-bar-style' content='default'>"
        "<meta name='theme-color' content='#eef1f6' "
        "media='(prefers-color-scheme: light)'>"
        "<meta name='theme-color' content='#0f1626' "
        "media='(prefers-color-scheme: dark)'>"
        "<link rel='manifest' href='/manifest.webmanifest'>"
        "<link rel='apple-touch-icon' href='/static/icon-512.png'>"
        # Single quotes inside the braces: reusing the outer quote there is
        # also PEP 701, and this file has no other reason to demand 3.12.
        f"<link rel='stylesheet' href='{stamped('app.css')}'>"
        "</head><body>"
        "<header class='masthead'><div class='inner'>"
        f"<span class='name'>i+1</span>{links}</div></header>"
        f"<main>{body}</main></body></html>"
    )


def mark(text: str, surface: str | None) -> str:
    """The sentence with its one new thing marked.

    Escaped first, then the escaped needle is wrapped, so a word carrying
    markup characters cannot break out.

    A pattern's recorded surface is the span the matcher aligned, and its
    tokens are often not adjacent in the sentence — "wollen wir zum" never
    appears in "Heute wollen wir zum Edeka" once punctuation shifts. So when
    the whole span misses, each of its words is marked separately. Better to
    point at the right words in the wrong shape than at nothing.
    """
    safe = escape(text)
    if not surface:
        return safe
    whole = escape(surface)
    if whole in safe:
        return safe.replace(whole, f"<span class='target'>{whole}</span>", 1)
    for word in sorted(surface.split(), key=len, reverse=True):
        piece = escape(word)
        if piece and piece in safe:
            safe = safe.replace(piece, f"<span class='target'>{piece}</span>", 1)
    return safe


def sentence(text: str, translation: str | None, surface: str | None = None,
             lead: bool = False, level: str | None = None,
             words: list[list[str]] | None = None) -> str:
    """A sentence, its English under it, and the level the judge gave it
    — `B1` — after the German where one is known, so a reader can see why
    a sentence was picked over a harder one, or why this one is hard.

    With `words` — `[token, kind, key]` per token, as `web.handlers._words`
    reads them off a sentence — every word is a button that opens its
    gloss, as a subtitle's words do; the new word's tokens are marked in it
    as before. Without, the text is plain with the new word marked.
    """
    size = " lead" if lead else ""
    badge = f" <span class='level' title='the level the judge gave it'>{escape(level)}</span>" \
        if level else ""
    body = clickable(words, surface) if words else mark(text, surface)
    out = f"<p class='de{size}' data-text='{escape(text)}'>{body}{badge}</p>"
    if translation:
        out += f"<p class='en'>{escape(translation)}</p>"
    return out


def clickable(words: list[list[str]], surface: str | None) -> str:
    """Every word a button carrying its unit; the tokens of `surface` —
    the new word as the sentence says it — marked as the target."""
    wanted = {w.strip(".,;:!?„“”\"'()[]…-–—").lower() for w in (surface or "").split()}
    out = []
    for token, kind, key in words:
        bare = token.strip(".,;:!?„“”\"'()[]…-–—").lower()
        hit = " target" if bare and bare in wanted else ""
        out.append(f"<button type='button' class='w{hit}' data-kind='{escape(kind)}'"
                   f" data-key='{escape(key)}'>{escape(token)}</button>")
    return " ".join(out)
