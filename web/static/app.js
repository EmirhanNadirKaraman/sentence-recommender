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

  document.addEventListener('keydown', function (e) {
    var el = document.activeElement;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ||
               el.tagName === 'SELECT' || el.isContentEditable)) return;
    if (e.key === 'ArrowLeft') { show(showing - 1); e.preventDefault(); }
    if (e.key === 'ArrowRight') { show(showing + 1); e.preventDefault(); }
  });
})();
