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
// Listening rather than watching. Remembered in the browser, because it is a
// property of how the phone is being held this minute, not of what is being
// learned — and applied to <body> so both pages get it from one place.
(function () {
  var KEY = 'i1-audio';

  // Keeping the screen awake, and only while listening.
  //
  // Safari suspends a page when the screen sleeps, which stops the video —
  // so on a run the audio dies a minute after the phone goes in your pocket.
  // A wake lock is the fix, and it is deliberately tied to this mode rather
  // than held always: it costs battery, and "I am listening" is exactly the
  // signal that the screen going dark would be a problem.
  //
  // The lock is dropped by the browser whenever the page is hidden and is
  // not given back on its own, so it is re-taken on every return to
  // visibility. Everything here is guarded: it needs a secure context and
  // iOS 16.4, and where it is missing the mode still works, the screen just
  // sleeps as it always did.
  var lock = null;

  function hold() {
    if (!('wakeLock' in navigator) || lock) return;
    navigator.wakeLock.request('screen').then(function (l) {
      lock = l;
      l.addEventListener('release', function () { lock = null; });
    }).catch(function () { lock = null; });   // refused: low battery, hidden
  }

  function release() {
    if (!lock) return;
    var l = lock;
    lock = null;
    try { l.release(); } catch (e) {}
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible'
        && document.body.classList.contains('audio')) hold();
  });

  function apply(on) {
    document.body.classList.toggle('audio', on);
    var b = document.getElementById('mode');
    if (b) b.textContent = on ? 'watching, not listening'
                              : 'listening, not watching';
    if (on) hold(); else release();
  }
  var stored = false;
  try { stored = localStorage.getItem(KEY) === '1'; } catch (e) {}
  apply(stored);
  var b = document.getElementById('mode');
  if (b) b.onclick = function () {
    var on = !document.body.classList.contains('audio');
    apply(on);
    // A browser that refuses storage still toggles; it just forgets.
    try { localStorage.setItem(KEY, on ? '1' : '0'); } catch (e) {}
  };
})();

// Taking back "I know this".
//
// It is the only destructive thing here, and a right swipe is a gesture you
// will sometimes make by accident. The bar is appended to the body rather
// than to the page region, because deciding a word replaces that region and
// the offer has to outlive it.
function offerUndo(kind, key, src, opts) {
  opts = opts || {};
  var endpoint = opts.endpoint || '/known';
  var back = opts.back || '/';
  var old = document.getElementById('undo-bar');
  if (old) old.remove();
  var bar = document.createElement('div');
  bar.id = 'undo-bar';
  bar.className = 'undo';
  var said = document.createElement('span');
  said.textContent = opts.label || ('Marked ' + key + ' known');
  var go = document.createElement('button');
  go.type = 'button';
  go.textContent = 'Undo';
  go.onclick = function () {
    var body = new URLSearchParams({kind: kind, key: key, src: src || '',
                                    back: back, action: 'undo'});
    fetch(endpoint, {method: 'POST', body: body, redirect: 'manual'})
      .catch(function () {})
      .then(function () { location.reload(); });
  };
  bar.appendChild(said);
  bar.appendChild(go);
  document.body.appendChild(bar);
  // Long enough to notice and reach, short enough not to sit there.
  setTimeout(function () { if (bar.parentNode) bar.remove(); }, 8000);
}

// The two things both the reading page and the reels feed need from a
// video's cues, and the only two they agree on. What they do with a cue
// differs — one marks a line in a full transcript beside the picture, the
// other has just the caption under it — so the fetching and the lookup are
// shared and the drawing is not.
//
// Cached across both: the feed goes back and forth between videos, and the
// deck can touch a dozen, so asking twice for the same cues is the common
// case rather than the rare one.
var CUES = {};

function loadCues(id) {
  if (!id) return Promise.resolve([]);
  if (CUES[id]) return Promise.resolve(CUES[id]);
  return fetch('/api/transcript?video=' + encodeURIComponent(id))
    .then(function (r) { return r.json(); })
    .then(function (d) { CUES[id] = d.cues || []; return CUES[id]; })
    .catch(function () { return []; });
}

