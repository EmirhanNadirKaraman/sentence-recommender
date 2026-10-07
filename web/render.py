"""Shared learning workspace: navigation, page identity, and reading scaffolding.

System fonts and local SVGs keep the first paint independent of third-party
assets. Every route uses the same shell, including account and empty states.
"""
from __future__ import annotations

import hashlib
import threading
from html import escape
from urllib.parse import quote
from pathlib import Path

from vocab.entry import Unit

# Who the page being built is for. Set by the server at the start of each
# request -- each runs on a thread of its own -- and read by `layout`, so
# the masthead can say whose page this is without every handler passing it.
ACTIVE = threading.local()

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

NAV = (("/", "Learn"), ("/reels", "Reels"), ("/review", "Review"), ("/hear", "Listening"),
       ("/anki", "Anki cards"), ("/mine", "Writing"), ("/starred", "Saved sentences"),
       ("/roadmap", "Learning path"), ("/words", "Dictionary"), ("/quiz", "Vocabulary check"),
       ("/blocked", "Learning gaps"), ("/lists", "Word lists"), ("/frontier", "Next milestones"),
       ("/subtitles", "Video library"), ("/plan", "Watch plan"), ("/channels", "Channels"),
       ("/settings", "Settings"), ("/journey", "Your atlas"))

NAV_GROUPS = (
    ("YOUR PRACTICE", ("/", "/review", "/hear", "/mine", "/quiz")),
    ("EXPLORE", ("/reels", "/subtitles", "/channels")),
    ("YOUR COLLECTION", ("/starred", "/words", "/lists", "/anki")),
    ("YOUR JOURNEY", ("/journey", "/roadmap", "/plan", "/frontier", "/blocked", "/settings")),
)

ICON_PATHS = {
    "/": "M4 5h6a2 2 0 0 1 2 2v13a4 4 0 0 0-4-2H4z M20 5h-6a2 2 0 0 0-2 2v13a4 4 0 0 1 4-2h4z",
    "/review": "M4 10a8 8 0 1 1 2 8 M4 4v6h6 M12 8v5l3 2",
    "/hear": "M4 14v-3a8 8 0 0 1 16 0v3 M4 12h3v8H4z M17 12h3v8h-3z",
    "/mine": "m4 16 11-11 4 4-11 11-5 1z M13 7l4 4",
    "/quiz": "M9 5h10v16H5V5h4 M9 3h6v4H9z M8 13l2 2 5-5",
    "/reels": "M5 3h14v18H5z m5 5 5 4-5 4z",
    "/subtitles": "M3 5h18v14H3z m7 4 5 3-5 3z",
    "/channels": "M8 4h8 M5 8h14v12H5z m5 3 5 3-5 3z",
    "/starred": "m12 3 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1z",
    "/words": "M4 4h15v16H4z M8 8h7 M8 12h5 M19 4v16h2",
    "/lists": "M8 6h12 M8 12h12 M8 18h12 M4 6h.01 M4 12h.01 M4 18h.01",
    "/anki": "M4 7h13v14H4z M8 3h13v14 M8 12h5 M8 16h3",
    "/roadmap": "M6 4a2 2 0 1 0 0 .01 M18 20a2 2 0 1 0 0 .01 M6 8v4h12v4",
    "/plan": "M5 4h14v17H5z M8 9h8 M8 13h8 M8 17h4",
    "/frontier": "M4 20V4 M4 4h14l-3 4 3 4H4",
    "/blocked": "M4 20h16 M7 20V13h4v7 M13 20V6h4v14",
    "/journey": "m12 3 3 6 6 3-6 3-3 6-3-6-6-3 6-3z",
    "/settings": "M4 7h16 M4 17h16 M8 4v6 M16 14v6",
}


def icon(path: str) -> str:
    return ("<svg class='nav-icon' viewBox='0 0 24 24' fill='none' "
            "stroke='currentColor' stroke-width='1.7' stroke-linecap='round' "
            "stroke-linejoin='round' aria-hidden='true'>"
            f"<path d='{ICON_PATHS.get(path, ICON_PATHS['/'])}'/></svg>")


