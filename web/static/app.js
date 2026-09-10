// The reading page: the deck, the player and the transcript, together.
//
// A file rather than a Python string, because every `{` in JavaScript has to
// be doubled inside an f-string and that is a tax on the parts of this app
// most likely to grow. It is also fetched once and cached, where an inline
// script is re-sent with every page.
//
// There is exactly one keydown listener in the app, and it lives here. There
// used to be two: the reading page emitted this and a deck-only script that
// did a strict subset of it, each with its own idea of which slide was
// showing, so an arrow key advanced the deck twice and desynced the counter.
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

  // --- touch -------------------------------------------------------------
  //
  // The deck is the gesture surface, not the document: the page below it
  // scrolls normally and the transcript scrolls inside itself, so only the
  // card reinterprets a drag. `touch-action: none` on #deck is what stops iOS
  // scrolling a gesture that starts there — without it the browser claims the
  // touch before any of this runs.
  //
  //   up / down     another sentence for this word
  //   right         I know this
  //   left          not yet  (snoozes it for twenty words)
  //
  // Vertical is always "another one of these" and horizontal always decides,
  // which is the same rule the reels feed will use.
  // Listen on the whole reading area, animate only the sentence: dragging
  // the iframe with it repaints the video for no benefit.
  var surface = document.getElementById('card') || deck;
  var LOCK = 10;        // px of travel before the axis is decided
  var GO = 0.22;        // fraction of the surface that counts as a commit
  var FLICK = 0.35;     // px/ms that counts regardless of distance
  var from = null;

  function decide(value) {
    var b = document.querySelector('.actions button[value="' + value + '"]');
    if (b) b.click();
  }

  function offset(dx, dy) {
    deck.style.transform = dx || dy
      ? 'translate(' + dx + 'px,' + dy + 'px)' : '';
  }

  surface.addEventListener('pointerdown', function (e) {
    if (!e.isPrimary) return;
    // iOS reserves the left edge for its own back gesture, and will take the
    // touch mid-drag; starting there would make "not yet" navigate backwards.
    if (e.clientX < 24) return;
    if (e.target.closest('button, a, input, textarea, select, [contenteditable]'))
      return;
    from = {x: e.clientX, y: e.clientY, t: e.timeStamp, axis: null};
    deck.style.transition = 'none';
  });

  surface.addEventListener('pointermove', function (e) {
    if (!from) return;
    var dx = e.clientX - from.x, dy = e.clientY - from.y;
    if (!from.axis) {
      if (Math.abs(dx) < LOCK && Math.abs(dy) < LOCK) return;
      from.axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y';
    }
    // Follow the finger, damped, so the card admits it is being dragged
    // without implying it will come off the page.
    if (from.axis === 'x') offset(dx * 0.6, 0);
    else offset(0, dy * 0.4);
  });

  function release(e) {
    if (!from) return;
    var dx = e.clientX - from.x, dy = e.clientY - from.y;
    var axis = from.axis, ms = Math.max(e.timeStamp - from.t, 1);
    from = null;
    deck.style.transition = calm ? 'none' : 'transform .18s ease-out';
    offset(0, 0);
    if (!axis) return;
    var d = axis === 'x' ? dx : dy;
    var far = Math.abs(d) > (axis === 'x' ? surface.clientWidth : surface.clientHeight) * GO;
    if (!far && Math.abs(d) / ms < FLICK) return;
    if (axis === 'x') decide(d > 0 ? 'known' : 'pass');
    else show(showing + (d < 0 ? 1 : -1));
  }

  surface.addEventListener('pointerup', release);
  surface.addEventListener('pointercancel', function () {
    from = null;
    deck.style.transition = calm ? 'none' : 'transform .18s ease-out';
    offset(0, 0);
  });

  document.addEventListener('keydown', function (e) {
    var el = document.activeElement;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ||
               el.tagName === 'SELECT' || el.isContentEditable)) return;
    if (e.key === 'ArrowLeft') { show(showing - 1); e.preventDefault(); }
    if (e.key === 'ArrowRight') { show(showing + 1); e.preventDefault(); }
  });
})();