// YouTube's own captions off. There is no parameter for it -- the embed
// follows the viewer's YouTube preference -- but the API can unload the
// captions module, once the module exists, which is after each video
// loads; so it is done on every change of state into buffering or
// playing. Our caption sits under the picture, the words clickable, and
// the burnt-in one was doubling it, half cropped.
function captionsOff(player) {
  try { if (player && player.unloadModule) player.unloadModule('captions'); }
  catch (_) {}
}
function quietEvents(events) {
  var onState = events.onStateChange;
  events.onStateChange = function (e) {
    if (e.data === 1 || e.data === 3) captionsOff(e.target);
    if (onState) onState(e);
  };
  var onReady = events.onReady;
  events.onReady = function (e) { captionsOff(e.target); if (onReady) onReady(e); };
  return events;
}

// The control bar under every player. Whichever page made the player
// registers it here when it is ready, with a way to ask where the current
// sentence starts; the bar itself is the same everywhere.
window.__player = null;
window.__sentenceStart = null;

(function () {
  var bar = document.getElementById('controls');
  if (!bar) return;
  function live() {
    var p = window.__player;
    return p && p.getPlayerState ? p : null;
  }
  function clock(seconds) {
    seconds = Math.max(0, Math.floor(seconds || 0));
    return Math.floor(seconds / 60) + ':' + ('0' + (seconds % 60)).slice(-2);
  }
  bar.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-act]');
    var p = live();
    if (!b || !p) return;
    var act = b.dataset.act;
    if (act === 'toggle') {
      if (p.getPlayerState() === 1) p.pauseVideo(); else p.playVideo();
    } else if (act === 'back') {
      p.seekTo(Math.max(p.getCurrentTime() - 5, 0), true);
    } else if (act === 'fwd') {
      p.seekTo(p.getCurrentTime() + 5, true);
    } else if (act === 'sentence') {
      var at = window.__sentenceStart ? window.__sentenceStart() : null;
      if (at != null) { p.seekTo(Math.max(at - 0.4, 0), true); p.playVideo(); }
    } else if (act === 'rate') {
      var rate = p.getPlaybackRate() === 1 ? 0.75 : 1;
      p.setPlaybackRate(rate);
      b.textContent = rate + '\u00d7';
    } else if (act === 'mute') {
      if (p.isMuted()) { p.unMute(); b.textContent = 'Sound off'; }
      else { p.mute(); b.textContent = 'Sound on'; }
    } else if (act === 'full') {
      var frame = document.getElementById('player');
      if (frame && frame.requestFullscreen) frame.requestFullscreen();
      else if (frame && frame.webkitRequestFullscreen) frame.webkitRequestFullscreen();
    }
  });
  setInterval(function () {
    var p = live();
    if (!p) return;
    var toggle = document.getElementById('toggle');
    if (toggle) toggle.textContent = p.getPlayerState() === 1 ? 'Pause' : 'Play';
    var at = document.getElementById('clock');
    if (at && p.getCurrentTime)
      at.textContent = clock(p.getCurrentTime()) + ' / ' + clock(p.getDuration());
  }, 500);

  // The keys YouTube's own player answers to, answered here, because the
  // frame cannot see them: arrows seek five seconds and turn the volume,
  // space and k play or pause, j and l seek ten, m mutes, f goes full
  // screen. The pages' own keys -- another sentence, another video, the
  // decisions -- are WASD, so the two sets never fight.
  document.addEventListener('keydown', function (e) {
    var el = document.activeElement;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ||
               el.tagName === 'SELECT' || el.isContentEditable)) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    var p = live();
    if (!p) return;
    var key = e.key;
    if (key === 'ArrowLeft') p.seekTo(Math.max(p.getCurrentTime() - 5, 0), true);
    else if (key === 'ArrowRight') p.seekTo(p.getCurrentTime() + 5, true);
    else if (key === 'ArrowUp') p.setVolume(Math.min(p.getVolume() + 5, 100));
    else if (key === 'ArrowDown') p.setVolume(Math.max(p.getVolume() - 5, 0));
    else if (key === ' ' || key === 'k') {
      if (p.getPlayerState() === 1) p.pauseVideo(); else p.playVideo();
    }
    else if (key === 'j') p.seekTo(Math.max(p.getCurrentTime() - 10, 0), true);
    else if (key === 'l') p.seekTo(p.getCurrentTime() + 10, true);
    else if (key === 'm') { if (p.isMuted()) p.unMute(); else p.mute(); }
    else if (key === 'f') {
      var frame = document.getElementById('player');
      if (frame && frame.requestFullscreen) frame.requestFullscreen();
    }
    else return;
    e.preventDefault();
  });
})();

