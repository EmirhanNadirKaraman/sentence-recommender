"""Immersive reel shell. The one YouTube iframe survives every swipe."""
from html import escape
from urllib.parse import quote


def feed(*, title, row, state, exit_url, atlas_url, scoreboard, panel, taste,
         ordering, player, pager, script):
    # Keep captions above the picture shade, with one shared tap surface.
    player = player.replace("<p class='de' id='caption'>", "<div class='caption'><p class='de' id='caption'>")
    player = player.replace("id='caption-en'></p></div>", "id='caption-en'></p></div></div>")
    thumbnail = 'https://i.ytimg.com/vi/' + quote(row['video'], safe='') + '/hqdefault.jpg'
    return (
        "<section class='reel-viewport' aria-label='Immersive language reels'>"
        "<div class='reel-track' id='reel-track'>"
        "<div class='reel-neighbor reel-previous' aria-hidden='true'><img alt=''><span></span></div>"
        f"<article class='card' id='reel' style=\"--reel-poster:url('{thumbnail}')\">"
        + player
        + "<div class='reel-loading' id='reel-loading' hidden><span class='reel-loading-orb'></span></div>"
        "<div class='reel-shade'></div>"
        "<header class='reel-topbar'>"
        f"<a class='reel-exit' href='{escape(exit_url, quote=True)}' aria-label='Leave reels'>"
        "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'><path d='m14 5-7 7 7 7'/></svg></a>"
        "<span class='reel-brand'>i+1 <small>REELS</small></span>"
        f"<a class='reel-journey' href='{escape(atlas_url, quote=True)}'>"
        "✦ <span data-journey='xp'>Your atlas</span><small>XP</small></a></header>"
        f"<div class='reel-info'><span class='reel-fit'>{round(row['comprehension'] * 100)}% familiar</span>"
        f"<h1 id='reel-title'>{escape(title)}</h1>"
        "<span class='reel-position'><span id='reel-at'></span> / <span id='reel-total'></span>"
        " · real voices, at your level</span></div>"
        "<div class='reel-rail' aria-label='Reel actions'>"
        "<button type='button' data-reel-action='toggle' aria-label='Play or pause'><span>Ⅱ</span><small>Pause</small></button>"
        "<button type='button' data-reel-action='mute' aria-label='Toggle sound'><span>♫</span><small>Sound</small></button>"
        "<button type='button' data-reel-action='learn' aria-label='Explore words in this video'><span>✦</span><small>Learn</small></button>"
        "<button type='button' data-reel-action='more' aria-label='Reel options'><span>•••</span><small>More</small></button>"
        "</div><span class='reel-drag-hint'>Swipe up for your next discovery ↑</span></article>"
        "<div class='reel-neighbor reel-next' aria-hidden='true'><img alt=''><span></span></div>"
        "</div><div class='reel-desktop-step'>" + pager + "</div>"
        "<div id='reel-status' class='reel-status' role='status' aria-live='polite'></div>"
        "<dialog id='reel-drawer' class='reel-drawer'>"
        "<div class='drawer-head'><span class='eyebrow'>GO A LITTLE DEEPER</span>"
        "<button type='button' data-reel-action='close' aria-label='Close reel options'>×</button></div>"
        "<div class='drawer-scroll'><div id='reel-panel'>" + panel + "</div>"
        "<details class='reel-settings'><summary>Playback & captions</summary>"
        "<div id='reel-controls-slot'></div></details>"
        "<details class='reel-settings'><summary>Your video & feed</summary>"
        "<div id='reel-board'>" + scoreboard + "</div>"
        "<div id='reel-taste'>" + taste + "</div>" + ordering + "</details></div></dialog></section>"
        "<script type='application/json' id='reel-state'>"
        + state.replace('<', '\\u003c') + "</script>" + script
    )
