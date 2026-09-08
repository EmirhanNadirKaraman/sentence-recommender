"""The video page.

A sentence in this corpus is a moment in a YouTube video — every subtitle
sentence carries the clip it came from and where in it — so a word can be
watched being said rather than only read.

The transcript beside the player follows along and is clickable, which is the
one place this project earns JavaScript: the YouTube player is the source of
truth for time, and nothing server-rendered can track it. The page still reads
and navigates with the script blocked; only the following and the seeking stop.
"""
from __future__ import annotations

from html import escape

from web.render import mark

# A short lead-in, because a cue's start time is when the word is already being
# said and beginning there clips it.
LEAD_IN = 0.4


def player(video_id: str, start: float, end: float) -> str:
    """The video, opened at the moment the sentence is said.

    Deliberately no `end`: stopping at the sentence would make the transcript
    beside it pointless, and the reason to watch a word being said is to hear
    what surrounds it. Jump in at the right moment, then keep going.
    """
    return (
        "<div class='player'>"
        f"<iframe id='player' title='Video' allowfullscreen "
        "allow='accelerometer; encrypted-media; picture-in-picture' "
        f"src='https://www.youtube-nocookie.com/embed/{escape(video_id)}"
        f"?start={max(int(start - LEAD_IN), 0)}"
        "&rel=0&modestbranding=1&enablejsapi=1'></iframe></div>"
    )


def transcript(cues: list, current_index: int, surface: str | None) -> str:
    """Every cue in the video, the spoken one marked."""
    rows = []
    for i, cue in enumerate(cues):
        here = " on" if i == current_index else ""
        body = (mark(cue.text, surface) if i == current_index
                else escape(cue.text))
        rows.append(
            f"<li class='cue{here}' data-at='{cue.timing.start:.2f}' "
            f"id='cue{i}'>"
            f"<span class='at'>{_clock(cue.timing.start)}</span>"
            f"<span class='said'>{body}</span></li>"
        )
    return f"<ol class='transcript'>{''.join(rows)}</ol>"


def script() -> str:
    """Keep the transcript in step with the player, and let cues seek it."""
    return """
<script src='https://www.youtube.com/iframe_api'></script>
<script>
(function () {
  var cues = Array.prototype.slice.call(document.querySelectorAll('.cue'));
  var times = cues.map(function (c) { return parseFloat(c.dataset.at); });
  var calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var player = null, showing = -1;

  function highlight(at) {
    var i = 0;
    while (i + 1 < times.length && times[i + 1] <= at) i++;
    if (i === showing) return;
    if (cues[showing]) cues[showing].classList.remove('now');
    showing = i;
    cues[i].classList.add('now');
    cues[i].scrollIntoView({block: 'center',
                            behavior: calm ? 'auto' : 'smooth'});
  }

  window.onYouTubeIframeAPIReady = function () {
    player = new YT.Player('player', {events: {onReady: function () {
      setInterval(function () {
        if (player && player.getCurrentTime) highlight(player.getCurrentTime());
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
