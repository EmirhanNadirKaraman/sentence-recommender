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

from web.render import mark

# A short lead-in, because a cue's start time is when the word is already
# being said, and beginning exactly there clips it.
LEAD_IN = 0.4


def player(video_id: str, start: float) -> str:
    """The video, opened at the moment the sentence is said.

    Deliberately no `end`: stopping at the sentence would make the caption and
    transcript pointless, and the reason to hear a word said is to hear what
    surrounds it.
    """
    return (
        "<div class='player'>"
        f"<iframe id='player' title='Video' allowfullscreen "
        "allow='accelerometer; encrypted-media; picture-in-picture' "
        f"src='https://www.youtube-nocookie.com/embed/{escape(video_id)}"
        f"?start={max(int(start - LEAD_IN), 0)}"
        "&rel=0&modestbranding=1&enablejsapi=1'></iframe></div>"
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
    return """
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
    player = new YT.Player('player', {events: {onReady: function () {
      setInterval(function () {
        if (player && player.getCurrentTime) showCue(player.getCurrentTime());
      }, 250);
    }}});
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
    """One script for the reading page: deck, player and transcript together.

    Each slide carries the video and second it was said, so stepping with the
    arrows moves the picture as well as the text — `loadVideoById` rather than
    a seek, since consecutive sentences are often from different videos. The
    transcript is fetched per video and cached, because shipping every cue of
    every video the deck touches would be most of the page.
    """
    return """
<script src='https://www.youtube.com/iframe_api'></script>
<script>
(function () {
  var deck = document.getElementById('deck');
  if (!deck) return;
  var slides = Array.prototype.slice.call(deck.querySelectorAll('.slide'));
  var at = document.getElementById('at');
  var stage = document.getElementById('stage');
  var box = document.getElementById('transcript');
  var line = document.getElementById('caption');
  var calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var player = null, ready = false, showing = 0;
  var loaded = {}, cues = [], marking = -1, video = null;

  function slide(i) { return slides[i]; }

  function keepInView(el) {
    if (!box || !el) return;
    var wanted = el.offsetTop - box.offsetTop
               - (box.clientHeight / 2) + (el.clientHeight / 2);
    var top = Math.max(0, Math.min(wanted, box.scrollHeight - box.clientHeight));
    if (box.scrollTo) box.scrollTo({top: top, behavior: calm ? 'auto' : 'smooth'});
    else box.scrollTop = top;
  }

  function drawTranscript(rows) {
    cues = rows || [];
    if (!box) return;
    box.innerHTML = cues.map(function (c, i) {
      return "<li class='cue' data-i='" + i + "'><span class='at'>" +
             c.clock + "</span><span class='said'></span></li>";
    }).join('');
    Array.prototype.forEach.call(box.querySelectorAll('.cue'), function (el, i) {
      el.querySelector('.said').textContent = cues[i].text;
      el.addEventListener('click', function () {
        if (player && player.seekTo) {
          player.seekTo(Math.max(cues[i].at - 0.4, 0), true);
          player.playVideo();
        }
      });
    });
    marking = -1;
  }

  function loadTranscript(id) {
    if (!box) return;
    if (loaded[id]) { drawTranscript(loaded[id]); return; }
    fetch('/api/transcript?video=' + encodeURIComponent(id))
      .then(function (r) { return r.json(); })
      .then(function (d) { loaded[id] = d.cues || []; drawTranscript(loaded[id]); })
      .catch(function () { drawTranscript([]); });
  }

  function follow(now) {
    if (!cues.length) return;
    var i = 0;
    while (i + 1 < cues.length && cues[i + 1].at <= now) i++;
    if (i === marking) return;
    var all = box.querySelectorAll('.cue');
    if (all[marking]) all[marking].classList.remove('now');
    marking = i;
    if (all[i]) { all[i].classList.add('now'); keepInView(all[i]); }
    if (line) line.textContent = cues[i].text;
  }

  function play(i) {
    var el = slide(i), id = el.dataset.video;
    if (!id) { if (stage) stage.hidden = true; return; }
    if (stage) stage.hidden = false;
    var start = Math.max(parseFloat(el.dataset.at) - 0.4, 0);
    if (!ready) return;
    if (id === video) player.seekTo(start, true);
    else { video = id; player.loadVideoById({videoId: id, startSeconds: start}); }
    loadTranscript(id);
  }

  function show(i) {
    slides[showing].hidden = true;
    showing = (i + slides.length) % slides.length;
    slides[showing].hidden = false;
    if (at) at.textContent = showing + 1;
    if (line) line.textContent = '';
    play(showing);
  }

  window.onYouTubeIframeAPIReady = function () {
    player = new YT.Player('player', {events: {onReady: function () {
      ready = true;
      play(showing);
      setInterval(function () {
        if (player && player.getCurrentTime) follow(player.getCurrentTime());
      }, 250);
    }}});
  };

  var prev = document.getElementById('prev'), next = document.getElementById('next');
  if (prev) prev.onclick = function () { show(showing - 1); };
  if (next) next.onclick = function () { show(showing + 1); };

  document.addEventListener('keydown', function (e) {
    var el = document.activeElement;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ||
               el.tagName === 'SELECT' || el.isContentEditable)) return;
    if (e.key === 'ArrowLeft') { show(showing - 1); e.preventDefault(); }
    if (e.key === 'ArrowRight') { show(showing + 1); e.preventDefault(); }
  });
})();
</script>
"""


def stage(video_id: str, start: float) -> str:
    """The player, ready for whichever sentence the deck is showing."""
    return (
        "<div class='stage' id='stage'><div class='player'>"
        f"<iframe id='player' title='Video' allowfullscreen "
        "allow='accelerometer; encrypted-media; picture-in-picture' "
        f"src='https://www.youtube-nocookie.com/embed/{escape(video_id)}"
        f"?start={max(int(start - LEAD_IN), 0)}"
        "&rel=0&modestbranding=1&enablejsapi=1'></iframe></div>"
        "<p class='de' id='caption'></p></div>"
    )
