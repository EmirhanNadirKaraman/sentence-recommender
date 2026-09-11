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
        options["cookiesfrombrowser"] = (browser,)
    options.update(extra)
    return options
