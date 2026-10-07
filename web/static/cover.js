/* A draft stays in the page until the reader explicitly saves and builds. */
(function () {
  'use strict';
  var root = document.getElementById('cover-builder');
  if (!root) return;
  var query = document.getElementById('cover-query');
  var name = document.getElementById('cover-name');
  var results = document.getElementById('cover-search-results');
  var status = document.getElementById('cover-search-status');
  var selected = document.getElementById('cover-selected');
  var count = document.getElementById('cover-count');
  var build = document.getElementById('cover-build');
  var buildStatus = document.getElementById('cover-build-status');
  var output = document.getElementById('cover-result');
  var draft = new Map();
  var found = [], timer, controller, revision = 0, busy = false;
  var original = name.value;
  function identity(word) { return JSON.stringify([word.kind, word.key]); }
  function node(tag, text, cls) {
    var el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }
  function link(text, url, cls) {
    var el = node('a', text, cls); el.href = url; return el;
  }
  JSON.parse(root.dataset.selected || '[]').forEach(function (word) { draft.set(identity(word), word); });
  function changed() {
    output.replaceChildren(); buildStatus.textContent = '';
    renderSelection(); renderResults();
  }
  function renderSelection() {
    selected.replaceChildren(); count.textContent = draft.size;
    if (!draft.size) selected.append(node('p', 'Select words from the results to start your collection.', 'quiet'));
    draft.forEach(function (word, id) {
      var chip = node('div', undefined, 'cover-word-chip');
      chip.append(node('span', word.key));
      var remove = node('button', '×'); remove.type = 'button';
      remove.setAttribute('aria-label', 'Remove ' + word.key); remove.disabled = busy;
      remove.addEventListener('click', function () { draft.delete(id); changed(); });
      chip.append(remove); selected.append(chip);
    });
    build.disabled = busy || !draft.size || !name.value.trim() || draft.size > 100;
    name.disabled = busy; query.disabled = busy;
  }
  function renderResults() {
    results.replaceChildren();
    found.forEach(function (word) {
      var added = draft.has(identity(word));
      var row = node('button', undefined, 'cover-search-item'); row.type = 'button';
      row.disabled = busy || added || draft.size >= 100;
      var label = node('span'); label.append(node('strong', word.key));
      label.append(node('small', (word.kind === 'pattern' ? 'Expression' : 'Word') +
        ' · ' + word.said.toLocaleString() + ' occurrences' + (word.known ? ' · Already known' : '')));
      row.append(label, node('span', added ? 'Added ✓' : '+ Add', 'cover-add'));
      row.setAttribute('aria-label', (added ? 'Added ' : 'Add ') + word.key);
      row.addEventListener('click', function () { draft.set(identity(word), {kind:word.kind, key:word.key}); changed(); });
      results.append(row);
    });
  }
  query.addEventListener('input', function () {
    clearTimeout(timer); if (controller) controller.abort();
    var current = ++revision, needle = query.value.trim(); found = []; renderResults();
    if (!needle) { status.textContent = 'Your next discovery starts with a word.'; return; }
    status.textContent = 'Searching…';
    timer = setTimeout(async function () {
      controller = new AbortController();
      try {
        var params = new URLSearchParams({q:needle, src:root.dataset.src});
        // Keep the page's vocabulary normalization and reader context.
        var list = new URL(location.href).searchParams.get('list'); if (list) params.set('list', list);
        var response = await fetch('/api/cover-search?' + params, {signal:controller.signal});
        if (!response.ok) throw new Error('Search could not load. Check your connection or sign in again.');
        var data = await response.json(); if (current !== revision) return;
        found = data.results || []; renderResults();
        status.textContent = found.length ? found.length + ' matches · choose the words that interest you' : 'No matches. Try another spelling.';
      } catch (error) {
        if (current === revision && error.name !== 'AbortError') status.textContent = error.message;
      }
    }, 160);
  });
  query.addEventListener('keydown', function (event) {
    if (event.key === 'ArrowDown') { var first = results.querySelector('button:not(:disabled)'); if (first) { event.preventDefault(); first.focus(); } }
  });
  name.addEventListener('input', function () { output.replaceChildren(); buildStatus.textContent = ''; renderSelection(); });
  function renderCover(data) {
    output.replaceChildren();
    var heading = node('div', undefined, 'cover-result-heading');
    heading.append(node('span', 'YOUR PERSONAL VIDEO COVER', 'eyebrow'));
    var complete = !data.unreachable.length;
    heading.append(node('h2', data.videos.length ?
      data.videos.length + ' video' + (data.videos.length === 1 ? '' : 's') + '. ' + data.covered + ' word' + (data.covered === 1 ? '' : 's') + ' within reach.' :
      (data.known.length === data.total ? 'You already know every word.' : 'These words need more support.')));
    heading.append(node('p', data.covered + ' of ' + data.total + ' selected words covered with i+1 examples · ' +
      data.minutes + ' min' + (data.videos.some(function(v){return v.estimated;}) ? ' (some durations estimated)' : ''), 'note'));
    if (data.videos.length) heading.append(node('p', data.optimal ?
      'The minimum number of videos for ' + (complete ? 'these words' : 'the coverable words') + ', with shorter total duration breaking ties.' :
      'A verified cover. The search reached its time limit, so minimum size is not proven.', 'quiet'));
    heading.append(node('p', 'Every example uses your current known words. Selecting a word does not mark it as learned.', 'quiet'));
    heading.append(link('Open saved collection ↗', data.list_url, 'link'));
    output.append(heading);
    if (data.known.length) output.append(node('p', 'Already known · ' + data.known.join(' · '), 'cover-known'));
    if (data.unreachable.length) {
      var missing = node('div', undefined, 'cover-unreachable');
      missing.append(node('h3', 'Not covered yet'), node('p', data.unreachable.join(' · ')),
        node('small', 'No available video sentence has one of these as your only unknown. Your list is saved; learn supporting words or add more videos, then rebuild.'));
      output.append(missing);
    }
    data.videos.forEach(function (video, index) {
      var card = node('article', undefined, 'cover-video-card');
      var top = node('div', undefined, 'cover-video-heading');
      top.append(node('span', String(index + 1).padStart(2, '0'), 'cover-video-number'));
      var title = node('div'); title.append(link(video.title, video.url),
        node('p', video.examples.length + ' selected word' + (video.examples.length === 1 ? '' : 's') + ' · ' + (video.estimated ? '≥ ' : '') + video.minutes + ' min', 'quiet'));
      top.append(title, link('Watch', video.url, 'go')); card.append(top);
      video.examples.forEach(function (example) {
        var line = node('div', undefined, 'cover-example');
        line.append(node('span', example.word, 'cover-target'), node('p', example.text),
          link(example.time + ' ↗', example.url, 'cover-time')); card.append(line);
      });
      output.append(card);
    });
  }
  build.addEventListener('click', async function () {
    if (busy || !draft.size) return;
    busy = true; renderSelection(); renderResults(); output.replaceChildren();
    buildStatus.textContent = 'Saving your list and finding its smallest cover… The first build may take a moment.';
    root.setAttribute('aria-busy', 'true');
    try {
      var form = new URLSearchParams({name:name.value.trim(), original:original,
        selected:JSON.stringify(Array.from(draft.values())), src:root.dataset.src});
      var list = new URL(location.href).searchParams.get('list'); if (list) form.set('list', list);
      var response = await fetch('/api/cover', {method:'POST', body:form, headers:{Accept:'application/json'}});
      if (!response.ok) throw new Error('The cover could not be built. Your selection is still here; try again or sign in again.');
      var data = await response.json();
      if (data.saved) original = data.saved;
      if (data.error) throw new Error(data.error);
      original = data.name; name.value = data.name;
      var url = new URL(location.href); url.searchParams.set('name', data.name); history.replaceState(null, '', url);
      renderCover(data); buildStatus.textContent = 'Collection saved. Cover checked against your current knowledge.';
      output.scrollIntoView({block:'start', behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
    } catch (error) { buildStatus.textContent = error.message; }
    finally { busy = false; root.removeAttribute('aria-busy'); renderSelection(); renderResults(); }
  });
  renderSelection();
})();