// A subtitle line as words a reader can click. Each word is a button --
// buttons are what the swipe handlers leave alone, and what a finger can
// hit -- carrying the unit it wears, where the corpus knows one. Clicking
// opens `glossPopup` below: what the word means in this line, and the way
// to a dictionary.
function wordsHtml(cue) {
  var words = cue.words && cue.words.length
    ? cue.words : cue.text.split(/\s+/).map(function (w) { return [w, '', '']; });
  return words.map(function (w) {
    return "<button type='button' class='w' data-kind='" + escapeAttr(w[1]) +
           "' data-key='" + escapeAttr(w[2]) + "'>" + escapeText(w[0]) + "</button>";
  }).join(' ');
}

function escapeText(t) {
  return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function escapeAttr(t) { return escapeText(t).replace(/'/g, '&#39;'); }

// The popup under a clicked word: the gloss of the word in that line --
// stored for the card's own word, asked of the local model for any other
// and kept -- and dict.cc and DWDS for the word itself. One popup for the
// whole page; a click on another word refills it, a click elsewhere or
// Escape closes it.
var glossBox = null;

function glossPopup(button, lineText) {
  var kind = button.dataset.kind || '', key = button.dataset.key || '';
  var token = button.textContent.replace(/^[„"“”'(\[…\-–—]+|[.,;:!?„“”"')\]…\-–—]+$/g, '');
  var lookup = kind === 'lemma' ? key
             : kind === 'pattern' ? key.replace(/\(.*?\)/g, '').trim().split(/\s+/).pop()
             : token;
  if (!glossBox) {
    glossBox = document.createElement('div');
    glossBox.className = 'gloss';
    glossBox.id = 'gloss';
    document.body.appendChild(glossBox);
    document.addEventListener('click', function (e) {
      if (glossBox && !glossBox.hidden && !e.target.closest('#gloss, .w'))
        glossBox.hidden = true;
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && glossBox) glossBox.hidden = true;
    });
  }
  var src = (document.querySelector('input[name="src"]') || {}).value || '';
  var state = document.getElementById('reel-state');
  if (!src && state) { try { src = JSON.parse(state.textContent).src || ''; } catch (_) {} }
  glossBox.innerHTML =
    "<div class='gloss-word'><strong>" + escapeText(token) + "</strong>" +
    (key && key !== token ? " <span class='gloss-key'>" + escapeText(key) + "</span>" : "") +
    "</div><p class='gloss-means'>…</p><div class='gloss-examples'></div>" +
    "<div class='gloss-actions'>" +
    "<a class='link' target='_blank' rel='noopener' href='https://www.dict.cc/?s=" +
    encodeURIComponent(lookup) + "'>dict.cc \u2197</a>" +
    "<a class='link' target='_blank' rel='noopener' href='https://www.dwds.de/wb/" +
    encodeURIComponent(lookup) + "'>DWDS \u2197</a>" +
    (kind ? "<button type='button' class='known'>I know this</button>" : "") +
    "<button type='button' class='use'>Use it in a sentence</button>" +
    "<button type='button' class='close'>Close</button></div>" +
    "<div class='gloss-try' hidden><textarea rows='2' placeholder='Write a German sentence with " +
    escapeAttr(lookup) + "'></textarea><div class='gloss-actions'>" +
    "<button type='button' class='go check'>Check it</button></div>" +
    "<div class='gloss-checked' hidden><p class='de'></p><p class='gloss-note'></p>" +
    "<p class='en'></p><div class='gloss-actions'><button type='button' class='go keep'>Keep it in Mine</button>" +
    "</div></div></div>";
  glossBox.hidden = false;
  glossBox.querySelector('.close').onclick = function () { glossBox.hidden = true; };
  var knownBtn = glossBox.querySelector('.known');
  if (knownBtn) knownBtn.onclick = function () {
    var body = new URLSearchParams({kind: kind, key: key, src: src, action: 'known', back: '/'});
    knownBtn.disabled = true;
    fetch('/known', {method: 'POST', body: body, redirect: 'manual', keepalive: true})
      .catch(function () {})
      .then(function () { knownBtn.textContent = 'Known'; });
  };
  var means = glossBox.querySelector('.gloss-means');
  var examples = glossBox.querySelector('.gloss-examples');
  fetch('/api/gloss?text=' + encodeURIComponent(lineText) + '&word=' + encodeURIComponent(token) +
        '&kind=' + encodeURIComponent(kind) + '&key=' + encodeURIComponent(key) +
        (src ? '&src=' + encodeURIComponent(src) : ''))
    .then(function (r) { return r.json(); })
    .then(function (d) {
      means.textContent = d.means || 'No gloss — the local model is not answering.';
      if (d.known && knownBtn) { knownBtn.textContent = 'Known'; knownBtn.disabled = true; }
      examples.innerHTML = (d.examples || []).map(function (x) {
        return "<p class='de'>" + escapeText(x.text) + "</p>" +
               (x.en ? "<p class='en'>" + escapeText(x.en) + "</p>" : "");
      }).join('');
    })
    .catch(function () { means.textContent = 'No gloss — the local model is not answering.'; });

  // Writing a sentence with the word: checked by the model, kept into Mine.
  var tryBox = glossBox.querySelector('.gloss-try');
  glossBox.querySelector('.use').onclick = function () {
    tryBox.hidden = !tryBox.hidden;
    if (!tryBox.hidden) tryBox.querySelector('textarea').focus();
  };
  var checked = glossBox.querySelector('.gloss-checked');
  glossBox.querySelector('.check').onclick = function () {
    var written = tryBox.querySelector('textarea').value.trim();
    if (!written) return;
    var b = glossBox.querySelector('.check');
    b.disabled = true; b.textContent = 'Checking…';
    fetch('/api/try', {method: 'POST',
                       body: new URLSearchParams({word: lookup, kind: kind, key: key, sentence: written})})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        b.disabled = false; b.textContent = 'Check it';
        if (d.error || !d.german) {
          checked.hidden = false;
          checked.querySelector('.de').textContent = '';
          checked.querySelector('.gloss-note').textContent = 'The local model is not answering.';
          checked.querySelector('.en').textContent = '';
          checked.querySelector('.keep').hidden = true;
          return;
        }
        checked.hidden = false;
        checked.querySelector('.de').textContent = d.german;
        checked.querySelector('.gloss-note').textContent = d.note;
        checked.querySelector('.en').textContent = d.english;
        var keep = checked.querySelector('.keep');
        keep.hidden = false; keep.disabled = false; keep.textContent = 'Keep it in Mine';
        keep.onclick = function () {
          keep.disabled = true;
          fetch('/mine', {method: 'POST', redirect: 'manual',
                          body: new URLSearchParams({action: 'keep', german: d.german,
                                                     english: d.english, src: src})})
            .catch(function () {})
            .then(function () { keep.textContent = 'Kept \u2713'; });
        };
      })
      .catch(function () { b.disabled = false; b.textContent = 'Check it'; });
  };
}

// One listener for every subtitle line on the page, wherever it is drawn.
document.addEventListener('click', function (e) {
  var w = e.target.closest('button.w');
  if (!w) return;
  var holder = w.closest('.said, #caption');
  glossPopup(w, holder ? holder.dataset.text || holder.textContent : w.textContent);
});

// Which cue is being spoken at `now`, or -1 if there are none. A linear
// scan: cues are in order and this runs four times a second, so finding the
// place costs less than keeping an index would.
function cueAt(cues, now) {
  if (!cues.length) return -1;
  var i = 0;
  while (i + 1 < cues.length && cues[i + 1].at <= now) i++;
  return i;
}

(function () {
  // #reading-top and #reading are replaced when a word is decided; the
  // player and the transcript sit outside them and survive. Anything looked
  // up inside a replaced region has to be looked up again afterwards, which
  // is what `bind` is for — and the gesture listeners hang off #card, which
  // is one of the survivors, so they are attached once.
  var card = document.getElementById('card');
  if (!card) return;
  var region = document.getElementById('reading');
  var top = document.getElementById('reading-top');
  var box = document.getElementById('transcript');
  var calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var player = null, ready = false, busy = false;
  var cues = [], marking = -1, video = null;
  var deck, slides, at, stage, line, lineEn, showing = 0;

  function bind() {
    deck = document.getElementById('deck');
    slides = deck
      ? Array.prototype.slice.call(deck.querySelectorAll('.slide')) : [];
    at = document.getElementById('at');
    stage = document.getElementById('stage');
    line = document.getElementById('caption');
    lineEn = document.getElementById('caption-en');
    showing = 0;
    var p = document.getElementById('prev'), n = document.getElementById('next');
    if (p) p.onclick = function () { show(showing - 1); };
    if (n) n.onclick = function () { show(showing + 1); };
  }

  function keepInView(el) {
    if (!box || !el) return;
    var wanted = el.offsetTop - box.offsetTop
               - (box.clientHeight / 2) + (el.clientHeight / 2);
    var to = Math.max(0, Math.min(wanted, box.scrollHeight - box.clientHeight));
    if (box.scrollTo) box.scrollTo({top: to, behavior: calm ? 'auto' : 'smooth'});
    else box.scrollTop = to;
  }

  function drawTranscript(rows) {
    cues = rows || [];
    if (!box) return;
    box.innerHTML = cues.map(function (c, i) {
      return "<li class='cue' data-i='" + i + "'><span class='at'>" +
             c.clock + "</span><span class='said'></span></li>";
    }).join('');
    Array.prototype.forEach.call(box.querySelectorAll('.cue'), function (el, i) {
      var said = el.querySelector('.said');
      said.innerHTML = wordsHtml(cues[i]);
      said.dataset.text = cues[i].text;
      el.addEventListener('click', function (e) {
        // A word opens its gloss; the rest of the line seeks the video.
        if (e.target.closest('button.w')) return;
        if (player && player.seekTo) {
          player.seekTo(Math.max(cues[i].at - 0.4, 0), true);
          player.playVideo();
        }
      });
    });
    marking = -1;
  }

  function loadTranscript(id) {
    if (!box || !id) return;
    loadCues(id).then(drawTranscript);
  }

  function follow(now) {
    if (!box) return;
    var i = cueAt(cues, now);
    if (i < 0 || i === marking) return;
    var all = box.querySelectorAll('.cue');
    if (all[marking]) all[marking].classList.remove('now');
    marking = i;
    if (all[i]) { all[i].classList.add('now'); keepInView(all[i]); }
    if (line) { line.innerHTML = wordsHtml(cues[i]); line.dataset.text = cues[i].text; }
    if (lineEn) lineEn.textContent = cues[i].en || '';
  }

  function play(i) {
    var el = slides[i];
    if (!el) return;
    var id = el.dataset.video;
    if (!id) {
      // Hidden is not stopped: the stage is display:none and the iframe
      // inside it plays on, so a transcript sentence after a video one
      // arrived with the last clip still talking underneath it.
      if (stage) stage.hidden = true;
      if (ready && player.pauseVideo) player.pauseVideo();
      return;
    }
    if (stage) stage.hidden = false;
    var start = Math.max(parseFloat(el.dataset.at) - 0.4, 0);
    if (!ready) return;
    if (id === video) player.seekTo(start, true);
    else { video = id; player.loadVideoById({videoId: id, startSeconds: start}); }
    loadTranscript(id);
  }

  function show(i) {
    if (slides.length < 2) return;
    slides[showing].hidden = true;
    showing = (i + slides.length) % slides.length;
    slides[showing].hidden = false;
    if (at) at.textContent = showing + 1;
    if (line) line.textContent = '';
    if (lineEn) lineEn.textContent = '';
    play(showing);
  }

  window.onYouTubeIframeAPIReady = function () {
    player = new YT.Player('player', {events: quietEvents({onReady: function () {
      ready = true;
      window.__player = player;
      window.__sentenceStart = function () {
        var el = slides[showing];
        return el && el.dataset.at ? parseFloat(el.dataset.at) : null;
      };
      play(showing);
      setInterval(function () {
        if (player && player.getCurrentTime) follow(player.getCurrentTime());
      }, 250);
    }})});
  };

  // A decision, without the page reload it used to cost. Anything unexpected
  // falls back to submitting the form the old way — slower, but it is the
  // behaviour that already worked, and a silent no-op here would look like
  // the swipe simply being ignored.
  function decide(value) {
    var b = document.querySelector('.actions button[value="' + value + '"]');
    if (!b || !b.form || busy) return;
    // A card with no region to swap — the word page — decides the old
    // way: the form posts and comes back to where it was.
    if (!region) { b.form.submit(); return; }
    busy = true;
    var body = new URLSearchParams(new FormData(b.form));
    body.append('action', value);
    var was = {kind: body.get('kind'), key: body.get('key'),
               src: body.get('src')};
    fetch('/known', {method: 'POST', body: body, redirect: 'manual',
                     keepalive: true})
      // The study page swaps in a video's next word the same way; it names
      // its route on the region.
      .then(function () {
        return fetch((region.dataset.api || '/api/next') + window.location.search);
      })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.empty || !d.html) { location.reload(); return; }
        if (top && d.top) top.innerHTML = d.top;
        region.innerHTML = d.html;
        bind();
        // The player sits outside the replaced region on purpose, so a
        // decision does not tear down the iframe — which means it also keeps
        // whatever the last deck left on it. A slide with no video hides the
        // stage, and nothing here put it back, so deciding from such a slide
        // lost the video for every word after it: still playing, just
        // hidden, until a prev/next click happened to call `play` again.
        //
        // `play` is that one authority and knows both directions, so it is
        // called rather than reimplemented. It also reads the slide actually
        // on screen: the payload named the first sentence in the deck with a
        // video, which is not always the first one shown, so the player
        // could open on a clip belonging to a sentence further down.
        if (d.video && !stage) { location.reload(); return; }
        play(showing);
        if (value === 'known') offerUndo(was.kind, was.key, was.src);
        busy = false;
      })
      .catch(function () { b.form.submit(); });
  }

  var LOCK = 10, GO = 0.22, FLICK = 0.35, from = null;

  function offset(dx, dy) {
    if (deck) deck.style.transform = dx || dy
      ? 'translate(' + dx + 'px,' + dy + 'px)' : '';
  }

  card.addEventListener('pointerdown', function (e) {
    if (!e.isPrimary || e.clientX < 24) return;
    if (e.target.closest('button, a, input, textarea, select, [contenteditable]'))
      return;
    from = {x: e.clientX, y: e.clientY, t: e.timeStamp, axis: null};
    if (deck) deck.style.transition = 'none';
  });

  card.addEventListener('pointermove', function (e) {
    if (!from) return;
    var dx = e.clientX - from.x, dy = e.clientY - from.y;
    if (!from.axis) {
      if (Math.abs(dx) < LOCK && Math.abs(dy) < LOCK) return;
      from.axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y';
    }
    if (from.axis === 'x') offset(dx * 0.6, 0);
    else offset(0, dy * 0.4);
  });

  function settle() {
    from = null;
    if (deck) deck.style.transition = calm ? 'none' : 'transform .18s ease-out';
    offset(0, 0);
  }

  card.addEventListener('pointerup', function (e) {
    if (!from) return;
    var dx = e.clientX - from.x, dy = e.clientY - from.y;
    var axis = from.axis, ms = Math.max(e.timeStamp - from.t, 1);
    settle();
    if (!axis) return;
    var d = axis === 'x' ? dx : dy;
    var span = axis === 'x' ? card.clientWidth : card.clientHeight;
    if (Math.abs(d) < span * GO && Math.abs(d) / ms < FLICK) return;
    if (axis === 'x') decide(d > 0 ? 'known' : 'pass');
    else show(showing + (d < 0 ? 1 : -1));
  });

  card.addEventListener('pointercancel', settle);

  document.addEventListener('keydown', function (e) {
    var el = document.activeElement;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ||
               el.tagName === 'SELECT' || el.isContentEditable)) return;
    // The same rule as the gestures: vertical is another one of these,
    // horizontal decides -- and D is a write, it marks a word known, which
    // is why the hint under the stepper names both axes. WASD rather than
    // the arrows, which the player has (see the controls block).
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 's') { show(showing + 1); e.preventDefault(); }
    if (e.key === 'w') { show(showing - 1); e.preventDefault(); }
    if (e.key === 'd') { decide('known'); e.preventDefault(); }
    if (e.key === 'a') { decide('pass'); e.preventDefault(); }
  });

  bind();
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
  // The picture, not the whole card: everything under it has to stay
  // scrollable or the page cannot be read to the bottom.
  var surface = reel.querySelector('.player') || reel;
  var title = document.getElementById('reel-title');
  var board = document.getElementById('reel-board');
  var panel = document.getElementById('reel-panel');
  var taste = document.getElementById('reel-taste');
  var counter = document.getElementById('reel-at');
  var caption = document.getElementById('caption');
  var captionEn = document.getElementById('caption-en');
  var cues = [], marking = -1;
  var calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var player = null, ready = false, busy = false;

  // The line being spoken, under the picture. The feed plays muted by
  // default and a reel is chosen by how well it plays with your hands full,
  // so what is being said has to be readable without sound. The full
  // transcript the reading page carries would not fit a swipe feed; the
  // caption is the part that belongs here.
  function showCues(id) {
    marking = -1;
    if (caption) caption.textContent = '';
    if (captionEn) captionEn.textContent = '';
    loadCues(id).then(function (rows) {
      if (id === s.video) cues = rows;
    });
  }

  window.onYouTubeIframeAPIReady = function () {
    player = new YT.Player('player', {events: quietEvents({onReady: function () {
      ready = true;
      window.__player = player;
      window.__sentenceStart = function () {
        return cues[marking] ? cues[marking].at : 0;
      };
      setInterval(function () {
        if (!player || !player.getCurrentTime) return;
        var i = cueAt(cues, player.getCurrentTime());
        if (i < 0 || i === marking) return;
        marking = i;
        if (caption) { caption.innerHTML = wordsHtml(cues[i]); caption.dataset.text = cues[i].text; }
        if (captionEn) captionEn.textContent = cues[i].en || '';
      }, 250);
    }})});
  };

  showCues(s.video);

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
        if (taste) taste.innerHTML = d.taste || '';
        if (counter) counter.textContent = d.at + 1;
        // The URL follows so a reload lands where you are, without the
        // navigation that would take the player with it.
        history.replaceState(null, '', '/reels?src=' +
          encodeURIComponent(s.src) + '&i=' + d.at);
        if (d.video !== s.video) {
          s.video = d.video;
          if (ready) player.loadVideoById({videoId: d.video, startSeconds: 0});
          showCues(d.video);
        }
      })
      .catch(function () {})
      .then(function () { busy = false; });
  }

  // Saying more or less of a channel, without leaving the page and without
  // reordering the feed under you. The server toggles — pressing the chosen
  // one takes the opinion back — so the button state is flipped to match and
  // the new order arrives with the next swipe, which is the moment it can be
  // seen without something jumping out from under a thumb.
  if (taste) taste.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('button[name="taste"]') : null;
    if (!b || !b.form) return;
    e.preventDefault();
    var body = new URLSearchParams(new FormData(b.form));
    body.append('taste', b.value);
    var was = b.classList.contains('on');
    fetch('/taste', {method: 'POST', body: body, redirect: 'manual',
                     keepalive: true})
      .catch(function () {})
      .then(function () {
        var all = b.form.querySelectorAll('button[name="taste"]');
        Array.prototype.forEach.call(all, function (x) {
          x.classList.remove('on');
          x.setAttribute('aria-pressed', 'false');
        });
        if (!was) {
          b.classList.add('on');
          b.setAttribute('aria-pressed', 'true');
        }
      });
  });

  // The panel's own forms, posted without leaving the page — a navigation
  // here would destroy the player, which is the thing this whole file exists
  // to avoid.
  function decide(value) {
    var b = panel.querySelector('button[value="' + value + '"]');
    if (!b || !b.form || busy) return;
    busy = true;
    var body = new FormData(b.form);
    body.append('action', value);
    var was = {kind: body.get('kind'), key: body.get('key'),
               src: body.get('src')};
    fetch('/known', {method: 'POST', body: new URLSearchParams(body),
                     redirect: 'manual', keepalive: true})
      .catch(function () {})
      .then(function () {
        busy = false;
        if (value === 'known') offerUndo(was.kind, was.key, was.src);
        go(s.at);            // the word is gone; the panel behind it moved on
      });
  }

  var LOCK = 10, GO = 0.18, FLICK = 0.35, from = null;

  function offset(dx, dy) {
    reel.style.transform = dx || dy
      ? 'translate(' + dx + 'px,' + dy + 'px)' : '';
  }

  surface.addEventListener('pointerdown', function (e) {
    if (!e.isPrimary || e.clientX < 24) return;
    if (e.target.closest('button, a, input, textarea, select, [contenteditable]'))
      return;
    from = {x: e.clientX, y: e.clientY, t: e.timeStamp, axis: null};
    reel.style.transition = 'none';
  });

  surface.addEventListener('pointermove', function (e) {
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
    var span = axis === 'x' ? surface.clientWidth : surface.clientHeight;
    if (Math.abs(d) < span * GO && Math.abs(d) / ms < FLICK) return;
    if (axis === 'x') decide(d > 0 ? 'known' : 'pass');
    else go(s.at + (d < 0 ? 1 : -1));      // swipe up = next, as a feed does
  }

  surface.addEventListener('pointerup', release);
  surface.addEventListener('pointercancel', function () {
    from = null;
    reel.style.transition = calm ? 'none' : 'transform .18s ease-out';
    offset(0, 0);
  });

  document.addEventListener('keydown', function (e) {
    var el = document.activeElement;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ||
               el.tagName === 'SELECT' || el.isContentEditable)) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 's') { go(s.at + 1); e.preventDefault(); }
    if (e.key === 'w') { go(s.at - 1); e.preventDefault(); }
    if (e.key === 'd') { decide('known'); e.preventDefault(); }
    if (e.key === 'a') { decide('pass'); e.preventDefault(); }
  });
})();


