"""The options every yt-dlp call shares.

Gathered here because the interesting one has to be on all of them or none.
YouTube answers an anonymous scrape with "Sign in to confirm you're not a
bot", and it does so at the metadata step — before subtitles are ever looked
at — so a run without cookies reports every video as unavailable and no
amount of choosing better channels helps.

`cookiesfrombrowser` hands yt-dlp the session from a browser already signed
in. It is a tuple because that is the shape yt-dlp wants, and the first
element is the browser name.
"""
from __future__ import annotations

from config import Settings

BASE = {"quiet": True, "no_warnings": True, "skip_download": True}


def scrape(settings: Settings | None = None, **extra) -> dict:
    """Base options, plus cookies when a browser is configured."""
    options = dict(BASE)
    browser = (settings or Settings()).cookies_browser
    if browser:
        # All three together, or none of them. Cookies alone make yt-dlp use
        # the web client, which answers "The page needs to be reloaded" until
        # the n-challenge is solved, and solving it needs a JS runtime.
        #
        # With only the cookie, `_why_empty` (which asked yt-dlp then) could
        # never inspect a video and so said "could not be inspected" — which
        # classifies as `unfetchable`, which is deliberately never settled.
        # So a video with no hand-written subtitles was re-fetched by every
        # later run, forever, instead of being written off once: a second
        # pass over a channel spent its first 34 videos re-asking questions
        # the first pass had already failed to answer.
        options.update({
            "cookiesfrombrowser": (browser,),
            "js_runtimes": {"node": {}},
            "remote_components": ["ejs:github"],
        })
    options.update(extra)
    return options
