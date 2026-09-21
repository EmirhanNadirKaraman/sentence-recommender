"""The video page.

A sentence in this corpus is a moment in a YouTube video — every subtitle
sentence carries the clip it came from and where in it — so a word can be
watched being said rather than only read.

Under the player sits a caption that follows the video, and under that the
whole transcript. Both are driven by the one place this project earns
JavaScript: the player is the only thing that knows what time it is. Without
the script the page still reads, navigates and seeks by link; it just stops
following.
"""
from __future__ import annotations

from html import escape

from web.render import mark, stamped

# A short lead-in, because a cue's start time is when the word is already
# being said, and beginning exactly there clips it.
LEAD_IN = 0.4


def player(video_id: str, start: float) -> str:
    """The video, opened at the moment the sentence is said, with our own
    controls under it.

    Deliberately no `end`: stopping at the sentence would make the caption and
    transcript pointless, and the reason to hear a word said is to hear what
    surrounds it.

    YouTube's own controls are off (`controls=0`) and the frame is cropped
    by a title bar's height top and bottom (`.player iframe`), which is the
    only way to be rid of the title-and-share bar the embed lays over the
    picture at the start and on every pause. What that costs -- play,
    pause, seeking, the speed, the sound, full screen -- the bar below
    gives back through the player API, on every page alike, and it works
    on the reel too, where the picture itself cannot take a click.
    """
    return (
        "<div class='player'>"
        f"<iframe id='player' title='Video' allowfullscreen "
        "allow='autoplay; accelerometer; encrypted-media; picture-in-picture; fullscreen' "
        f"src='https://www.youtube-nocookie.com/embed/{escape(video_id)}"
        f"?start={max(int(start - LEAD_IN), 0)}"
        "&rel=0&controls=0&enablejsapi=1&playsinline=1'></iframe></div>"
        + controls()
    )


def controls() -> str:
    """The bar under every player. `app.js` binds it to whichever player
    the page made (`window.__player`) and asks the page where the current
    sentence starts (`window.__sentenceStart`)."""
    return (
        "<div class='controls' id='controls'>"
        "<button type='button' data-act='prev' title='The subtitle before (Q)'>&#8249; line</button>"
        "<button type='button' data-act='sentence' title='Play this sentence again'>"
        "&#8635; sentence</button>"
        "<button type='button' data-act='next' title='The next subtitle (E)'>line &#8250;</button>"
        "<button type='button' data-act='back' title='Five seconds back'>&minus;5 s</button>"
        "<button type='button' data-act='toggle' id='toggle'>Play</button>"
        "<button type='button' data-act='fwd' title='Five seconds on'>+5 s</button>"
        "<button type='button' data-act='rate' id='rate' title='Slower or normal speed'>1&times;</button>"
        "<button type='button' data-act='mute' id='mute'>Sound off</button>"
        "<button type='button' data-act='autopause' id='autopause' "
        "title='Pause after every subtitle (T)'>Auto-pause off</button>"
        "<button type='button' data-act='full' title='Full screen'>&#x26F6;</button>"
        "<span class='clock' id='clock'></span>"
        "</div>"
    )


def caption(text: str, translation: str | None, surface: str | None) -> str:
    """The line being spoken, directly under the picture.

    Starts as the sentence the page was opened for, so it says something
    useful before the video has played a frame, then follows along.
    """
    english = (f"<p class='en' id='caption-en'>{escape(translation)}</p>"
               if translation else "<p class='en' id='caption-en'></p>")
    return (f"<div class='caption'><p class='de' id='caption'>"
            f"{mark(text, surface)}</p>{english}</div>")


def transcript(cues: list, current_index: int, surface: str | None) -> str:
    """Every cue in the video, the one being spoken marked."""
    rows = []
    for i, cue in enumerate(cues):
        here = " on" if i == current_index else ""
        body = (mark(cue.text, surface) if i == current_index
                else escape(cue.text))
        english = escape(cue.translation) if cue.translation else ""
        rows.append(
            f"<li class='cue{here}' data-at='{cue.timing.start:.2f}' "
            f"data-en=\"{english}\" id='cue{i}'>"
            f"<span class='at'>{_clock(cue.timing.start)}</span>"
            f"<span class='said'>{body}</span></li>"
        )
    return f"<ol class='transcript' id='transcript'>{''.join(rows)}</ol>"


def script() -> str:
    """Follow the player: update the caption, mark the line, keep it in view.

    The transcript scrolls inside its own box rather than through the page —
    scrolling the document would carry the video out of the viewport, which
    is the opposite of what a video page is for.
    """
    return f"<script src='{stamped('app.js')}'></script>" + """
<script src='https://www.youtube.com/iframe_api'></script>
<script>
(function () {
  var box = document.getElementById('transcript');
  var line = document.getElementById('caption');
  var lineEn = document.getElementById('caption-en');
  var cues = Array.prototype.slice.call(box.querySelectorAll('.cue'));
  var times = cues.map(function (c) { return parseFloat(c.dataset.at); });
  var calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var player = null, showing = -1;

  function keepInView(cue) {
    var wanted = cue.offsetTop - box.offsetTop
               - (box.clientHeight / 2) + (cue.clientHeight / 2);
    var top = Math.max(0, Math.min(wanted, box.scrollHeight - box.clientHeight));
    if (box.scrollTo) box.scrollTo({top: top, behavior: calm ? 'auto' : 'smooth'});
    else box.scrollTop = top;
  }

  function showCue(at) {
    var i = 0;
    while (i + 1 < times.length && times[i + 1] <= at) i++;
    if (i === showing) return;
    if (cues[showing]) cues[showing].classList.remove('now');
    showing = i;
    cues[i].classList.add('now');
    line.innerHTML = cues[i].querySelector('.said').innerHTML;
    lineEn.textContent = cues[i].dataset.en || '';
    keepInView(cues[i]);
  }

  window.onYouTubeIframeAPIReady = function () {
    player = new YT.Player('player', {events: quietEvents({onReady: function () {
      window.__player = player;
      window.__sentenceStart = function () {
        return cues[showing] ? parseFloat(cues[showing].dataset.at) : null;
      };
      window.__cueTimes = function () { return times; };
      setInterval(function () {
        if (player && player.getCurrentTime) showCue(player.getCurrentTime());
      }, 250);
    }})});
  };

  cues.forEach(function (cue) {
    cue.addEventListener('click', function () {
      if (!player || !player.seekTo) return;
      player.seekTo(Math.max(parseFloat(cue.dataset.at) - 0.4, 0), true);
      player.playVideo();
    });
  });
})();
</script>
"""


def _clock(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


def merged_script() -> str:
    """The tags that pull in the reading page's behaviour.

    The script itself is `web/static/app.js`; what is left here is the order
    it has to load in. The IFrame API goes first because `app.js` installs
    `onYouTubeIframeAPIReady` for it to call, and neither tag is deferred, so
    the order on the page is the order they run in.

    What app.js does, briefly: each slide carries the video and the second it
    was said, so stepping the deck moves the picture as well as the text —
    `loadVideoById` rather than a seek, since consecutive sentences are often
    from different videos — and the transcript is fetched per video and
    cached, because shipping every cue of every video the deck touches would
    be most of the page.
    """
    return (
        "<script src='https://www.youtube.com/iframe_api'></script>"
        f"<script src='{stamped('app.js')}'></script>"
    )


def stage(video_id: str, start: float) -> str:
    """The player, ready for whichever sentence the deck is showing."""
    return (
        f"<div class='stage' id='stage'>{player(video_id, start)}"
        "<p class='de' id='caption'></p><p class='en' id='caption-en'></p></div>"
    )
