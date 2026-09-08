"""HTML for the local viewer.

Server-rendered and form-driven — no JavaScript, so there is nothing to load,
bundle or debug. Everything is one file of markup helpers because the site is
half a dozen pages, not an application.
"""
from __future__ import annotations

from html import escape

STYLE = """
:root {
  --bg: #fbfaf8; --panel: #fff; --ink: #1a1a19; --muted: #6b6a66;
  --line: #e5e3de; --accent: #3a5a8c; --pattern: #7a4a8c; --ok: #2f7a4f;
  --warn: #a8632a;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #17171a; --panel: #1f1f23; --ink: #ececea; --muted: #96958f;
    --line: #32323a; --accent: #8fb0e0; --pattern: #c39ad6; --ok: #6fc494;
    --warn: #e0a06a;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
header { border-bottom: 1px solid var(--line); background: var(--panel);
  position: sticky; top: 0; z-index: 5; }
nav { max-width: 940px; margin: 0 auto; padding: 12px 20px;
  display: flex; gap: 20px; align-items: baseline; flex-wrap: wrap; }
nav .brand { font-weight: 650; letter-spacing: -0.01em; margin-right: 8px; }
nav a { color: var(--muted); font-size: 14px; }
nav a.on { color: var(--ink); font-weight: 600; }
main { max-width: 940px; margin: 0 auto; padding: 28px 20px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.015em; }
h2 { font-size: 16px; margin: 32px 0 12px; }
.sub { color: var(--muted); margin: 0 0 24px; font-size: 14px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px; margin-bottom: 28px; }
.stat { background: var(--panel); border: 1px solid var(--line);
  border-radius: 10px; padding: 14px 16px; }
.stat .n { font-size: 24px; font-weight: 650; letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums; }
.stat .k { color: var(--muted); font-size: 13px; margin-top: 2px; }
.row { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 12px 16px; margin-bottom: 8px; display: flex; gap: 14px;
  align-items: baseline; }
.row .pos { color: var(--muted); font-variant-numeric: tabular-nums;
  font-size: 13px; min-width: 42px; }
.row .body { flex: 1; min-width: 0; }
.unit { font-weight: 600; }
.de { margin-top: 3px; }
.en { color: var(--muted); font-size: 14px; margin-top: 1px; }
.tag { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
  padding: 2px 7px; border-radius: 999px; border: 1px solid var(--line);
  color: var(--muted); white-space: nowrap; }
.tag.pattern { color: var(--pattern); border-color: currentColor; }
.tag.word { color: var(--accent); border-color: currentColor; }
form.inline { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }
input[type=text] { flex: 1; min-width: 200px; padding: 9px 12px; font: inherit;
  background: var(--panel); color: var(--ink);
  border: 1px solid var(--line); border-radius: 8px; }
button { padding: 9px 16px; font: inherit; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--line); background: var(--panel); color: var(--ink); }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.pager { display: flex; gap: 10px; align-items: center; margin-top: 20px;
  color: var(--muted); font-size: 14px; }
.cloze { font-size: 19px; line-height: 1.7; margin: 6px 0; }
.blank { border-bottom: 2px solid var(--accent); padding: 0 26px; }
.empty { color: var(--muted); padding: 28px 0; }
.verdict { padding: 12px 16px; border-radius: 10px; margin-bottom: 18px;
  border: 1px solid var(--line); background: var(--panel); }
.verdict.ok { color: var(--ok); } .verdict.no { color: var(--warn); }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
td, th { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-weight: 500; font-size: 13px; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
"""

NAV = (("/", "Overview"), ("/roadmap", "Roadmap"), ("/review", "Review"),
       ("/subtitles", "Subtitles"))


def layout(title: str, body: str, active: str = "/") -> str:
    links = "".join(
        f'<a href="{href}" class="{"on" if href == active else ""}">{escape(label)}</a>'
        for href, label in NAV
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)} · sentence-recommender</title>"
        f"<style>{STYLE}</style></head><body>"
        f"<header><nav><span class='brand'>sentence-recommender</span>{links}</nav></header>"
        f"<main>{body}</main></body></html>"
    )


def stat(number, label: str) -> str:
    return f"<div class='stat'><div class='n'>{number}</div><div class='k'>{escape(label)}</div></div>"


def tag(kind: str) -> str:
    name = "pattern" if kind == "pattern" else "word"
    return f"<span class='tag {name}'>{name}</span>"


def sentence_block(text: str, translation: str | None) -> str:
    out = f"<div class='de'>{escape(text)}</div>"
    if translation:
        out += f"<div class='en'>{escape(translation)}</div>"
    return out