// --- the quiz --------------------------------------------------------------
//
// Same two gestures as the reading page and the opposite stakes. There, right
// marks a word known and left sets it aside for a while; here BOTH answers
// write, and the left one comments a line out of a file under version
// control. So both offer undo, and the vertical axis is left alone — the page
// scrolls, because there is no deck to step through and a swipe up that ate a
// question would be worse than no gesture at all.
(function () {
  var card = document.getElementById('quiz-card');
  if (!card) return;
  var region = document.getElementById('quiz');
  var calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var busy = false;

  function deck() { return region.querySelector('.deck'); }

  function answer(value) {
    var b = region.querySelector('.actions button[value="' + value + '"]');
    if (!b || !b.form || busy) return;
    busy = true;
    var body = new URLSearchParams(new FormData(b.form));
    body.append('action', value);
    var was = {kind: body.get('kind'), key: body.get('key'),
               src: body.get('src'),
               written: (region.querySelector('h2') || {}).textContent || ''};
    fetch('/quiz', {method: 'POST', body: body, redirect: 'manual',
                    keepalive: true})
      .then(function () {
        return fetch('/api/quiz' + window.location.search);
      })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.html) { location.reload(); return; }
        region.innerHTML = d.html;
        if (value !== 'skip') {
          offerUndo(was.kind, was.key, was.src, {
            endpoint: '/quiz',
            back: '/quiz' + window.location.search,
            label: value === 'know'
              ? 'Confirmed ' + was.written
              : 'Struck ' + was.written + ' from the list'
          });
        }
        busy = false;
      })
      .catch(function () { b.form.submit(); });
  }

  // Another sentence for the same word. The alternatives travel with the
  // question, so this is a swap rather than a request — and it rotates rather
  // than running out, because the reason to ask for another is that the one
  // on screen did not help, and the reason to ask twice is the same reason.
  // Delegated: the region is replaced with every question.
  card.addEventListener('click', function (e) {
    var b = e.target.closest('.another');
    if (!b) return;
    var box = region.querySelector('.example'), more;
    if (!box) return;
    try { more = JSON.parse(box.getAttribute('data-more') || '[]'); }
    catch (err) { more = []; }
    var p = box.querySelector('.de');
    if (!more.length || !p) return;
    var showing = p.textContent;
    p.textContent = more.shift();
    more.push(showing);
    box.setAttribute('data-more', JSON.stringify(more));
  });

  var LOCK = 10, GO = 0.22, FLICK = 0.35, from = null;

  function offset(dx) {
    var d = deck();
    if (d) d.style.transform = dx ? 'translateX(' + dx + 'px)' : '';
  }

  card.addEventListener('pointerdown', function (e) {
    if (!e.isPrimary || e.clientX < 24) return;
    if (e.target.closest('button, a, input, textarea, select, [contenteditable]'))
      return;
    from = {x: e.clientX, y: e.clientY, t: e.timeStamp, axis: null};
    var d = deck();
    if (d) d.style.transition = 'none';
  });

  card.addEventListener('pointermove', function (e) {
    if (!from) return;
    var dx = e.clientX - from.x, dy = e.clientY - from.y;
    if (!from.axis) {
      if (Math.abs(dx) < LOCK && Math.abs(dy) < LOCK) return;
      // Once it is a scroll it stays a scroll: no answer is recorded from a
      // gesture that started as someone reading down the page.
      from.axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y';
    }
    if (from.axis === 'x') offset(dx * 0.6);
  });

  function settle() {
    from = null;
    var d = deck();
    if (d) d.style.transition = calm ? 'none' : 'transform .18s ease-out';
    offset(0);
  }

  card.addEventListener('pointerup', function (e) {
    if (!from) return;
    var dx = e.clientX - from.x, axis = from.axis;
    var ms = Math.max(e.timeStamp - from.t, 1);
    settle();
    if (axis !== 'x') return;
    if (Math.abs(dx) < card.clientWidth * GO && Math.abs(dx) / ms < FLICK) return;
    answer(dx > 0 ? 'know' : 'no');
  });

  card.addEventListener('pointercancel', settle);

  document.addEventListener('keydown', function (e) {
    var el = document.activeElement;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ||
               el.tagName === 'SELECT' || el.isContentEditable)) return;
    if (e.key === 'd' || e.key === 'y') { answer('know'); e.preventDefault(); }
    if (e.key === 'a' || e.key === 'n') { answer('no'); e.preventDefault(); }
    if (e.key === 's') { answer('skip'); e.preventDefault(); }
  });
})();
