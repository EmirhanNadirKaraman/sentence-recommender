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
  apply(stored && !document.body.classList.contains('reels-page'));
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
// What YouTube says when it will not play, said out loud. The embed is built
// with `controls=0`, so a refusal has nowhere to show itself: the picture stays
// black behind a spinner and the bar below goes on offering Play. Nothing was
// listening for `onError` either, so the one message that explains it was
// being dropped. This puts it over the picture, with the way out.
var PLAYER_TROUBLE = {
  2: 'This video was asked for wrongly — the id looks invalid.',
  5: 'The browser’s player could not start this one.',
  100: 'The video is gone, or private.',
  101: 'Its owner does not allow it to be played outside YouTube.',
  150: 'Its owner does not allow it to be played outside YouTube.'
};

function playerTrouble(target, code) {
  var box = document.querySelector('.player');
  if (!box || box.querySelector('.trouble')) return;
  var url = '';
  try { url = target && target.getVideoUrl ? target.getVideoUrl() : ''; } catch (_) {}
  var note = document.createElement('p');
  note.className = 'trouble';
  note.textContent = (PLAYER_TROUBLE[code] || 'YouTube would not play this one.')
    + ' (error ' + code + ') ';
  if (url) {
    var out = document.createElement('a');
    out.href = url;
    out.target = '_blank';
    out.rel = 'noreferrer';
    out.textContent = 'Watch it on YouTube';
    note.appendChild(out);
  }
  box.appendChild(note);
}

function quietEvents(events) {
  var onState = events.onStateChange;
  events.onStateChange = function (e) {
    if (e.data === 1 || e.data === 3) captionsOff(e.target);
    if (onState) onState(e);
  };
  var onReady = events.onReady;
  events.onReady = function (e) { captionsOff(e.target); if (onReady) onReady(e); };
  var onError = events.onError;
  events.onError = function (e) {
    playerTrouble(e && e.target, e && e.data);
    if (onError) onError(e);
  };
  return events;
}

// Hearing: a subtitle counts as heard when the player has actually played
// through it -- the caption current while playing, for most of a second
// -- and then once only. Seeking past a line, or having it in the
// transcript, is not hearing it. The pages that follow a video call
// `hearing.tick` every quarter second with what is current; heard lines
// go to the server a batch at a time and once more on leaving. Every word
// of a heard line is one encounter of the word (`vocab.encounters`).
var hearing = (function () {
  var HEARD_AFTER = 0.8, TICK = 0.25;
  var playing = {}, traversed = {}, heard = {}, rewarded = {}, queue = [], video = null, pendingReward;
  function reset(id) { if (id !== video) { video = id; playing = {}; traversed = {}; heard = {}; rewarded = {}; } }
  function tick(id, index, cue, isPlaying, rate) {
    if (!id || index < 0 || !cue || !isPlaying) return;
    reset(id);
    if (rewarded[index]) return;
    playing[index] = (playing[index] || 0) + TICK;
    traversed[index] = (traversed[index] || 0) + TICK * Math.max(.25,Math.min(2,Number(rate) || 1));
    var rewardAfter = Math.max(HEARD_AFTER, (Number(cue.duration) || 1) * .75);
    var reward = traversed[index] >= rewardAfter;
    if (heard[index] && !reward) return;
    if (playing[index] < HEARD_AFTER) return;
    heard[index] = true;
    if (reward) rewarded[index] = true;
    queue.push({text:cue.text,video:id,at:cue.at,words:cue.words || [],reward:reward});
    if (reward) { clearTimeout(pendingReward); pendingReward = setTimeout(function () { flush(false); },250); }

  }
  function flush(leaving) {
    if (!queue.length) return;
    var body = JSON.stringify(queue.splice(0, queue.length));
    if (leaving && navigator.sendBeacon) {
      navigator.sendBeacon('/api/heard', new Blob([body], {type: 'application/json'}));
      return;
    }
    fetch('/api/heard', {method: 'POST', body: body, keepalive: true,
                         headers: {'Content-Type': 'application/json'}})
      .then(function (r) { if (!r.ok) throw new Error('Hearing save failed'); return r.json(); })
      .then(function (d) { if (window.journeyUpdate && d.journey) window.journeyUpdate(d.journey, true); })
      .catch(function () {});
  }
  setInterval(function () { flush(false); }, 10000);
  window.addEventListener('pagehide', function () { flush(true); });
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') flush(true);
  });
  return {tick: tick};
})();

// The control bar under every player. Whichever page made the player
// registers it here when it is ready, with a way to ask where the current
// sentence starts; the bar itself is the same everywhere.
window.__player = null;
window.__sentenceStart = null;
// The start of every subtitle of the video on screen, in order, for the
// line-by-line keys and the auto-pause; each page registers its own.
window.__cueTimes = null;
// The starts of the i+1 lines alone, for the two controls that walk
// between them. Set beside `__cueTimes` by whichever module owns the
// cues, so it is recomputed as the reader learns words.
window.__i1Times = null;

