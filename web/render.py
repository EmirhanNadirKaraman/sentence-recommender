"""The look of the local viewer.

The palette and structure come from a German school exercise book: cool
squared paper, königsblau fountain-pen ink for the text, and the red margin
rule down the left. That last one is load-bearing rather than decorative — it
separates the rail carrying step numbers from the reading column, which is
exactly what a margin is for. Red also means one thing here, the same thing it
means on returned schoolwork: a correction.

Typographic register carries the pedagogy. German is set in Literata, a
reading face; the interface and the English translations are in Atkinson
Hyperlegible. The German is the material; everything else is scaffolding.
"""
from __future__ import annotations

from html import escape

FONTS = ("https://fonts.googleapis.com/css2?"
         "family=Literata:ital,opsz,wght@0,7..72,400;0,7..72,600;1,7..72,400"
         "&family=Atkinson+Hyperlegible:wght@400;700&display=swap")

STYLE = """
:root {
  --paper:   #eef1f6;
  --surface: #f8fafd;
  --ink:     #1b2a4a;
  --ink-2:   #5d6d8c;
  --rail:    #c0392b;
  --target:  #4a55a8;
  --faint:   #ccd7e8;
  --serif: Literata, Charter, "Iowan Old Style", Georgia, serif;
  --sans: "Atkinson Hyperlegible", ui-sans-serif, system-ui, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #0f1626; --surface: #161f33; --ink: #dce5f6; --ink-2: #8b9bbd;
    --rail: #e2685c; --target: #9fabf2; --faint: #263149;
  }
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; background: var(--paper); color: var(--ink);
  font: 400 15px/1.5 var(--sans);
  text-rendering: optimizeLegibility;
}
a { color: inherit; text-decoration-color: var(--faint);
    text-underline-offset: 3px; }
a:hover { text-decoration-color: var(--target); }
:focus-visible { outline: 2px solid var(--target); outline-offset: 3px; }

.masthead { border-bottom: 1px solid var(--faint); }
.masthead .inner {
  max-width: 47rem; margin: 0 auto; padding: 14px 24px;
  display: flex; gap: 22px; align-items: baseline; flex-wrap: wrap;
}
.masthead .name { font: italic 400 16px/1 var(--serif); margin-right: 6px; }
.masthead a { font-size: 14px; color: var(--ink-2); text-decoration: none; }
.masthead a.here { color: var(--ink); text-decoration: underline;
  text-decoration-color: var(--rail); text-decoration-thickness: 2px; }

main { max-width: 47rem; margin: 0 auto; padding: 40px 24px 96px; }

h1 { font: 400 21px/1.3 var(--sans); margin: 0 0 6px; }
h2 { font: 400 15px/1.3 var(--sans); color: var(--ink-2);
     margin: 40px 0 14px; }
.note { color: var(--ink-2); font-size: 14px; margin: 0 0 30px; max-width: 34rem; }

/* German is always the serif; English always the sans, one step down. */
.de { font: 400 19px/1.6 var(--serif); margin: 0; }
.de.lead { font-size: 30px; line-height: 1.42; }
.en { font: 400 14px/1.5 var(--sans); color: var(--ink-2); margin: 6px 0 0; }

/* The one unknown thing: marked when shown, ruled when withheld. */
.target { color: var(--target); text-decoration: underline;
  text-decoration-thickness: 2px; text-underline-offset: 5px;
  text-decoration-color: var(--target); }
.blank { display: inline-block; min-width: 7ch;
  border-bottom: 2px solid var(--target); }

/* The ledger: a rail of step numbers, one continuous margin rule beside it. */
.ledger { position: relative; --rail-w: 4.75rem; }
.ledger::before {
  content: ""; position: absolute; top: 0; bottom: 0; left: var(--rail-w);
  width: 1px; background: var(--rail); opacity: .55;
}
.entry { display: grid; grid-template-columns: var(--rail-w) 1fr; }
.entry .rail {
  text-align: right; padding: 18px 18px 0 0;
  font-size: 13px; color: var(--ink-2); font-variant-numeric: tabular-nums;
}
.entry .rail .kind { display: block; font-size: 11.5px; opacity: .75; }
.entry .body { padding: 18px 0 18px 22px; border-bottom: 1px solid var(--faint); }
.entry:last-child .body { border-bottom: 0; }
.entry .unit { font: 600 17px/1.35 var(--serif); }
.entry .unit a { text-decoration: none; }
.entry .unit a:hover { text-decoration: underline;
  text-decoration-color: var(--target); }
.entry .de { margin-top: 5px; }

/* Figures: no tiles, no borders — just numbers given room. */
.figures { display: flex; gap: 40px; flex-wrap: wrap;
  margin: 44px 0 0; padding-top: 22px; border-top: 1px solid var(--faint); }
.figures div { min-width: 0; }
.figures .n { font: 400 22px/1.1 var(--serif);
  font-variant-numeric: tabular-nums; }
.figures .k { font-size: 13px; color: var(--ink-2); margin-top: 3px; }

form.bar { display: flex; gap: 10px; margin: 0 0 26px; flex-wrap: wrap; }
input[type=text], select {
  font: 400 15px var(--sans); padding: 8px 11px; color: var(--ink);
  background: var(--surface); border: 1px solid var(--faint); border-radius: 3px;
}
input[type=text] { flex: 1; min-width: 190px; }
input[type=text]::placeholder { color: var(--ink-2); opacity: .8; }
button {
  font: 400 15px var(--sans); padding: 8px 15px; cursor: pointer;
  color: var(--ink); background: var(--surface);
  border: 1px solid var(--faint); border-radius: 3px;
}
button.go { background: var(--ink); color: var(--paper); border-color: var(--ink); }
button:hover { border-color: var(--target); }

/* Source switch: quiet, and it says what it is switching. */
.switch { display: flex; gap: 16px; align-items: baseline; margin: 0 0 28px;
  font-size: 14px; color: var(--ink-2); flex-wrap: wrap; }
.switch a { text-decoration: none; }
.switch a.on { color: var(--ink); text-decoration: underline;
  text-decoration-color: var(--rail); text-decoration-thickness: 2px;
  text-underline-offset: 4px; }

/* Review: the answer sits on a ruled line, as it would on a worksheet. */
.prompt { margin: 26px 0 30px; }
.prompt .de { margin-bottom: 16px; }
.answer { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap;
  margin-top: 26px; }
.answer input[type=text] {
  font: 400 19px var(--serif); border: 0; border-bottom: 2px solid var(--ink);
  border-radius: 0; background: transparent; padding: 4px 2px; min-width: 12rem;
}
.mark { font: 400 17px/1.4 var(--serif); margin: 0 0 26px;
  padding-left: 14px; border-left: 3px solid var(--rail); }
.mark.right { border-left-color: var(--target); }

/* The player sits above the reading, and follows whichever sentence is shown. */
.stage { margin: 6px 0 22px; }
.stage .de { font-size: 17px; color: var(--ink-2); margin: 12px 0 0;
  min-height: 1.6em; }

/* Per-sentence corrections. Quiet: these are for the exception, not the
   reading, and should not compete with the sentence above them. */
.tools { display: flex; gap: 10px; align-items: center; margin-top: 10px; }
.tools button, .tools .link {
  font: 400 13px var(--sans); padding: 4px 10px; border-radius: 3px;
  color: var(--ink-2); background: transparent;
  border: 1px solid var(--faint); text-decoration: none; cursor: pointer;
}
.tools button:hover, .tools .link:hover { color: var(--ink);
  border-color: var(--rail); }
.boxes { display: grid; gap: 2px; margin: 22px 0; }
.box { display: grid; grid-template-columns: 1.4rem 1fr auto; gap: 10px;
  align-items: baseline; padding: 7px 4px;
  border-bottom: 1px solid var(--faint); }
.box .de { font-size: 17px; }
.box .quiet { font-size: 13px; }

/* Adding a video: a form that reaches out to YouTube and writes, so it says
   so before you press it and reports what happened after. */
.note.said { padding: 12px 15px; border-left: 3px solid var(--target);
  background: var(--surface); max-width: none; }
.note.said.bad { border-left-color: var(--rail); }

/* Alternative i+1 sentences for the same unit, stepped through in place. */
.deck { min-height: 7.2rem; }
.also { font: 400 13.5px/1.5 var(--sans); color: var(--ink-2); margin: 10px 0 0; }
.also.clear { color: var(--target); }
.stepper { display: flex; gap: 12px; align-items: center; margin-top: 14px;
  font-size: 14px; color: var(--ink-2); }
.stepper button { padding: 4px 12px; font-size: 16px; line-height: 1.2; }
.stepper .count { font-variant-numeric: tabular-nums; }
.stepper .hint { margin-left: 4px; }

/* Actions: what to do about the thing just shown. */
.actions { display: flex; gap: 10px; flex-wrap: wrap; align-items: center;
  margin: 30px 0 0; }
.actions form { display: inline; }
.actions .link {
  font: 400 15px var(--sans); padding: 8px 15px; text-decoration: none;
  color: var(--ink); background: var(--surface);
  border: 1px solid var(--faint); border-radius: 3px; display: inline-block;
}
.actions .link:hover, .actions button:hover { border-color: var(--target); }

/* Video: player above, transcript following along beside it. */
.player { position: relative; padding-bottom: 56.25%; height: 0;
  background: var(--surface); border: 1px solid var(--faint); }
.player iframe { position: absolute; inset: 0; width: 100%; height: 100%;
  border: 0; }
/* The spoken line, right under the picture. Reserved height so the layout
   does not jump each time it changes. */
.caption { margin: 18px 0 4px; min-height: 4.6rem; }
.caption .de { font-size: 22px; line-height: 1.45; }
.caption .en { min-height: 1.2em; }

.transcript { list-style: none; margin: 20px 0 0; padding: 0;
  max-height: 22rem; overflow-y: auto; overscroll-behavior: contain;
  border-top: 1px solid var(--faint); }
.cue { display: grid; grid-template-columns: 3.4rem 1fr; gap: 14px;
  padding: 9px 4px; border-bottom: 1px solid var(--faint); cursor: pointer; }
.cue .at { font-size: 13px; color: var(--ink-2);
  font-variant-numeric: tabular-nums; }
.cue .said { font: 400 16px/1.5 var(--serif); color: var(--ink-2); }
.cue:hover .said { color: var(--ink); }
.cue.on .said, .cue.now .said { color: var(--ink); }
.cue.on { background: var(--surface); }
.cue.now { box-shadow: inset 3px 0 0 var(--rail); }
.occurrence { font-size: 14px; color: var(--ink-2); margin: 0 0 22px; }

.pager { display: flex; gap: 18px; align-items: baseline; margin-top: 30px;
  font-size: 14px; color: var(--ink-2); }
.quiet { color: var(--ink-2); }
.rows { width: 100%; border-collapse: collapse; font-size: 14px; }
.rows td, .rows th { text-align: left; padding: 9px 12px 9px 0;
  border-bottom: 1px solid var(--faint); font-weight: 400; }
.rows th { color: var(--ink-2); font-size: 13px; }
.rows td.n, .rows th.n { text-align: right; font-variant-numeric: tabular-nums; }
.empty { color: var(--ink-2); padding: 34px 0; font-size: 15px; max-width: 32rem; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }

@media (max-width: 620px) {
  .ledger { --rail-w: 3.1rem; }
  .entry .body { padding-left: 14px; }
  .de.lead { font-size: 24px; }
  .figures { gap: 26px; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
"""

NAV = (("/", "Next"), ("/reels", "Reels"), ("/roadmap", "Roadmap"),
       ("/blocked", "Blocked"), ("/subtitles", "Videos"))


def layout(title: str, body: str, here: str = "/", source: str = "") -> str:
    suffix = f"?src={source}" if source else ""
    links = "".join(
        f'<a href="{href}{suffix}" class="{"here" if href == here else ""}">'
        f"{escape(label)}</a>"
        for href, label in NAV
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)}</title>"
        "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
        f"<link rel='stylesheet' href='{FONTS}'>"
        f"<style>{STYLE}</style></head><body>"
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
             lead: bool = False) -> str:
    size = " lead" if lead else ""
    out = f"<p class='de{size}'>{mark(text, surface)}</p>"
    if translation:
        out += f"<p class='en'>{escape(translation)}</p>"
    return out