def welcome(suffix: str) -> str:
    """A clear next action, plus familiar alternatives, without invented stats."""
    return (
        "<section class='welcome' aria-labelledby='welcome-title'>"
        "<div class='welcome-copy'><span class='eyebrow'>ONE NEW WORD. A WHOLE NEW WORLD.</span>"
        "<h1 id='welcome-title'>Make yourself<br>at home in a language.</h1>"
        "<p>Real voices. Useful sentences. One small discovery at a time.</p>"
        "<a class='go' href='#reading-top'>Continue learning</a>"
        "<span class='welcome-foot'>Go at your own pace. Every word counts.</span></div>"
        "<div class='word-garden' aria-hidden='true'>"
        "<span class='garden-orbit'></span><span class='garden-spark'>✦</span>"
        "<span class='garden-card garden-back'>A little more,<small>every day.</small></span>"
        "<span class='garden-card garden-front'>i + <b>1</b><small>Your next discovery</small></span>"
        "<span class='garden-dot'></span></div></section>"
        "<section class='practice-paths' aria-label='Choose your practice'>"
        f"<a href='/review{suffix}' class='practice-path'>{icon('/review')}"
        "<span><strong>Make it stick</strong><small>Revisit words with spaced practice</small></span><span>↗</span></a>"
        f"<a href='/reels{suffix}' class='practice-path'>{icon('/reels')}"
        "<span><strong>Follow your curiosity</strong><small>Discover language in real videos</small></span><span>↗</span></a>"
        f"<a href='/mine{suffix}' class='practice-path'>{icon('/mine')}"
        "<span><strong>Make it yours</strong><small>Put your own thoughts into words</small></span><span>↗</span></a>"
        "</section>"
    )


# How many words may pile up before the nav stops being quiet about it.
ANKI_REMIND = 15