(function () {
  var bar = document.getElementById('controls');
  if (!bar) return;
  var AUTOPAUSE = 'i1-autopause';
  var autopause = false;
  try { autopause = localStorage.getItem(AUTOPAUSE) === '1'; } catch (_) {}
  // The subtitle's English, on unless it has been turned off before. Default
  // on because a reader who does not want it knows to press H, while one who
  // needs it would not know it was missing.
  var ENGLISH = 'i1-english';
  var english = true;
  try { english = localStorage.getItem(ENGLISH) !== '0'; } catch (_) {}
  var lastCue = -1;
  function live() {
    var p = window.__player;
    return p && p.getPlayerState ? p : null;
  }
  function clock(seconds) {
    seconds = Math.max(0, Math.floor(seconds || 0));
    return Math.floor(seconds / 60) + ':' + ('0' + (seconds % 60)).slice(-2);
  }
  function times() { return window.__cueTimes ? (window.__cueTimes() || []) : []; }
  function cueIndex(now) {
    var t = times(), i = -1;
    while (i + 1 < t.length && t[i + 1] <= now) i++;
    return i;
  }
  // The subtitle before: the one whose start is clearly behind the
  // playhead, so a second press goes back another line rather than
  // restarting the same one; the next: the first start ahead.
  function i1Times() {
    return window.__i1Times ? (window.__i1Times() || []) : [];
  }
  function step(p, by, list) {
    var t = list || times(), now = p.getCurrentTime(), to = null;
    if (by < 0) { for (var i = t.length - 1; i >= 0; i--) if (t[i] < now - 0.8) { to = t[i]; break; } }
    else { for (var j = 0; j < t.length; j++) if (t[j] > now + 0.05) { to = t[j]; break; } }
    if (to == null) return;
    p.seekTo(Math.max(to - 0.4, 0), true);
    p.playVideo();
  }
  function showAutopause() {
    var b = document.getElementById('autopause');
    if (b) {
      b.textContent = 'Auto-pause ' + (autopause ? 'on' : 'off');
      b.classList.toggle('on', autopause);
    }
  }
  function toggleAutopause() {
    autopause = !autopause;
    try { localStorage.setItem(AUTOPAUSE, autopause ? '1' : '0'); } catch (_) {}
    showAutopause();
  }
  // The class is on `body`, not on the caption, because the caption is
  // replaced wholesale every time the line changes and a class set on it
  // would be thrown away with it.
  function showEnglish() {
    document.body.classList.toggle('no-en', !english);
    var b = document.getElementById('english');
    if (b) {
      b.textContent = 'English ' + (english ? 'on' : 'off');
      b.classList.toggle('on', english);
      b.setAttribute('aria-pressed', english ? 'true' : 'false');
    }
  }
  function toggleEnglish() {
    english = !english;
    try { localStorage.setItem(ENGLISH, english ? '1' : '0'); } catch (_) {}
    showEnglish();
  }
  showAutopause();
  showEnglish();
  bar.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-act]');
    if (!b) return;
    // Before the player guard: hiding the English is a reading preference and
    // works whether or not the frame has finished loading.
    if (b.dataset.act === 'english') { toggleEnglish(); return; }
    var p = live();
    if (!p) return;
    var act = b.dataset.act;
    if (act === 'toggle') {
      if (p.getPlayerState() === 1) p.pauseVideo(); else p.playVideo();
    } else if (act === 'prev') {
      step(p, -1);
    } else if (act === 'next') {
      step(p, 1);
    } else if (act === 'i1prev') {
      step(p, -1, i1Times());
    } else if (act === 'i1next') {
      step(p, 1, i1Times());
    } else if (act === 'autopause') {
      toggleAutopause();
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
      var frame = document.querySelector('.reel-viewport') || document.getElementById('player');
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

  // Auto-pause: when the playhead crosses into the next subtitle, stop
  // on its first frame, so play goes on from the start of the next line.
  // Only while playing, and only forwards by one -- a seek or a new
  // video resets what "the next line" is.
  setInterval(function () {
    var p = live();
    if (!p || !p.getCurrentTime) return;
    var i = cueIndex(p.getCurrentTime());
    if (autopause && p.getPlayerState() === 1 && lastCue >= 0 && i === lastCue + 1) {
      p.pauseVideo();
      p.seekTo(times()[i], true);
    }
    lastCue = i;
  }, 100);

  // The keys YouTube's own player answers to, answered here, because the
  // frame cannot see them: arrows seek five seconds and turn the volume,
  // space and k play or pause, j and l seek ten, m mutes, v goes full
  // screen. T is the auto-pause and H hides the English under the caption.
  // The pages' own keys -- another sentence, another video, the decisions --
  // are WASD, O/P step the reel and F keeps a sentence, so the two sets
  // never fight.
  document.addEventListener('keydown', function (e) {
    var el = document.activeElement;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ||
               el.tagName === 'SELECT' || el.isContentEditable)) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    var p = live();
    if (!p) return;
    var key = e.key;
    if (document.getElementById('reel-state') && (key === 'ArrowUp' || key === 'ArrowDown')) return;
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
    // V, not F: F keeps a sentence now, and full screen is also a button in
    // the bar, so it loses a shortcut rather than the ability.
    else if (key === 'v') {
      var frame = document.querySelector('.reel-viewport') || document.getElementById('player');
      if (frame && frame.requestFullscreen) frame.requestFullscreen();
    }
    else if (key === 'q') step(p, -1);
    else if (key === 'e') step(p, 1);
    // Z and X walk the i+1 lines, as Q and E walk every line. Free keys: the
    // pages use WASD, the reel O and P, and F keeps a sentence.
    else if (key === 'z') step(p, -1, i1Times());
    else if (key === 'x') step(p, 1, i1Times());
    else if (key === 't') toggleAutopause();
    else if (key === 'h') toggleEnglish();
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
  var t = targetUnit();
  return words.map(function (w) {
    var state = t && w[1] === t.kind && w[2] === t.key ? ' target' : knownness(w[1], w[2]);
    return "<button type='button' class='w" + state + "' data-kind='" +
           escapeAttr(w[1]) + "' data-key='" + escapeAttr(w[2]) + "'>" +
           escapeText(w[0]) + "</button>";
  }).join(' ');
}

// The word being learned, where the page has one: the card's sentence
// marks it, and the caption and transcript mark it the same wherever the
// video says it, so the reader can see it coming.
function targetUnit() {
  var b = document.querySelector('.de.lead button.w.target');
  return b && b.dataset.kind && b.dataset.key ? {kind: b.dataset.kind, key: b.dataset.key} : null;
}

// Whether a word is known, as a class -- `render.clickable` does the same
// for the words the server draws. `window.__known` is the reader's units,
// served with the page (`watch.known_script`); a word no unit claims is
// neither, and a page without the set says nothing. The stylesheet only
// paints these when colours are on (Settings).
// Whether a line is i+1: exactly one distinct unit in it is unknown. The
// server marks what it renders (`web.render.one_step`); the transcript and
// the caption are redrawn here from `/api/transcript`, so the rule has to
// exist on this side too or the mark disappears the moment the cues load.
function oneStep(cue) {
  if (!cue || !cue.words || !window.__known) return false;
  var seen = {}, n = 0;
  for (var i = 0; i < cue.words.length; i++) {
    var kind = cue.words[i][1], key = cue.words[i][2];
    if (!kind || !key) continue;
    var id = kind + ':' + key;
    if (window.__known[id] || seen[id]) continue;
    seen[id] = 1;
    n++;
    if (n > 1) return false;
  }
  return n === 1;
}

function knownness(kind, key) {
  if (!kind || !key || !window.__known) return '';
  return window.__known[kind + ':' + key] ? ' known' : ' new';
}

// A word marked known on the page is known from then on: in the set the
// caption and transcript are drawn from, and on every button already drawn.
// Undo reloads the page, so there is no way back to write.
function learned(kind, key) {
  if (!kind || !key) return;
  if (window.__known) window.__known[kind + ':' + key] = 1;
  Array.prototype.forEach.call(document.querySelectorAll('button.w.new'), function (b) {
    if (b.dataset.kind === kind && b.dataset.key === key) {
      b.classList.remove('new');
      b.classList.add('known');
    }
  });
  restep();
}

// A word just learned can make a sentence i+1 that was i+2 a moment ago, so
// the marks are recounted off the buttons now that they have been repainted.
// The target counts as unknown -- it is the word being taught -- and both
// halves of a sentence carry the mark, because on some pages they are one box.
function restep() {
  Array.prototype.forEach.call(
    document.querySelectorAll('.cue, .de'), function (box) {
      var seen = {}, n = 0;
      Array.prototype.forEach.call(
        box.querySelectorAll('button.w.new, button.w.target'), function (b) {
          var id = b.dataset.kind + ':' + b.dataset.key;
          if (!b.dataset.kind || !b.dataset.key || seen[id]) return;
          seen[id] = 1;
          n++;
        });
      box.classList.toggle('i1', n === 1);
      var en = box.nextElementSibling;
      if (box.classList.contains('de') && en && en.classList.contains('en'))
        en.classList.toggle('i1', n === 1);
    });
}

function escapeText(t) {
  return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function escapeAttr(t) { return escapeText(t).replace(/'/g, '&#39;'); }

// The popup under a clicked word: the gloss of the word in that line --
// stored for the card's own word, asked of the local model for any other
// and kept -- and four dictionaries for the word itself, which answer
// different questions: dict.cc translates, DWDS gives the German sense
// with corpus evidence, Linguee shows the word in translated sentence
// pairs, Duden rules on the standard form. One popup for the whole page;
// a click on another word refills it, a click elsewhere or Escape closes
// it.
var glossBox = null;

function closeGloss() {
  if (!glossBox || glossBox.hidden) return;
  glossBox.hidden = true;
  if (glossBox.resume) { glossBox.resume(); glossBox.resume = null; }
}

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
    glossBox.hidden = true;
    document.body.appendChild(glossBox);
    document.addEventListener('click', function (e) {
      if (glossBox && !glossBox.hidden && !e.target.closest('#gloss, .w')) closeGloss();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && glossBox && !glossBox.hidden) closeGloss();
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
    "<a class='link' target='_blank' rel='noopener' href='https://www.linguee.com/" +
    "german-english/search?query=" + encodeURIComponent(lookup) + "'>Linguee \u2197</a>" +
    "<a class='link' target='_blank' rel='noopener' href='https://www.duden.de/suchen/" +
    "dudenonline/" + encodeURIComponent(lookup) + "'>Duden \u2197</a>" +
    (kind ? "<button type='button' class='known'>I know this</button>" : "") +
      (kind ? "<button type='button' class='anki'>Anki</button>" : "") +
    "<button type='button' class='use'>Use it in a sentence</button>" +
    "<button type='button' class='close'>Close</button></div>" +
    "<div class='gloss-try' hidden><textarea rows='2' placeholder='Write a German sentence with " +
    escapeAttr(lookup) + "'></textarea><div class='gloss-actions'>" +
    "<button type='button' class='go check'>Check it</button></div>" +
    "<div class='gloss-checked' hidden><p class='de'></p><p class='gloss-note'></p>" +
    "<p class='en'></p><div class='gloss-actions'><button type='button' class='go keep'>Keep it in Mine</button>" +
    "</div></div></div>";
  // Reading the gloss while the video talks on is reading nothing; the
  // video waits, and goes on when the popup goes. A second word clicked
  // while it is open refills it and keeps the first click's promise.
  if (glossBox.hidden) {
    var p = window.__player;
    var wasPlaying = !!(p && p.getPlayerState && p.getPlayerState() === 1);
    if (wasPlaying) p.pauseVideo();
    glossBox.resume = wasPlaying ? function () { if (p && p.playVideo) p.playVideo(); } : null;
  }
  glossBox.hidden = false;
  glossBox.querySelector('.close').onclick = function () { closeGloss(); };
  var knownBtn = glossBox.querySelector('.known');
  if (knownBtn) knownBtn.onclick = function () {
    var body = new URLSearchParams({kind: kind, key: key, src: src, action: 'known', back: '/'});
    knownBtn.disabled = true;
    fetch('/known', {method: 'POST', body: body, headers: {Accept: 'application/json'}, keepalive: true})
      .then(function (r) { if (!r.ok) throw new Error('Word save failed'); return r.json(); })
      .then(function (d) {
        if (window.journeyUpdate && d.journey) window.journeyUpdate(d.journey);
        knownBtn.textContent = 'Known'; learned(kind,key);
      }).catch(function () { knownBtn.disabled=false; knownBtn.textContent='Try again'; });
  };
  // Queue the word for a card, or take it out again. The button says which
  // it is rather than only doing it: the queue lives on another page, and a
  // control that looks the same before and after is one you press twice.
  var ankiBtn = glossBox.querySelector('.anki');
  if (ankiBtn) ankiBtn.onclick = function () {
    ankiBtn.disabled = true;
    fetch('/api/anki', {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams({kind: kind, key: key})
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        ankiBtn.textContent = d.queued ? 'Queued' : 'Anki';
        ankiBtn.classList.toggle('on', !!d.queued);
      })
      .catch(function () { ankiBtn.textContent = 'Anki'; })
      .then(function () { ankiBtn.disabled = false; });
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
          checked.querySelector('.gloss-note').textContent = d.say || 'The local model is not answering.';
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
  var holder = w.closest('.said, #caption, .de');
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
  //
  // What this module needs is the *player*, not the reading page's card. The
  // embed is built with `controls=0` and the bar under it drives the player
  // through the API, so a page showing a player that nobody claims cannot be
  // played at all -- which is what the video page was. It has the picture, the
  // transcript and the bar, and neither #card nor the reel's #reel-state, so
  // both modules bailed out and every button on it did nothing. The reel keeps
  // its own claim, since it drives one player through a feed of videos;
  // anything else with a player is driven from here, and the deck, the swap
  // region and the gestures are each optional.
  if (!document.getElementById('player')
      || document.getElementById('reel-state')) return;
  var card = document.getElementById('card');
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
      return "<li class='cue" + (oneStep(c) ? ' i1' : '') + "' data-i='" + i +
             "'><span class='at'>" + c.clock +
             "</span><span class='said'></span></li>";
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
    var step = oneStep(cues[i]);
    if (line) {
      line.innerHTML = wordsHtml(cues[i]);
      line.dataset.text = cues[i].text;
      line.classList.toggle('i1', step);
    }
    if (lineEn) {
      lineEn.textContent = cues[i].en || '';
      lineEn.classList.toggle('i1', step);
    }
  }

  function play(i) {
    var el = slides[i];
    if (!el) return;
    var id = el.dataset.video;
    // The remove button names a video, and this deck steps between
    // sentences from different ones without reloading -- so the server's
    // value is right for the first slide only and has to follow from here.
    // Gone entirely when the slide has no video: there is nothing to remove,
    // and a button that removed whatever was showing a moment ago would be
    // worse than no button.
    var drop = document.getElementById('drop-video');
    if (drop) {
      drop.hidden = !id;
      if (id) drop.querySelector("input[name='video']").value = id;
    }
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
      window.__cueTimes = function () { return cues.map(function (c) { return c.at; }); };
      window.__i1Times = function () {
        return cues.filter(oneStep).map(function (c) { return c.at; });
      };
      play(showing);
      setInterval(function () {
        if (!player || !player.getCurrentTime) return;
        var now = player.getCurrentTime();
        follow(now);
        var i = cueAt(cues, now);
        hearing.tick(video, i, cues[i], player.getPlayerState() === 1, player.getPlaybackRate ? player.getPlaybackRate() : 1);
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
    fetch('/known', {method: 'POST', body: body, headers: {Accept: 'application/json'},
                     keepalive: true})
      .then(function (r) { if (!r.ok) throw new Error('Word save failed'); return r.json(); })
      .then(function (d) { if (window.journeyUpdate && d.journey) window.journeyUpdate(d.journey); })
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
        if (value === 'known') { learned(was.kind, was.key); offerUndo(was.kind, was.key, was.src); }
        busy = false;
      })
      .catch(function () { b.form.submit(); });
  }

  var LOCK = 10, GO = 0.22, FLICK = 0.35, from = null;

  function offset(dx, dy) {
    if (deck) deck.style.transform = dx || dy
      ? 'translate(' + dx + 'px,' + dy + 'px)' : '';
  }

  if (card) card.addEventListener('pointerdown', function (e) {
    if (!e.isPrimary || e.clientX < 24) return;
    if (e.target.closest('button, a, input, textarea, select, [contenteditable]'))
      return;
    from = {x: e.clientX, y: e.clientY, t: e.timeStamp, axis: null};
    if (deck) deck.style.transition = 'none';
  });

  if (card) card.addEventListener('pointermove', function (e) {
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

  if (card) card.addEventListener('pointerup', function (e) {
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

  if (card) card.addEventListener('pointercancel', settle);

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

  // The picture, clicked, plays or pauses. The embed is built with
  // `controls=0`, so YouTube shows nothing to click and the reel's CSS turns
  // the frame's own pointer events off anyway -- the video page borrows the
  // reel's id and so inherited that, which left clicks landing on a `.player`
  // with nobody listening. Whichever module drives a player owns its picture,
  // so the class goes on here rather than being assumed from an id.
  var picture = document.querySelector('.player');
  if (picture) {
    picture.classList.add('driven');
    picture.addEventListener('click', function (e) {
      // The trouble note carries a link out to YouTube; a click meant for it
      // is not a click meant for the picture.
      if (e.target.closest('a, button')) return;
      var p = window.__player;
      if (!p || !p.getPlayerState) return;
      if (p.getPlayerState() === 1) p.pauseVideo(); else p.playVideo();
    });
  }

  // The reading page loads a video's cues when the deck plays it. A page with
  // no deck -- the video page -- would otherwise never load any, so the
  // caption would not follow, the line buttons would have no lines to step
  // through and auto-pause nothing to pause at. The transcript names its own
  // video for exactly this.
  if (!deck && box && box.dataset.video) loadTranscript(box.dataset.video);
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
  var track = document.getElementById('reel-track') || reel;
  var drawer = document.getElementById('reel-drawer');
  var surface = reel; // Captions and empty space are part of the same gesture.
  var title = document.getElementById('reel-title');
  var board = document.getElementById('reel-board');
  var panel = document.getElementById('reel-panel');
  var taste = document.getElementById('reel-taste');
  var counter = document.getElementById('reel-at');
  var total = document.getElementById('reel-total');
  var caption = document.getElementById('caption');
  var captionEn = document.getElementById('caption-en');
  var loading = document.getElementById('reel-loading');
  var status = document.getElementById('reel-status');
  var slot = document.getElementById('reel-controls-slot');
  var controls = reel.querySelector('.controls');
  if (slot && controls) slot.appendChild(controls);
  var calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var player = null, ready = false, busy = false, cues = [], marking = -1;
  var cache = {}, from = null, dragged = 0, wheel = 0, wheelQuiet = null, wheelLocked = false;
  var generation = 0;
  if (counter) counter.textContent = s.at + 1;
  if (total) total.textContent = s.total;
  function say(message) {
    if (!status) return;
    status.textContent = message;
    setTimeout(function () { if (status.textContent === message) status.textContent = ''; }, 3500);
  }
  function showCues(id) {
    cues = []; marking = -1;
    if (caption) caption.textContent = '';
    if (captionEn) captionEn.textContent = '';
    loadCues(id).then(function (rows) { if (id === s.video) cues = rows; });
  }
  window.onYouTubeIframeAPIReady = function () {
    player = new YT.Player('player', {events: quietEvents({
      onReady: function () {
        ready = true; window.__player = player;
        window.__sentenceStart = function () { return cues[marking] ? cues[marking].at : 0; };
        window.__cueTimes = function () { return cues.map(function (c) { return c.at; }); };
        window.__i1Times = function () { return cues.filter(oneStep).map(function (c) { return c.at; }); };
        // Muted playback works on mobile; sound remains a deliberate tap.
        try { player.mute(); player.loadVideoById({videoId:s.video,startSeconds:0}); } catch (ignore) {}
        setInterval(function () {
          if (!ready || !player.getCurrentTime) return;
          var at = cueAt(cues, player.getCurrentTime()), playing = player.getPlayerState() === 1;
          hearing.tick(s.video, at, cues[at], playing, player.getPlaybackRate ? player.getPlaybackRate() : 1);
          var toggle = document.querySelector('[data-reel-action="toggle"]');
          if (toggle) { toggle.querySelector('span').textContent = playing ? 'Ⅱ' : '▷'; toggle.querySelector('small').textContent = playing ? 'Pause' : 'Play'; }
          if (at < 0 || at === marking) return;
          marking = at;
          if (caption) { caption.innerHTML = wordsHtml(cues[at]); caption.dataset.text = cues[at].text; }
          if (captionEn) captionEn.textContent = cues[at].en || '';
        }, 250);
      },
      onStateChange: function (e) { if (loading && e.data === 1) loading.hidden = true; },
      onError: function () { if (loading) loading.hidden = true; say('This video cannot play here. Swipe to another.'); }
    })});
  };
  showCues(s.video);
  function url(at, keepVideo) {
    var q = new URLSearchParams({i: at, src: s.src, list: s.list || '', sort: s.sort || 'watch'});
    if (keepVideo) q.set('video', s.video);
    return '/api/reels?' + q.toString();
  }
  function request(at, keepVideo) {
    if (!keepVideo && cache[at]) return cache[at];
    var result = fetch(url(at, keepVideo)).then(function (r) {
      if (!r.ok) throw new Error('Feed request failed');
      return r.json();
    });
    if (!keepVideo) { cache[at] = result; result.catch(function () { delete cache[at]; }); }
    return result;
  }
  function repaintPagers() {
    document.querySelectorAll('.reel-pager a[data-act]').forEach(function (a) {
      var at = s.at + (a.dataset.act === 'harder' ? 1 : -1);
      var dead = at < 0 || at >= s.total;
      a.classList.toggle('off', dead);
      a.setAttribute('aria-disabled', dead ? 'true' : 'false');
      a.setAttribute('aria-label', a.dataset.act === 'harder' ? 'Next reel' : 'Previous reel');
      a.href = '/reels?' + new URLSearchParams({src:s.src, list:s.list || '', sort:s.sort || 'watch', i:Math.max(at,0)}).toString();
    });
  }
  function prefetch() {
    var version = generation;
    [s.at - 1, s.at + 1].forEach(function (at) {
      if (at < 0 || at >= s.total) return;
      request(at).then(function (d) {
        if (version !== generation || d.empty) return;
        var next = document.querySelector(at < s.at ? '.reel-previous' : '.reel-next');
        if (next) { next.querySelector('img').src = 'https://i.ytimg.com/vi/' + encodeURIComponent(d.video) + '/hqdefault.jpg'; next.querySelector('span').textContent = d.title; }
      }).catch(function () {});
    });
    Object.keys(cache).forEach(function (at) { if (Math.abs(Number(at) - s.at) > 1) delete cache[at]; });
  }
  function offset(y, x) { track.style.transform = y || x ? 'translate3d(' + (x || 0) + 'px,' + (y || 0) + 'px,0)' : ''; }
  function settle() {
    track.style.transition = calm ? 'none' : 'transform .22s cubic-bezier(.2,.8,.2,1)';
    offset(0, 0);
  }
  function go(at, keepVideo) {
    if (busy || at < 0 || at >= s.total) { settle(); if (at >= s.total) say('You’ve reached the end. Your atlas is waiting.'); return; }
    busy = true;
    var direction = at > s.at ? 1 : at < s.at ? -1 : 0;
    var milliseconds = calm || !direction ? 0 : 220;
    track.style.transition = calm ? 'none' : 'transform .22s cubic-bezier(.2,.8,.2,1)';
    offset(direction ? -direction * surface.clientHeight : 0, 0);
    Promise.all([request(at, keepVideo), new Promise(function (resolve) { setTimeout(resolve, milliseconds); })])
      .then(function (result) {
        var d = result[0];
        if (d.empty) { say('No more videos in this collection.'); settle(); return; }
        s.at = d.at; s.total = d.total;
        title.textContent = d.title;
        if (board) board.innerHTML = d.scoreboard;
        if (panel) panel.innerHTML = d.panel;
        if (taste) taste.innerHTML = d.taste || '';
        if (counter) counter.textContent = s.at + 1;
        if (total) total.textContent = s.total;
        var fit = reel.querySelector('.reel-fit');
        if (fit && d.familiar !== undefined) fit.textContent = Math.round(d.familiar * 100) + '% familiar';
        if (d.video !== s.video) {
          var trouble = reel.querySelector('.trouble'); if (trouble) trouble.remove();
          if (status) status.textContent='';
          s.video = d.video;
          reel.style.setProperty('--reel-poster', 'url("https://i.ytimg.com/vi/' + encodeURIComponent(d.video) + '/hqdefault.jpg")');
          if (loading) { loading.hidden = false; var loadingVideo = d.video; setTimeout(function () { if (s.video === loadingVideo) loading.hidden = true; }, 10000); }
          if (ready) player.loadVideoById({videoId: d.video, startSeconds: 0});
          showCues(d.video);
        }
        stateEl.textContent = JSON.stringify(s);
        track.style.transition = 'none'; offset(0, 0);
        history.replaceState(null, '', '/reels?' + new URLSearchParams({
          src:s.src, list:s.list || '', sort:s.sort || 'watch', i:s.at, video:s.video}).toString());
        repaintPagers();
        prefetch();
      })
      .catch(function () { settle(); say('Couldn’t load the next reel. Try again.'); })
      .then(function () { busy = false; });
  }
  repaintPagers(); prefetch();
  document.addEventListener('click', function (e) {
    var link = e.target.closest('.reel-pager a[data-act]');
    if (link) { e.preventDefault(); if (!link.classList.contains('off')) go(s.at + (link.dataset.act === 'harder' ? 1 : -1)); return; }
    var button = e.target.closest('[data-reel-action]');
    if (!button) return;
    var act = button.dataset.reelAction;
    if (act === 'close') { if (drawer) drawer.close(); return; }
    if (act === 'learn' || act === 'more') {
      if (drawer) { drawer.showModal(); if (act === 'learn') panel.scrollIntoView({block:'nearest'}); }
    } else if (ready && act === 'toggle') {
      if (player.getPlayerState() === 1) player.pauseVideo(); else player.playVideo();
    } else if (ready && act === 'mute') {
      if (player.isMuted()) player.unMute(); else player.mute();
      button.querySelector('small').textContent = player.isMuted() ? 'Sound off' : 'Sound on';
    }
  });
  if (drawer) drawer.addEventListener('click', function (e) { if (e.target === drawer) { var r = drawer.getBoundingClientRect(); if (e.clientY < r.top) drawer.close(); } });
  if (taste) taste.addEventListener('click', function (e) {
    var b = e.target.closest('button[name="taste"]');
    if (!b || !b.form) return;
    e.preventDefault();
    var body = new URLSearchParams(new FormData(b.form)); body.append('taste', b.value);
    var was = b.classList.contains('on');
    fetch('/taste', {method:'POST', body:body, redirect:'manual'}).then(function (r) {
      if (r.status >= 400) throw new Error('Taste failed');
      b.form.querySelectorAll('button[name="taste"]').forEach(function (x) { x.classList.remove('on'); x.setAttribute('aria-pressed','false'); });
      if (!was) { b.classList.add('on'); b.setAttribute('aria-pressed','true'); }
      cache = {}; generation++; prefetch();
    }).catch(function () { say('Couldn’t save that preference.'); });
  });
  function decide(value) {
    var b = panel.querySelector('button[value="' + value + '"]');
    if (!b || !b.form || busy) return;
    busy = true;
    var body = new URLSearchParams(new FormData(b.form)); body.append('action',value);
    var was = {kind:body.get('kind'), key:body.get('key'), src:body.get('src')};
    fetch('/known', {method:'POST', body:body, headers:{Accept:'application/json'}})
      .then(function (r) { if (!r.ok) throw new Error('Decision failed'); return r.json(); })
      .then(function (d) {
        if (window.journeyUpdate && d.journey) window.journeyUpdate(d.journey);
        if (value === 'known') { learned(was.kind,was.key); offerUndo(was.kind,was.key,was.src,{back:location.pathname + location.search}); }
        cache = {}; generation++; busy = false; go(s.at,true);
      }).catch(function () { busy = false; say('Couldn’t save that word. Please try again.'); });
  }
  if (panel) panel.addEventListener('click', function (e) {
    var b = e.target.closest('button[name="action"]');
    if (b && (b.value === 'known' || b.value === 'pass')) { e.preventDefault(); decide(b.value); }
  });
  // Capture after direction lock, so word taps still open their dictionary.
  function interactive(target) { return target.closest('a, input, textarea, select, [contenteditable], button:not(.w)'); }
  surface.addEventListener('pointerdown', function (e) {
    if (!e.isPrimary || busy || e.clientX < 16 || interactive(e.target)) return;
    from = {x:e.clientX,y:e.clientY,t:e.timeStamp,axis:null,id:e.pointerId};
    track.style.transition = 'none';
  });
  surface.addEventListener('pointermove', function (e) {
    if (!from) return;
    var dx = e.clientX - from.x, dy = e.clientY - from.y;
    if (!from.axis) {
      if (Math.max(Math.abs(dx),Math.abs(dy)) < 9) return;
      from.axis = Math.abs(dy) >= Math.abs(dx) ? 'y' : 'x';
      try { surface.setPointerCapture(e.pointerId); } catch (ignore) {}
    }
    if (from.axis === 'y') {
      var edge = (s.at === 0 && dy > 0) || (s.at === s.total - 1 && dy < 0);
      offset(edge ? dy * .18 : dy,0);
    } else offset(0,dx * .25);
  });
  surface.addEventListener('pointerup', function (e) {
    if (!from) return;
    var origin = from, dx = e.clientX - from.x, dy = e.clientY - from.y;
    from = null;
    if (!origin.axis) {
      if (!e.target.closest('.w') && ready) { if (player.getPlayerState() === 1) player.pauseVideo(); else player.playVideo(); }
      return;
    }
    dragged = Date.now();
    try { surface.releasePointerCapture(e.pointerId); } catch (ignore) {}
    var d = origin.axis === 'y' ? dy : dx, span = origin.axis === 'y' ? surface.clientHeight : surface.clientWidth;
    if (Math.abs(d) < span * .15 && Math.abs(d) / Math.max(e.timeStamp - origin.t,1) < .45) { settle(); return; }
    if (origin.axis === 'y') go(s.at + (d < 0 ? 1 : -1));
    else { settle(); decide(d > 0 ? 'known' : 'pass'); }
  });
  surface.addEventListener('pointercancel', function () { from = null; settle(); });
  document.addEventListener('click', function (e) {
    if (Date.now() - dragged < 300 && reel.contains(e.target)) { e.preventDefault(); e.stopImmediatePropagation(); }
  },true);
  surface.addEventListener('wheel', function (e) {
    if (e.ctrlKey || e.metaKey || (drawer && drawer.open)) return;
    e.preventDefault();
    clearTimeout(wheelQuiet);
    wheelQuiet = setTimeout(function () { wheel = 0; wheelLocked = false; },180);
    if (wheelLocked || busy) return;
    var delta = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? surface.clientHeight : 1);
    wheel += delta;
    if (Math.abs(wheel) >= 60) { wheelLocked = true; go(s.at + (wheel > 0 ? 1 : -1)); wheel = 0; }
  },{passive:false});
  document.addEventListener('keydown', function (e) {
    if ((drawer && drawer.open) || e.target.closest('input,textarea,select,[contenteditable]') || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 's' || e.key === 'p' || e.key === 'ArrowDown' || e.key === 'PageDown') { e.preventDefault(); go(s.at + 1); }
    if (e.key === 'w' || e.key === 'o' || e.key === 'ArrowUp' || e.key === 'PageUp') { e.preventDefault(); go(s.at - 1); }
    if (e.key === 'd') { e.preventDefault(); decide('known'); }
    if (e.key === 'a') { e.preventDefault(); decide('pass'); }
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


// The star after a sentence, wherever one is drawn. Posted rather than
// followed: the control is on every page, and a reload to move a bookmark
// would lose the reader's place on all of them -- mid-deck, mid-reel,
// halfway down the review queue.
document.addEventListener('click', function (e) {
  var star = e.target.closest("button.star[data-act='star']");
  if (!star) return;
  var holder = star.closest('.de');
  var text = holder && holder.dataset.text;
  if (!text || star.disabled) return;
  star.disabled = true;
  fetch('/api/star', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: 'text=' + encodeURIComponent(text)
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.ok) return;
      // Every copy of this sentence on the page, not just the one clicked:
      // the reel panel and the deck can both be showing it, and two stars
      // disagreeing about one sentence is worse than neither moving.
      var same = document.querySelectorAll(".de[data-text]");
      for (var i = 0; i < same.length; i++) {
        if (same[i].dataset.text !== text) continue;
        var b = same[i].querySelector("button.star");
        if (!b) continue;
        b.classList.toggle('on', d.starred);
        b.setAttribute('aria-pressed', d.starred ? 'true' : 'false');
      }
    })
    .catch(function () {})
    .then(function () { star.disabled = false; });
});


// F keeps the sentence being read. Its own listener rather than a branch in
// the player's, because that one gives up when there is no player on the
// page -- and Mine, Roadmap, Frontier and Starred all draw sentences with no
// video anywhere near them.
//
// "Being read" is the first star the reader can actually see: the deck hides
// every slide but one, and a hidden element has no offsetParent, so that is
// the whole test. The lead sentence wins where a page has one, since that is
// the sentence the page is about rather than an example under it.
document.addEventListener('keydown', function (e) {
  if (e.key !== 'f' && e.key !== 'F') return;
  var el = document.activeElement;
  if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ||
             el.tagName === 'SELECT' || el.isContentEditable)) return;
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  var shown = function (b) { return b.offsetParent !== null; };
  var lead = [].filter.call(
    document.querySelectorAll(".de.lead button.star[data-act='star']"), shown);
  var any = [].filter.call(
    document.querySelectorAll("button.star[data-act='star']"), shown);
  var pick = lead[0] || any[0];
  if (!pick) return;
  pick.click();
  e.preventDefault();
});

// The keyboard shortcuts, on every page and named where they apply.
//
// They were written down once, in a `.hint` under the study card's stepper,
// and the reel, the video page and the review queue each answered to keys
// nobody had been told about. Which keys work depends on what the page is
// showing, so the list is built from what is actually on it -- a page with no
// player does not claim to answer to Q and E -- rather than each handler
// being asked to remember a list that would drift from the bindings above.
(function () {
  // The script is loaded from inside <main>, and the panel's markup sits
  // after it, so at this point the elements are not parsed yet. Every other
  // module here is anchored on something inside <main> and does not notice.
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', start);
  else start();

  function start() {
  var open = document.getElementById('keys-open');
  var panel = document.getElementById('keys');
  if (!open || !panel) return;

  // Each group names the thing it belongs to and the element that proves the
  // page has one. The keys themselves are the bindings in the modules above;
  // a group whose anchor is missing is not shown.
  var GROUPS = [
    {anchor: '#controls', title: 'The video', keys: [
      ['Space', 'play or pause'], ['K', 'play or pause'],
      ['&larr; &rarr;', 'five seconds back or on'],
      ['J L', 'ten seconds back or on'],
      ['Q E', 'the subtitle before or after'],
      ['Z X', 'the i+1 line before or after'],
      ['T', 'pause after every line'],
      ['H', 'hide or show the English'],
      ['M', 'sound off or on'], ['V', 'full screen'],
      ['&uarr; &darr;', 'louder or quieter']]},
    {anchor: '#deck', title: 'The sentences', keys: [
      ['W S', 'another sentence for this word'],
      ['D', 'I know this word'], ['A', 'not yet']]},
    {anchor: '#reel-state', title: 'The reel', keys: [
      ['W O', 'the video before'], ['S P', 'the next video'],
      ['D', 'I know the word it offers'], ['A', 'set that word aside']]},
    {anchor: '#quiz-card', title: 'Review', keys: [
      ['D Y', 'I knew it'], ['A N', 'I did not'], ['S', 'skip it']]},
    {anchor: "button.star[data-act='star']", title: 'Any sentence', keys: [
      ['F', 'keep this one']]}
  ];

  function build() {
    var out = "<div class='keys-head'><b>Keyboard</b>" +
      "<button type='button' class='keys-close' aria-label='Close'>" +
      "&times;</button></div>";
    var any = false;
    GROUPS.forEach(function (g) {
      if (!document.querySelector(g.anchor)) return;
      any = true;
      out += "<h3>" + g.title + "</h3><dl>";
      g.keys.forEach(function (k) {
        out += "<dt><kbd>" + k[0] + "</kbd></dt><dd>" + k[1] + "</dd>";
      });
      out += "</dl>";
    });
    if (!any) out += "<p class='quiet'>This page answers to no keys of its " +
      "own — the ones below work wherever they apply.</p>";
    out += "<h3>Anywhere</h3><dl>" +
      "<dt><kbd>?</kbd></dt><dd>this list</dd>" +
      "<dt><kbd>Esc</kbd></dt><dd>close it</dd></dl>";
    panel.innerHTML = out;
  }

  function show(on) {
    if (on && !panel.innerHTML) build();
    // Rebuilt each time it opens: a word marked known can add the star
    // control to a page that had none, and the reel swaps its own card out.
    else if (on) build();
    panel.hidden = !on;
    open.setAttribute('aria-expanded', on ? 'true' : 'false');
  }

  open.addEventListener('click', function () { show(panel.hidden); });
  panel.addEventListener('click', function (e) {
    if (e.target.closest('.keys-close')) show(false);
  });
  document.addEventListener('keydown', function (e) {
    var el = document.activeElement;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ||
               el.tagName === 'SELECT' || el.isContentEditable)) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === '?') { show(panel.hidden); e.preventDefault(); }
    else if (e.key === 'Escape' && !panel.hidden) { show(false); e.preventDefault(); }
  });
  }
})();

// The phone's section picker remains a native disclosure without JavaScript.
// Escape and clicking outside dismiss it when scripting is available.
(function () {
  function bind() {
    var more = document.querySelector('.more-nav');
    if (!more) return;
    document.addEventListener('click', function (e) {
      if (more.open && !more.contains(e.target)) more.open = false;
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && more.open) {
        more.open = false;
        more.querySelector('summary').focus();
      }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
})();

// --- the atlas: feedback follows committed reader state ---------------------
(function () {
  var node = document.getElementById('journey-state');
  if (!node) return;
  var current;
  try { current = JSON.parse(node.textContent); } catch (ignore) { return; }
  var key = 'i1-journey-' + current.identity;
  var previous = null, celebrationTimer, toastTimer, soundContext;
  var calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  try { previous = JSON.parse(localStorage.getItem(key) || 'null'); } catch (ignore) {}
  function remember(data) {
    try { localStorage.setItem(key, JSON.stringify({xp:data.xp,level:data.level,day:data.day,
      badges:data.badges.filter(function (b) { return b.earned; }).map(function (b) { return b.key; }),
      chapter:data.chapter_complete})); } catch (ignore) {}
  }
  function closeCelebration() {
    var old = document.getElementById('reward-celebration');
    if (old) old.remove();
    document.querySelectorAll('.reward-particle').forEach(function (p) { p.remove(); });
  }
  function chime() {
    var on = false;
    try { on = localStorage.getItem('i1-reward-sound') === '1'; } catch (ignore) {}
    if (!on || !soundContext || soundContext.state !== 'running') return;
    [523.25,659.25,783.99].forEach(function (pitch,i) {
      var oscillator = soundContext.createOscillator(), gain = soundContext.createGain();
      var at = soundContext.currentTime + i * .07;
      oscillator.type = 'sine'; oscillator.frequency.value = pitch;
      gain.gain.setValueAtTime(0,at); gain.gain.linearRampToValueAtTime(.045,at + .015);
      gain.gain.exponentialRampToValueAtTime(.001,at + .24);
      oscillator.connect(gain); gain.connect(soundContext.destination);
      oscillator.start(at); oscillator.stop(at + .25);
    });
  }
  document.addEventListener('pointerdown', function () {
    var on = false; try { on = localStorage.getItem('i1-reward-sound') === '1'; } catch (ignore) {}
    var Audio = window.AudioContext || window.webkitAudioContext;
    if (on && Audio) { if (!soundContext) soundContext = new Audio(); if (soundContext.state === 'suspended') soundContext.resume().catch(function () {}); }
  },{passive:true});
  var toggle = document.getElementById('reward-sound');
  if (toggle) {
    try { toggle.checked = localStorage.getItem('i1-reward-sound') === '1'; } catch (ignore) {}
    toggle.addEventListener('change',function () { try { localStorage.setItem('i1-reward-sound',toggle.checked ? '1' : '0'); } catch (ignore) {} });
  }
  function celebrate(title, detail, eyebrow) {
    closeCelebration(); clearTimeout(celebrationTimer);
    var box = document.createElement('section');
    box.id = 'reward-celebration'; box.className = 'reward-celebration';
    box.setAttribute('role','status'); box.setAttribute('aria-live','polite');
    box.innerHTML = "<div class='reward-card'><button class='reward-close' type='button' aria-label='Dismiss achievement'>×</button>" +
      "<span class='reward-mark'>✦</span><span class='eyebrow'>" + escapeText(eyebrow || 'ACHIEVEMENT UNLOCKED') +
      "</span><h2>" + escapeText(title) + "</h2><p>" + escapeText(detail) +
      "</p><a href='/journey" + escapeAttr(location.search) + "'>Explore your atlas ↗</a></div>";
    document.body.appendChild(box);
    box.querySelector('button').onclick = closeCelebration;
    if (!calm) {
      for (var i=0;i<20;i++) {
        var particle = document.createElement('i'); particle.className = 'reward-particle';
        particle.style.setProperty('--x',(30 + Math.random() * 40) + 'vw');
        particle.style.setProperty('--drift',((Math.random() - .5) * 220) + 'px');
        particle.style.setProperty('--spin',Math.random() * 180 + 'deg');
        document.body.appendChild(particle);
      }
    }
    chime();
    celebrationTimer = setTimeout(closeCelebration,6000);
  }
  function toast(points, quiet) {
    var old = document.getElementById('reward-toast'); if (old) old.remove();
    clearTimeout(toastTimer);
    var box = document.createElement('div'); box.id='reward-toast'; box.className='reward-toast';
    box.setAttribute('role','status'); box.setAttribute('aria-live','polite');
    var session = 0;
    try { session = Number(sessionStorage.getItem(key) || 0); } catch (ignore) {}
    box.innerHTML = '<b>✦ +' + points + ' XP</b><span>' + (quiet ? 'Real voices. Real progress.' : 'Your world just grew.') +
      '</span><small>' + session + ' this session</small>';
    document.body.appendChild(box);
    toastTimer = setTimeout(function () { box.remove(); },quiet ? 1800 : 2600);
  }
  function paint(data) {
    document.querySelectorAll('[data-journey="rank"]').forEach(function (el) { el.textContent=data.rank; });
    var regionStyle = Math.floor((data.level - 1) / 7) % 3;
    var lands = ['M0 206l50-29 50 15 72-43 62 34 48-47 61 34 54-27 103 37v60H0z',
      'M0 212l55-60 40 20 65-95 70 116 67-103 59 91 65-45 79 79v25H0z',
      'M0 210q60-20 110 0t110 0t110 0t170 0v30H0z M100 207q30-45 62 0 M306 207q26-60 58 0'];
    document.querySelectorAll('[data-atlas-land]').forEach(function (el) { el.setAttribute('d',lands[regionStyle]); });
    document.querySelectorAll('[data-atlas-sky]').forEach(function (el) { el.setAttribute('stop-color',['#122348','#172247','#0f273a'][regionStyle]); });
    document.querySelectorAll('.atlas-scene').forEach(function (el) { el.setAttribute('aria-label','Your atlas grows with your journey: level ' + data.level); });
    var lit = (data.level - 1) % 7 + 1;
    document.querySelectorAll('[data-atlas-step]').forEach(function (el) {
      var step = Number(el.dataset.atlasStep);
      el.classList.toggle('lit',step <= lit); el.classList.toggle('sleeping',step > lit);
      el.querySelector('circle').setAttribute('r',step === lit ? 12 : 7);
    });
    document.querySelectorAll('[data-atlas-region]').forEach(function (el) { el.textContent='REGION ' + (Math.floor((data.level - 1) / 7) + 1); });
    var points = [[65,132],[127,101],[197,129],[246,67],[320,100],[365,42],[431,79]];
    document.querySelectorAll('.atlas-thread').forEach(function (el) { el.setAttribute('points',points.slice(0,lit).map(function (p) { return p.join(','); }).join(' ')); });
    document.querySelectorAll('[data-journey="xp"]').forEach(function (el) { el.textContent = data.xp.toLocaleString(); });
    document.querySelectorAll('[data-journey="level"]').forEach(function (el) { el.textContent=data.level; el.style.setProperty('--fill',data.percent + '%'); });
    document.querySelectorAll('[data-journey="quests"]').forEach(function (el) { el.textContent=data.quest_done + '/3'; });
    document.querySelectorAll('[data-journey="remaining"]').forEach(function (el) { el.textContent=data.remaining + ' to level ' + (data.level+1); });
    var xpBar = document.querySelector('.xp-progress');
    if (xpBar) { xpBar.max=data.ceiling - data.floor; xpBar.value=data.xp - data.floor; }
    data.quests.forEach(function (q) {
      var card = document.querySelector('[data-quest="' + q.key + '"]'); if (!card) return;
      card.classList.toggle('complete',q.value >= q.target);
      card.querySelector('[data-quest-count]').textContent=q.value + '/' + q.target;
      card.querySelector('progress').value=q.value;
      card.querySelector('.quest-go').textContent=(q.value >= q.target ? 'Explore more' : 'Let’s go') + ' ↗';
    });
    if (data.chapter_complete) {
      var title = document.getElementById('expedition-title'); if (title) title.textContent='A chapter well spent.';
      var chapter = document.querySelector('.chapter-reward'); if (chapter) chapter.textContent='✓ Chapter complete';
    }
  }
  function update(data, quiet, baseline) {
    if (!data || data.identity !== current.identity) return;
    var old = baseline || {xp:current.xp,level:current.level,day:current.day,
      badges:current.badges.filter(function (b) { return b.earned; }).map(function (b) { return b.key; }),chapter:current.chapter_complete};
    var points = data.xp - old.xp;
    var fresh = data.badges.filter(function (b) { return b.earned && (old.badges || []).indexOf(b.key) < 0; });
    current = data; paint(data); remember(data);
    if (points <= 0) return;
    try { sessionStorage.setItem(key,String(Number(sessionStorage.getItem(key) || 0) + points)); } catch (ignore) {}
    var drawer = document.getElementById('reel-drawer');
    if (drawer && drawer.open) {
      var last = drawer.querySelector('.drawer-reward'); if (last) last.remove();
      var note = document.createElement('div'); note.className='drawer-reward'; note.setAttribute('role','status');
      var win = data.chapter_complete && (!old.chapter || old.day !== data.day) ? 'Daily expedition complete' :
        data.level > old.level ? 'Level ' + data.level + ' · ' + data.rank : fresh.length ? fresh[0].name : 'Your atlas just grew';
      note.textContent='✦ +' + points + ' XP · ' + win;
      drawer.querySelector('.drawer-head').insertAdjacentElement('afterend',note);
      if (fresh.length || data.level > old.level || data.chapter_complete && !old.chapter) chime();
      setTimeout(function () { note.remove(); },6000);
      return;
    }
    if (data.chapter_complete && (!old.chapter || old.day !== data.day)) celebrate('Today’s chapter complete.', 'Three small quests. A little more of the world is yours. +20 bonus XP.', 'EXPEDITION COMPLETE');
    else if (data.level > old.level) celebrate(data.rank, 'Welcome to chapter ' + data.level + '. Your atlas has a new light.', 'LEVEL UP · ' + data.level);
    else if (fresh.length) celebrate(fresh[0].name, fresh[0].detail + (fresh.length > 1 ? ' And ' + (fresh.length - 1) + ' more achievement' + (fresh.length > 2 ? 's' : '') + '.' : ''), 'ACHIEVEMENT UNLOCKED');
    else toast(points,quiet);
  }
  window.journeyUpdate = update;
  paint(current);
  if (previous) update(current,false,previous); else remember(current);
  document.addEventListener('keydown',function (e) { if (e.key === 'Escape') closeCelebration(); });
  // A full-page form returns new state in its HTML. AJAX learning/hearing calls
  // use the same update function, so there is no polling loop or view reward.
})();