// --- the reels feed --------------------------------------------------------
//
// A feed rather than a series of pages, for one reason: iOS grants media
// playback permission to the *iframe's document*. Navigating to change video
// tears that document down, so the next `playVideo` is an unprivileged call
// and silently does nothing — playback dies after the first swipe. The player
// is created once here and never destroyed; only what surrounds it is fetched
// and swapped.
//
//   up / down   previous and next video
//   right       I know the word the panel is offering
//   left        set that word aside
(function () {
  var reel = document.getElementById('reel');
  var stateEl = document.getElementById('reel-state');
  if (!reel || !stateEl) return;

  var s = JSON.parse(stateEl.textContent);
  var title = document.getElementById('reel-title');
  var board = document.getElementById('reel-board');
  var panel = document.getElementById('reel-panel');
  var counter = document.getElementById('reel-at');
  var calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var player = null, ready = false, busy = false;

  window.onYouTubeIframeAPIReady = function () {
    player = new YT.Player('player', {events: {onReady: function () {
      ready = true;
    }}});
  };

  function go(to) {
    if (busy || to < 0 || to >= s.total) return;
    busy = true;
    fetch('/api/reels?i=' + to + '&src=' + encodeURIComponent(s.src))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.empty) return;
        s.at = d.at;
        title.textContent = d.title;
        board.innerHTML = d.scoreboard;
        panel.innerHTML = d.panel;
        if (counter) counter.textContent = d.at + 1;
        // The URL follows so a reload lands where you are, without the
        // navigation that would take the player with it.
        history.replaceState(null, '', '/reels?src=' +
          encodeURIComponent(s.src) + '&i=' + d.at);
        if (d.video !== s.video) {
          s.video = d.video;
          if (ready) player.loadVideoById({videoId: d.video, startSeconds: 0});
        }
      })
      .catch(function () {})
      .then(function () { busy = false; });
  }

  // The panel's own forms, posted without leaving the page — a navigation
  // here would destroy the player, which is the thing this whole file exists
  // to avoid.
  function decide(value) {
    var b = panel.querySelector('button[value="' + value + '"]');
    if (!b || !b.form || busy) return;
    busy = true;
    var body = new FormData(b.form);
    body.append('action', value);
    fetch('/known', {method: 'POST', body: new URLSearchParams(body),
                     redirect: 'manual', keepalive: true})
      .catch(function () {})
      .then(function () {
        busy = false;
        go(s.at);            // the word is gone; the panel behind it moved on
      });
  }

  var LOCK = 10, GO = 0.18, FLICK = 0.35, from = null;

  function offset(dx, dy) {
    reel.style.transform = dx || dy
      ? 'translate(' + dx + 'px,' + dy + 'px)' : '';
  }

  reel.addEventListener('pointerdown', function (e) {
    if (!e.isPrimary || e.clientX < 24) return;
    if (e.target.closest('button, a, input, textarea, select, [contenteditable]'))
      return;
    from = {x: e.clientX, y: e.clientY, t: e.timeStamp, axis: null};
    reel.style.transition = 'none';
  });

  reel.addEventListener('pointermove', function (e) {
    if (!from) return;
    var dx = e.clientX - from.x, dy = e.clientY - from.y;
    if (!from.axis) {
      if (Math.abs(dx) < LOCK && Math.abs(dy) < LOCK) return;
      from.axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y';
    }
    if (from.axis === 'x') offset(dx * 0.5, 0);
    else offset(0, dy * 0.3);
  });

  function release(e) {
    if (!from) return;
    var dx = e.clientX - from.x, dy = e.clientY - from.y;
    var axis = from.axis, ms = Math.max(e.timeStamp - from.t, 1);
    from = null;
    reel.style.transition = calm ? 'none' : 'transform .18s ease-out';
    offset(0, 0);
    // No axis means it never moved: a tap. The iframe cannot receive it —
    // pointer-events is off so swipes are seen at all — so play/pause is
    // handed back here rather than lost with it.
    if (!axis) {
      if (ready && player.getPlayerState) {
        if (player.getPlayerState() === 1) player.pauseVideo();
        else player.playVideo();
      }
      return;
    }
    var d = axis === 'x' ? dx : dy;
    var span = axis === 'x' ? reel.clientWidth : reel.clientHeight;
    if (Math.abs(d) < span * GO && Math.abs(d) / ms < FLICK) return;
    if (axis === 'x') decide(d > 0 ? 'known' : 'pass');
    else go(s.at + (d < 0 ? 1 : -1));      // swipe up = next, as a feed does
  }

  reel.addEventListener('pointerup', release);
  reel.addEventListener('pointercancel', function () {
    from = null;
    reel.style.transition = calm ? 'none' : 'transform .18s ease-out';
    offset(0, 0);
  });

  document.addEventListener('keydown', function (e) {
    var el = document.activeElement;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ||
               el.tagName === 'SELECT' || el.isContentEditable)) return;
    if (e.key === 'ArrowDown') { go(s.at + 1); e.preventDefault(); }
    if (e.key === 'ArrowUp') { go(s.at - 1); e.preventDefault(); }
  });
})();