def layout(title: str, body: str, here: str = "/", source: str = "",
           wordlist: str = "", anki_new: int = 0, bare: bool = False, journey: dict | None = None) -> str:
    # Both carried, because a nav link that drops either one silently puts
    # the reader back on the default corpus or the default goal list, which
    # looks like the switch did not work.
    carried = [(k, v) for k, v in (("src", source), ("list", wordlist)) if v]
    suffix = ("?" + "&".join(f"{k}={quote(str(v), safe='')}"
                             for k, v in carried)) if carried else ""
    # The count of words queued and not yet exported rides on the Anki link,
    # because a reminder that lives on the Anki page is one only the person
    # already going there will read.
    def link(href: str, label: str) -> str:
        here_now = "here" if href == active_path else ""
        badge = ""
        if href == "/anki" and anki_new:
            due = " due" if anki_new >= ANKI_REMIND else ""
            badge = (f"<span class='badge{due}' title='queued since your last "
                     f"export'>{anki_new:,}</span>")
        return (f'<a href="{href}{suffix}" class="{here_now}"'
                + (' aria-current="page"' if here_now else "") + ">"
                f"{icon(href)}<span>{escape(label)}</span>{badge}</a>")

    labels = dict(NAV)
    active_path = here if here in labels else "/words" if here.startswith("/word/") else here
    groups = "".join(
        f"<div class='nav-group'><p>{heading}</p>"
        + "".join(link(path, labels[path]) for path in paths) + "</div>"
        for heading, paths in NAV_GROUPS
    )
    reader = getattr(ACTIVE, "reader", "") if getattr(ACTIVE, "shared", False) else ""
    account = (f"<div class='who'><span class='avatar'>{escape(reader[:1].upper())}</span>"
               f"<span>{escape(reader)}</span><form method='post' action='/logout'>"
               "<button type='submit'>Sign out</button></form></div>" if reader and not bare else "")
    brand = (f"<a class='brand' href='/{suffix}' aria-label='i+1 home'>"
             "<span class='brand-mark'>i<span>+1</span></span>"
             "<span>little by little<small>A LANGUAGE LEARNING SPACE</small></span></a>")
    shell = ("<header class='masthead'><div class='inner'>" + brand
             + "<nav class='desktop-nav' aria-label='Main navigation'>" + groups + "</nav>"
             + "<div class='rail-note'><span>✦</span><p>A little practice.<br>A little more possibility.</p></div>"
             + account + "</div></header>" if not bare else "<header class='auth-brand'>" + brand + "</header>")
    section = next((heading for heading, paths in NAV_GROUPS if active_path in paths), "YOUR LEARNING SPACE")
    current = labels.get(active_path, title)
    context = "".join(f"<span class='context-chip'>{escape(str(value).replace('_', ' '))}</span>"
                      for value in (source, wordlist) if value)
    toolbar = (f"<div class='workspace-top'><div><span class='workspace-section'>{section}</span>"
               f"<span class='workspace-page'>{escape(current)}</span></div>"
               f"<div class='workspace-context'>{context}<span class='space-mark'>✦</span></div></div>"
               if not bare else "")
    # Four primary destinations and a native disclosure keep all other routes
    # reachable on a phone, including without JavaScript.
    mobile = ("<nav class='mobile-nav' aria-label='Quick navigation'>"
              + "".join(link(path, "Saved" if path == "/starred" else labels[path]) for path in ("/", "/reels", "/review", "/starred"))
              + "<details class='more-nav'><summary>" + icon('/lists') + "<span>More</span></summary>"
              + "<nav class='more-panel' aria-label='All sections'>" + groups + account + "</nav></details></nav>"
              if not bare else "")
    intro = welcome(suffix) if here == "/" and not bare and "id='reading-top'" in body else ""
    immersive = here == "/reels" and "id='reel-state'" in body
    journey_data = ""
    if journey is not None and not bare:
        from web.journey import hud, home, state
        journey_data = state(journey)
        if here == "/" and "id='reading-top'" in body:
            intro = home(journey, suffix)
        toolbar = toolbar.replace("<span class='space-mark'>✦</span>", hud(journey, suffix))
    if immersive:
        shell = toolbar = mobile = ""
    # Some handlers already insert the script beside their player. The shell's
    # shortcuts must also work on account pages, and must never bind twice.
    script = "" if "app.js" in body else f"<script src='{stamped('app.js')}'></script>"
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
        "<meta name='theme-color' content='#f5f5f7' "
        "media='(prefers-color-scheme: light)'>"
        "<meta name='theme-color' content='#1d1d1f' "
        "media='(prefers-color-scheme: dark)'>"
        "<link rel='manifest' href='/manifest.webmanifest'>"
        "<link rel='apple-touch-icon' href='/static/icon-512.png'>"
        # Single quotes inside the braces: reusing the outer quote there is
        # also PEP 701, and this file has no other reason to demand 3.12.
        f"<link rel='stylesheet' href='{stamped('app.css')}'>"
        # Colours on or off is this browser's choice (Settings), read here,
        # before the body, so the first paint is already the right one.
        "<script>try{if(localStorage.getItem('colours')==='1')"
        "document.documentElement.classList.add('coloured')}catch(e){}</script>"
        f"</head><body class='{'auth-page' if bare else 'reels-page' if immersive else 'learning-page'}' data-page='{escape(here, quote=True)}'>"
        "<a class='skip-link' href='#main-content'>Skip to content</a>"
        f"{shell}{journey_data}<div class='workspace'>{toolbar}"
        f"<main id='main-content'>{intro}{body}</main></div>{mobile}"
        # The keys, on every page, because they were written down in one
        # `.hint` on one card and nowhere else -- so the reel, the video page
        # and the review queue each had shortcuts nobody was told about. What
        # they are depends on what the page has, so `app.js` fills this in
        # from what it finds rather than each handler being asked to remember.
        "<button type='button' id='keys-open' class='keys-open' "
        "title='Keyboard shortcuts (?)' aria-label='Keyboard shortcuts'>"
        "keys</button>"
        "<div id='keys' class='keys' hidden role='dialog' "
        "aria-label='Keyboard shortcuts'></div>"
        f"{script}</body></html>"
    )



def video_tile(row: dict, href: str) -> str:
    """A catalogue entry with the same measured data as the detailed table."""
    title = row.get("title") or row["video"]
    percent = min(100, max(0, round(row["comprehension"] * 100)))
    duration = f"{row['minutes']:.0f} min" if row.get("minutes") is not None else ""
    level = f" · {escape(row['level_label'])}" if row.get("level_label") else ""
    return (
        f"<a class='video-tile' href='{escape(href, quote=True)}'>"
        "<div class='video-cover'>"
        f"<img src='https://i.ytimg.com/vi/{quote(row['video'], safe='')}/hqdefault.jpg' "
        "alt='' width='480' height='360' loading='lazy' decoding='async'>"
        f"<span class='video-play'>{icon('/subtitles')}</span>"
        f"<span class='video-duration'>{duration}</span></div>"
        f"<div class='video-info'><h3>{escape(title)}</h3>"
        f"<span class='video-fit'>{percent}% of words familiar{level}</span>"
        f"<span class='video-meter' aria-hidden='true'><span style='width:{percent}%'></span></span>"
        f"<span class='video-learn'>{row['teaches']:,} words from your list <span>Watch & explore ↗</span></span>"
        "</div></a>"
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
             words: list[list[str]] | None = None, known=None,
             starred: bool | None = None) -> str:
    """A sentence, its English under it, and the level the judge gave it
    — `B1` — after the German where one is known, so a reader can see why
    a sentence was picked over a harder one, or why this one is hard.

    With `words` — `[token, kind, key]` per token, as `web.handlers._words`
    reads them off a sentence — every word is a button that opens its
    gloss, as a subtitle's words do; the new word's tokens are marked in it
    as before, and with `known`, the reader's units, every other word says
    whether it is known (`clickable`). Without, the text is plain with the
    new word marked.

    `starred` adds the keep-this control, in the state given. It lives here
    rather than at the eight call sites because "every page" is what was
    asked for, and a control added page by page is a control that misses
    one. `None` leaves it off, for the places where a sentence is furniture
    rather than something to come back to — a quiz answer, a worked example.

    A button and not a form: a sentence is rendered inside a form on several
    of those pages, and a nested form is invalid HTML that browsers silently
    unnest, which would post the wrong thing. `app.js` sends it instead.

    A sentence with exactly one unknown word in it is marked `i1`, and the
    stylesheet gives it its own background. That is the whole point of the
    thing -- the sentence you can read but for one word -- and it was
    indistinguishable from a sentence with five. Computed here, off the same
    `words` and `known` that `clickable` colours the words from, for the
    reason the keep-control is here: every page is what was asked for, and a
    mark added page by page is a mark that misses one.
    """
    size = " lead" if lead else ""
    step = one_step(words, known)
    size += " i1" if step else ""
    badge = f" <span class='level' title='the level the judge gave it'>{escape(level)}</span>" \
        if level else ""
    body = clickable(words, surface, known) if words else mark(text, surface)
    # Named, not only tinted. A background says "this one is different"; the
    # badge says which different, and i+1 is the word the whole app is built
    # around, so it is worth spelling out where the reader meets it.
    flag = ("<span class='step' title='you know every word in this one "
            "but one'>i+1</span>" if step else "")
    keep = "" if starred is None else (
        f"<button type='button' class='star{' on' if starred else ''}'"
        f" data-act='star' aria-pressed='{'true' if starred else 'false'}'"
        f" title='Keep this sentence (F)'>&#9733;</button>")
    out = (f"<p class='de{size}' data-text='{escape(text)}'>"
           f"{body}{flag}{badge}{keep}</p>")
    if translation:
        # The English carries the mark too: on the pages where the two halves
        # are one box, tinting only the German splits it down the middle.
        out += (f"<p class='en{' i1' if ' i1' in size else ''}'>"
                f"{escape(translation)}</p>")
    return out


def one_step(words, known) -> bool:
    """Whether a sentence is i+1: exactly one distinct unit in it is unknown.

    Counted over units rather than tokens, so a word said twice is one
    unknown, and a token no unit claims -- a name, a number -- is neither
    known nor unknown and cannot make a sentence harder than it reads.
    """
    if not words or known is None:
        return False
    new = {(kind, key) for _, kind, key in words
           if kind and key and Unit(kind, key) not in known}
    return len(new) == 1


def clickable(words: list[list[str]], surface: str | None, known=None) -> str:
    """Every word a button carrying its unit; the tokens of `surface` —
    the new word as the sentence says it — marked as the target.

    With `known`, every other word that wears a unit is classed `known` or
    `new`, and the stylesheet colours the new ones when the reader has
    colours on (Settings). A word no unit claims — a name, a number, a
    filler — is neither: painting those as unknown would light up most of
    a line. The target is only ever the target: it is the new word, and
    its mark stays the loudest thing on the line.
    """
    wanted = {w.strip(".,;:!?„“”\"'()[]…-–—").lower() for w in (surface or "").split()}
    out = []
    for token, kind, key in words:
        bare = token.strip(".,;:!?„“”\"'()[]…-–—").lower()
        if bare and bare in wanted:
            state = " target"
        elif known is not None and kind and key:
            state = " known" if Unit(kind, key) in known else " new"
        else:
            state = ""
        out.append(f"<button type='button' class='w{state}' data-kind='{escape(kind)}'"
                   f" data-key='{escape(key)}'>{escape(token)}</button>")
    return " ".join(out)


def login_page(error: str, target: str, name: str = "",
               google: bool = False) -> str:
    """The door: a name and a password, or Google, and where to go after."""
    warning = f"<p class='note due'>{escape(error)}</p>" if error else ""
    body = (
        "<h1>Sign in</h1>"
        f"{warning}"
        f"{_google_form('signin', 'Sign in with Google', target) if google else ''}"
        "<form method='post' action='/login' class='login'>"
        f"<input type='hidden' name='next' value='{escape(target, quote=True)}'>"
        "<label>Name <input name='name' autocomplete='username' "
        "autocapitalize='none' autocorrect='off' spellcheck='false' required "
        f"value='{escape(name, quote=True)}'></label>"
        "<label>Password <input name='password' type='password' "
        "autocomplete='current-password' required></label>"
        "<button type='submit'>Sign in</button>"
        "</form>"
        + ("<p class='note'>New here? <a href='/signup'>Make an account with "
           "Google</a>.</p>" if google else "")
    )
    return layout("Sign in", body, bare=True)


def _google_form(purpose: str, label: str, target: str = "/") -> str:
    """A button that begins a sign-in with Google (see `web.google`)."""
    return ("<form method='post' action='/auth/google' class='login'>"
            f"<input type='hidden' name='purpose' value='{escape(purpose, quote=True)}'>"
            f"<input type='hidden' name='next' value='{escape(target, quote=True)}'>"
            f"<button type='submit'>{escape(label)}</button></form>")


def _invited_to(found: dict) -> str:
    """What an invitation is for, in a sentence."""
    from languages import NATIVE, language               # noqa: PLC0415
    learning = language(found["language"]).name
    helped = NATIVE.get(found["native"], found["native"])
    return (f"It is to learn {escape(learning)}, with {escape(helped)} "
            "translations.")


def signup_page(error: str, token: str, found: dict, name: str = "",
                google: bool = False) -> str:
    """An invitation, and the form that spends it -- with a password, or
    with Google instead, which is the same form sent elsewhere."""
    warning = f"<p class='note due'>{escape(error)}</p>" if error else ""
    instead = ("<button type='submit' formaction='/auth/google' formnovalidate "
               "name='purpose' value='signup'>Use Google instead of a "
               "password</button>" if google else "")
    body = (
        "<h1>Make your account</h1>"
        f"<p class='note'>You have an invitation. {_invited_to(found)} "
        "Pick the name you will sign in with, and a password"
        + (" -- or sign in with Google instead" if google else "") + ".</p>"
        f"{warning}"
        "<form method='post' action='/signup' class='login'>"
        f"<input type='hidden' name='invite' value='{escape(token, quote=True)}'>"
        "<label>Name <input name='name' autocomplete='username' "
        "autocapitalize='none' autocorrect='off' spellcheck='false' required "
        "pattern='[a-z][a-z0-9_-]{0,31}' "
        "title='lowercase letters, digits, - and _, starting with a letter' "
        f"value='{escape(name, quote=True)}'></label>"
        "<label>Password <input name='password' type='password' "
        "autocomplete='new-password' minlength='8' required></label>"
        "<label>Password again <input name='again' type='password' "
        "autocomplete='new-password' minlength='8' required></label>"
        "<button type='submit'>Make my account</button>"
        f"{instead}"
        "</form>"
    )
    return layout("Make your account", body, bare=True)


def open_signup_page(error: str, name: str = "", learning: str = "de",
                     native: str = "en") -> str:
    """Signing up on one's own, with a Google account: a name, the language
    to learn, and the one translations are made in."""
    from languages import LANGUAGES, NATIVE              # noqa: PLC0415
    warning = f"<p class='note due'>{escape(error)}</p>" if error else ""

    def options(choices: dict[str, str], chosen: str) -> str:
        return "".join(
            f"<option value='{escape(code, quote=True)}'"
            f"{' selected' if code == chosen else ''}>{escape(label)}</option>"
            for code, label in choices.items())

    body = (
        "<h1>Make your account</h1>"
        "<p class='note'>Pick the name you will be known by here and what you "
        "want to learn; Google confirms who you are, and you sign in with it "
        "from then on. Your words, cards and plans are your own.</p>"
        f"{warning}"
        "<form method='post' action='/auth/google' class='login'>"
        "<input type='hidden' name='purpose' value='signup'>"
        "<label>Name <input name='name' autocomplete='username' "
        "autocapitalize='none' autocorrect='off' spellcheck='false' required "
        "pattern='[a-z][a-z0-9_-]{0,31}' "
        "title='lowercase letters, digits, - and _, starting with a letter' "
        f"value='{escape(name, quote=True)}'></label>"
        "<label>Learning <select name='language'>"
        f"{options({c: l.name for c, l in LANGUAGES.items()}, learning or 'de')}"
        "</select></label>"
        "<label>Translations in <select name='native'>"
        f"{options(NATIVE, native or 'en')}</select></label>"
        "<button type='submit'>Continue with Google</button>"
        "</form>"
        "<p class='note'>Have an account? <a href='/login'>Sign in</a>.</p>"
    )
    return layout("Make your account", body, bare=True)


def signup_closed() -> str:
    return layout("Sign-ups closed", "<h1>Sign-ups are closed for now</h1>"
                  "<p class='sub'>This installation has as many readers as it "
                  "takes. Ask whoever runs it for an invitation, or "
                  "<a href='/login'>sign in</a>.</p>", bare=True)


def no_invitation() -> str:
    return layout("Sign up", "<h1>Signing up takes an invitation</h1>"
                  "<p class='sub'>Ask whoever runs this installation for a "
                  "link, or <a href='/login'>sign in</a>.</p>", bare=True)


def google_failed(message: str, back: str) -> str:
    return layout("Google sign-in", "<h1>That did not work</h1>"
                  f"<p class='sub'>{escape(message)}</p>"
                  f"<p><a href='{escape(back, quote=True)}'>Back</a></p>",
                  bare=True)


def unknown_google(email: str, can_sign_up: bool) -> str:
    """A Google account that signs nobody in here."""
    which = f" ({escape(email)})" if email else ""
    then = ("<a href='/signup'>Make an account</a> with it, or "
            "<a href='/login'>sign in</a> another way." if can_sign_up else
            "<a href='/login'>Sign in</a> another way, or ask whoever runs "
            "this installation for an invitation.")
    return layout("Google sign-in", "<h1>No account here uses that Google "
                  f"account{which}</h1><p class='sub'>{then}</p>", bare=True)


def owner_only() -> str:
    """What a reader is told when they reach for something only the
    installation's owner may do."""
    return layout("Not yours to change", "<h1>Only the owner can do that</h1>"
                  "<p class='sub'>Adding videos and channels, and recalculating "
                  "the plan, change what every reader here sees, so they are "
                  "for whoever runs this installation.</p>"
                  "<p><a href='/'>Back to reading</a></p>")


def invitation_gone() -> str:
    return layout("Invitation", "<h1>This invitation has expired</h1>"
                  "<p class='sub'>Or it has already been used. Ask for a new "
                  "link, or <a href='/login'>sign in</a>.</p>", bare=True)


def invited_page(url: str, found: dict) -> str:
    """The link to send, shown once: only its digest is kept."""
    from datetime import datetime                         # noqa: PLC0415
    until = datetime.fromtimestamp(found["expires"]).strftime("%-d %B")
    body = (
        "<h1>Invitation made</h1>"
        f"<p class='note'>{_invited_to(found)}</p>"
        "<p class='note'>Send this link. It works once, until "
        f"{escape(until)}, and this is the only time it is shown.</p>"
        f"<p><input class='invite-link' readonly value='{escape(url, quote=True)}' "
        "onclick='this.select()'></p>"
        "<p><a href='/settings'>Back to Settings</a></p>"
    )
    return layout("Invitation made", body)
