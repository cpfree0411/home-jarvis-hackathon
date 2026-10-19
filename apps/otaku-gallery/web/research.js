/*
 * Research Guide panel. The server owns every research session; this page only
 * starts, polls, cancels and renders one. All remote/model text is placed with
 * textContent, and every link comes from the server's own fetched source records.
 */
(function () {
  'use strict';
  var App = window.OtakuApp, S = window.OTAKU_STRINGS;
  var root = document.getElementById('research');
  if (!App || !root) return;
  var el = App.el;
  var POLL_MS = 700, POLL_FAILS = 6, CLIENT_WALL_MS = 80000;

  var input = root.querySelector('.rs-input');
  var form = root.querySelector('.rs-search');
  var goButton = root.querySelector('.rs-go');
  var body = root.querySelector('.rs-body');
  var article = root.querySelector('.rs-article');
  var progress = root.querySelector('.rs-progress');
  var progressText = root.querySelector('.rs-progress-text');
  var progressSub = root.querySelector('.rs-progress-sub');
  var steps = root.querySelectorAll('.rs-step');
  var topicsBar = root.querySelector('.rs-topics');
  var toast = root.querySelector('.rs-toast');
  var keyboard = root.querySelector('.rs-keyboard');
  var openButton = document.getElementById('research-open');

  var run = 0, sessionId = null, pollTimer = null, startedAt = 0, fails = 0, lastPayload = null;
  var item = null, focusBefore = null, toastTimer = null, isOpen = false;

  /* ------------------------------------------------------------ safety helpers */
  function safeSourceUrl(url) {
    return typeof url === 'string' && url.length < 600 &&
      /^https:\/\/(?:en\.wikipedia\.org\/wiki\/|anilist\.co\/(?:anime|manga|character)\/\d+)[^\s<>"'\\]*$/.test(url);
  }
  function showToast(text) {
    toast.textContent = text; toast.hidden = false;
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () { toast.hidden = true; }, 4200);
  }
  function api(method, path, payload) {
    var opts = {method: method, headers: {Accept: 'application/json'}};
    if (payload !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(payload); }
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {ok: false, error: {message: S.failed.text}}; });
    });
  }

  /* ------------------------------------------------------------ rendering helpers */
  function chips(ids, sources) {
    var wrap = el('span', 'rs-cites');
    (ids || []).forEach(function (id) {
      var n = sources.findIndex(function (s) { return s.id === id; });
      if (n >= 0) wrap.appendChild(el('span', 'rs-cite', String(n + 1)));
    });
    return wrap;
  }
  function caveat(entry) {
    if (entry.verified !== false) return null;
    var b = el('span', 'rs-caveat', '\u26a0 ' + (entry.source_ids && entry.source_ids.length ? S.unverified : S.noCitation));
    b.title = S.unverifiedLong; return b;
  }
  function notice(title, text, extra) {
    var box = el('section', 'rs-notice');
    box.appendChild(el('h2', null, title));
    if (text) box.appendChild(el('p', null, text));
    if (extra) box.appendChild(extra);
    return box;
  }
  function chipRow(list) {
    var wrap = el('div', 'rs-chips');
    list.forEach(function (entry) {
      var b = el('button', 'rs-chip', entry.label); b.type = 'button';
      if (entry.note) b.title = entry.note;
      b.addEventListener('click', function () { search(entry.query); });
      wrap.appendChild(b);
    });
    return wrap;
  }
  function retryButton() {
    var b = el('button', 'rs-chip rs-retry', S.retry); b.type = 'button';
    b.addEventListener('click', function () { if (lastPayload) begin(lastPayload); });
    return b;
  }
  function sourcesBlock(sources) {
    var block = el('section', 'rs-sources');
    block.appendChild(el('h3', null, S.sections.sources));
    var list = el('ol');
    sources.forEach(function (s) {
      var li = el('li', s.cited ? 'is-cited' : '');
      li.appendChild(el('span', 'rs-source-provider', s.provider));
      if (safeSourceUrl(s.url)) {
        var a = el('a', null, s.title);
        a.href = s.url; a.rel = 'noopener noreferrer'; a.target = '_blank';
        if (App.kiosk) a.addEventListener('click', function (e) { e.preventDefault(); showToast(S.linkToast + decodeURI(s.url)); });
        li.appendChild(a);
      } else li.appendChild(el('span', null, s.title));
      var tags = [];
      if (s.bundled_snapshot) tags.push(S.sourceSnapshot + (s.snapshot_date ? ' ' + s.snapshot_date : ''));
      if (s.license) tags.push(s.license);
      if (!s.cited) tags.push(S.sourceUnused);
      if (tags.length) li.appendChild(el('span', 'rs-source-note', tags.join(' \u00b7 ')));
      list.appendChild(li);
    });
    block.appendChild(list);
    block.appendChild(el('p', 'rs-fine', S.sourcesFine));
    return block;
  }

  function renderPage(view) {
    var page = view.page || {}, sources = page.sources || [];
    article.replaceChildren();
    var status = page.status;
    if (status === 'needs_query') { article.appendChild(notice(S.needsQuery.title, S.needsQuery.text)); return; }
    if (status === 'unsafe') { article.appendChild(notice(S.unsafe.title, S.unsafe.text)); return; }
    if (status === 'rate_limited') {
      article.appendChild(notice(S.rateLimited.title, S.rateLimited.text(view.retry_after || 5), retryButton())); return;
    }
    if (status === 'not_found') {
      article.appendChild(notice(S.notFound.title, page.reason === 'sources_unavailable' ? S.notFound.sourcesDown : S.notFound.text, retryButton()));
      if (sources.length) article.appendChild(sourcesBlock(sources));
      return;
    }
    if (status === 'ambiguous') {
      article.appendChild(notice(S.ambiguous.title, S.ambiguous.text, chipRow((page.candidates || []).map(function (c) {
        return {label: c.label, note: c.note, query: c.query};
      }))));
      if (page.sections && page.sections.length) page.sections.forEach(function (sec) { article.appendChild(sectionBlock(sec, sources)); });
      article.appendChild(sourcesBlock(sources));
      return;
    }
    if (status === 'evidence_only') {
      var extra = el('div');
      if (page.reason === 'nebius_key_unavailable') extra.appendChild(el('p', 'rs-fine', S.keyMissing));
      else if (page.reason_message) extra.appendChild(el('p', 'rs-fine', S.evidenceOnly.reasonPrefix + page.reason_message));
      extra.appendChild(retryButton());
      article.appendChild(notice(S.evidenceOnly.title, S.evidenceOnly.text, extra));
      (page.sections || []).forEach(function (sec) { article.appendChild(sectionBlock(sec, sources, true)); });
      article.appendChild(sourcesBlock(sources));
      return;
    }
    /* answered */
    var head = el('header', 'rs-head');
    var tags = el('div', 'rs-tags');
    if (S.kinds[page.entity_kind]) tags.appendChild(el('span', 'rs-tag', S.kinds[page.entity_kind]));
    if (S.confidence[page.confidence]) tags.appendChild(el('span', 'rs-tag is-' + page.confidence, S.confidence[page.confidence]));
    tags.appendChild(el('span', 'rs-tag is-model', S.chips.model));
    if (view.cached) tags.appendChild(el('span', 'rs-tag', S.chips.cached));
    if (sources.some(function (s) { return s.bundled_snapshot; })) tags.appendChild(el('span', 'rs-tag', S.chips.snapshot));
    head.appendChild(tags);
    head.appendChild(el('h1', null, page.title || view.query));
    if (page.title_original && page.title_original !== page.title) head.appendChild(el('p', 'rs-original', page.title_original));
    if (page.tagline) head.appendChild(el('p', 'rs-tagline', page.tagline));
    article.appendChild(head);
    if (page.overview) {
      var lead = el('p', 'rs-lead', page.overview);
      lead.appendChild(chips(page.overview_source_ids, sources));
      if (page.overview_verified === false) lead.appendChild(caveat({verified: false, source_ids: page.overview_source_ids}));
      article.appendChild(lead);
    }
    if (page.facts && page.facts.length) {
      var dl = el('dl', 'rs-facts');
      page.facts.forEach(function (fact) {
        var row = el('div'), dd = el('dd', null, fact.value);
        dd.appendChild(chips(fact.source_ids, sources));
        var c = caveat(fact); if (c) dd.appendChild(c);
        row.appendChild(el('dt', null, fact.label)); row.appendChild(dd); dl.appendChild(row);
      });
      article.appendChild(dl);
    }
    (page.sections || []).forEach(function (sec) { article.appendChild(sectionBlock(sec, sources)); });
    if (page.related && page.related.length) {
      var rel = el('section', 'rs-section'); rel.appendChild(el('h2', null, S.sections.related));
      var ul = el('ul', 'rs-related');
      page.related.forEach(function (r) {
        var li = el('li'); li.appendChild(el('strong', null, r.name)); li.appendChild(document.createTextNode(r.relation));
        li.appendChild(chips(r.source_ids, sources));
        var c = caveat(r); if (c) li.appendChild(c);
        ul.appendChild(li);
      });
      rel.appendChild(ul); article.appendChild(rel);
    }
    var meta = el('section', 'rs-meta');
    meta.appendChild(el('p', null, S.meta.written(page.model || S.chips.model)));
    var usage = page.usage || {}, timings = view.timings || {};
    var line = S.meta.timing(timings.model_ms, timings.total_ms, usage.total_tokens);
    if (line) meta.appendChild(el('p', null, line));
    if (page.confidence_reason) meta.appendChild(el('p', null, page.confidence_reason));
    if (page.limits) meta.appendChild(el('p', null, page.limits));
    meta.appendChild(el('p', null, S.meta.warning));
    article.appendChild(meta);
    article.appendChild(sourcesBlock(sources));
  }
  function sectionBlock(sec, sources, plain) {
    var box = el('section', 'rs-section');
    box.appendChild(el('h2', null, sec.heading));
    var p = el('p', null, sec.body);
    if (!plain) { p.appendChild(chips(sec.source_ids, sources)); var c = caveat(sec); if (c) p.appendChild(c); }
    else p.appendChild(chips(sec.source_ids, sources));
    box.appendChild(p); return box;
  }

  /* ------------------------------------------------------------ session control */
  function setProgress(stage, elapsedMs) {
    progress.hidden = false; article.hidden = true;
    progressText.textContent = S.stages[stage] || S.stages.queued;
    progressSub.textContent = S.progressSub(Math.floor((elapsedMs || 0) / 1000));
    var order = ['searching', 'writing', 'done'], at = order.indexOf(stage);
    steps.forEach(function (s, i) { s.dataset.state = i < at ? 'done' : i === at ? 'active' : ''; });
  }
  function showArticle() { progress.hidden = true; article.hidden = false; body.scrollTop = 0; goButton.disabled = false; }
  function stopPoll() { window.clearTimeout(pollTimer); pollTimer = null; }

  function begin(payload) {
    run += 1; var mine = run;
    stopPoll(); lastPayload = payload; fails = 0; startedAt = Date.now(); sessionId = null;
    hideKeyboard(); goButton.disabled = true;
    setProgress('queued', 0);
    api('POST', 'api/research', payload).then(function (view) {
      if (mine !== run) return;
      if (!view.ok) { failed(view.error && view.error.message); return; }
      sessionId = view.id; handle(view, mine);
    }).catch(function () { if (mine === run) failed(S.network); });
  }
  function handle(view, mine) {
    if (mine !== run) return;
    if (view.status === 'done') { renderPage(view); showArticle(); return; }
    if (view.status === 'failed') { failed(view.error && view.error.message); return; }
    if (view.status === 'cancelled') { showArticle(); article.replaceChildren(notice(S.cancelled, '', retryButton())); return; }
    setProgress(view.stage, view.elapsed_ms);
    if (Date.now() - startedAt > CLIENT_WALL_MS) { failed(S.failed.text); return; }
    pollTimer = window.setTimeout(function () { poll(mine); }, POLL_MS);
  }
  function poll(mine) {
    if (mine !== run || !sessionId) return;
    api('GET', 'api/research/' + encodeURIComponent(sessionId)).then(function (view) {
      if (mine !== run) return;
      fails = 0;
      if (!view.ok) { failed(view.error && view.error.message); return; }
      handle(view, mine);
    }).catch(function () {
      if (mine !== run) return;
      fails += 1;
      if (fails >= POLL_FAILS) failed(S.network); else pollTimer = window.setTimeout(function () { poll(mine); }, POLL_MS * 2);
    });
  }
  function failed(message) {
    stopPoll(); showArticle();
    article.replaceChildren(notice(S.failed.title, message || S.failed.text, retryButton()));
  }
  function cancel() {
    run += 1; stopPoll();
    if (sessionId) api('POST', 'api/research/' + encodeURIComponent(sessionId) + '/cancel', {}).catch(function () {});
    sessionId = null; showArticle(); renderIntro();
  }
  function search(query) {
    query = (query || '').trim().slice(0, 80);
    setInput(query);
    begin({query: query});
  }
  function startTopic(topic) {
    setInput(topic.label);
    begin({item_id: item.id, topic_id: topic.id});
  }

  /* ------------------------------------------------------------ intro + topics */
  function renderIntro() {
    article.replaceChildren();
    var box = el('section', 'rs-intro');
    box.appendChild(el('h2', null, S.intro.title));
    box.appendChild(el('p', null, S.intro.text));
    var ol = el('ol', 'rs-how');
    S.intro.steps.forEach(function (t) { ol.appendChild(el('li', null, t)); });
    box.appendChild(ol);
    box.appendChild(el('p', 'rs-fine', S.intro.warning));
    if (App.config && App.config.nebius_configured === false) box.appendChild(el('p', 'rs-warn', S.keyMissing));
    article.appendChild(box);
  }
  function renderTopics() {
    topicsBar.replaceChildren();
    if (!item || !item.topics.length) { topicsBar.hidden = true; return; }
    topicsBar.hidden = false;
    topicsBar.appendChild(el('span', 'rs-topics-label', S.researchFrom(item.title)));
    item.topics.forEach(function (t) {
      var b = el('button', 'rs-chip', t.label); b.type = 'button';
      b.addEventListener('click', function () { startTopic(t); });
      topicsBar.appendChild(b);
    });
  }

  /* ------------------------------------------------------------ open / close */
  function open(detail) {
    item = detail.item;
    if (!item || isOpen) return;
    isOpen = true; focusBefore = document.activeElement;
    if (!focusBefore || focusBefore.offsetParent === null) focusBefore = openButton;
    App.hold(1);
    root.hidden = false; showArticle();
    renderTopics(); setInput('');
    input.focus();
    if (detail.topic) startTopic(detail.topic); else renderIntro();
  }
  function close() {
    if (!isOpen) return;
    isOpen = false; run += 1; stopPoll();
    if (sessionId) api('POST', 'api/research/' + encodeURIComponent(sessionId) + '/cancel', {}).catch(function () {});
    sessionId = null; hideKeyboard(); root.hidden = true; goButton.disabled = false; toast.hidden = true;
    App.hold(-1);
    if (focusBefore && focusBefore.focus) focusBefore.focus(); else openButton.focus();
  }

  /* ------------------------------------------------------------ on-screen keyboard */
  /* Touch keyboard (QWERTY + symbols), ported from the kiosk Research Guide.
     The kiosk has no system keyboard; keys type on pointerdown so the field keeps
     focus. Shown when the search field is touched (kiosk, ?keyboard=1 or a coarse
     pointer); a hardware keyboard keeps writing the field directly. */
  var LAYOUTS = {
    en: [['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'], ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'], ['z', 'x', 'c', 'v', 'b', 'n', 'm']],
    num: [['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'], ['-', ':', '.', ',', '!', '?', '\'', '&', '+'], ['(', ')', '/', '~', '\u00b7', '#', '*']]
  };
  var params = new URLSearchParams(window.location.search);
  var touchKeyboard = App.kiosk || params.get('keyboard') === '1' ||
    (params.get('keyboard') !== '0' && !!window.matchMedia && window.matchMedia('(pointer: coarse)').matches && window.innerWidth >= 900);
  var layout = 'en', shift = false;
  var replaceOnType = false;   // a finished query is replaced by the first new keystroke, like selected text
  if (touchKeyboard) input.setAttribute('inputmode', 'none');   // never stack a system keyboard under ours
  function setInput(text) { input.value = String(text || ''); replaceOnType = !!input.value; root.dataset.replace = 'no'; }
  function press(key) {
    var typing = ['shift', 'num', 'enter', 'hide', 'back'].indexOf(key) < 0;
    if (replaceOnType && typing) input.value = '';
    if (typing || key === 'back') { replaceOnType = false; root.dataset.replace = 'no'; }
    if (key === 'back') input.value = Array.from(input.value).slice(0, -1).join('');
    else if (key === 'space') { if (input.value && !/\s$/.test(input.value)) input.value += ' '; }
    else if (key === 'shift') { shift = !shift; return drawKeyboard(); }
    else if (key === 'num') { layout = layout === 'num' ? 'en' : 'num'; shift = false; return drawKeyboard(); }
    else if (key === 'enter') { if (!goButton.disabled) search(input.value); return; }
    else if (key === 'hide') return hideKeyboard();
    else if (input.value.length < 80) {
      input.value += shift && layout === 'en' ? key.toUpperCase() : key;
      if (shift) { shift = false; drawKeyboard(); }
    }
    var end = input.value.length;
    try { input.setSelectionRange(end, end); } catch (e) { /* not focusable yet */ }
    input.scrollLeft = input.scrollWidth;
  }
  function keyButton(label, key, cls, aria) {
    var b = el('button', 'rs-key' + (cls ? ' ' + cls : ''), label);
    b.type = 'button'; b.dataset.key = key; b.tabIndex = -1;
    if (aria) b.setAttribute('aria-label', aria);
    return b;
  }
  function drawKeyboard() {
    var rows = LAYOUTS[layout];
    keyboard.replaceChildren();
    rows.forEach(function (keys, index) {
      var row = el('div', 'rs-key-row');
      if (index === 2) row.appendChild(keyButton(layout === 'num' ? '' : '\u21e7', 'shift', 'is-wide' + (shift ? ' is-on' : '') + (layout === 'num' ? ' is-off' : ''), S.keys.shift));
      keys.forEach(function (k) { row.appendChild(keyButton(shift && layout === 'en' ? k.toUpperCase() : k, k)); });
      if (index === 2) row.appendChild(keyButton('\u232b', 'back', 'is-wide', S.keys.back));
      keyboard.appendChild(row);
    });
    var last = el('div', 'rs-key-row');
    last.appendChild(keyButton(layout === 'num' ? S.keys.letters : S.keys.numbers, 'num', 'is-wide'));
    last.appendChild(keyButton(S.keys.space, 'space', 'is-space'));
    last.appendChild(keyButton(S.keys.hide, 'hide', 'is-wide'));
    last.appendChild(keyButton(S.keys.go, 'enter', 'is-wide is-go'));
    keyboard.appendChild(last);
  }
  function showKeyboard() {
    if (!touchKeyboard || goButton.disabled) return;
    if (keyboard.hidden) { layout = 'en'; shift = false; drawKeyboard(); keyboard.hidden = false; root.dataset.keyboard = 'yes'; root.dataset.replace = replaceOnType ? 'yes' : 'no'; }
  }
  function hideKeyboard() { keyboard.hidden = true; root.dataset.keyboard = 'no'; root.dataset.replace = 'no'; }
  keyboard.addEventListener('pointerdown', function (e) {
    var target = e.target && e.target.closest ? e.target.closest('.rs-key') : null;
    if (!target) return;
    e.preventDefault();
    press(target.dataset.key);
  });
  input.addEventListener('pointerdown', showKeyboard);
  /* A hardware keyboard (desktop testing) writes the field directly. */
  input.addEventListener('input', function () { replaceOnType = false; root.dataset.replace = 'no'; });

  form.addEventListener('submit', function (e) { e.preventDefault(); if (!goButton.disabled) search(input.value); });
  root.querySelector('.rs-close').addEventListener('click', close);
  root.querySelector('.rs-cancel').addEventListener('click', cancel);
  document.addEventListener('otaku:research-open', function (e) { open(e.detail); });
  document.addEventListener('keydown', function (e) {
    if (root.hidden) return;
    if (e.key === 'Escape') { e.preventDefault(); if (!keyboard.hidden) hideKeyboard(); else close(); return; }
    if (e.key === 'Tab') { /* keep focus inside the dialog */
      var f = Array.prototype.filter.call(root.querySelectorAll('button, input, a[href], [tabindex="0"]'), function (n) { return !n.disabled && n.tabIndex >= 0 && n.offsetParent !== null; });
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
})();
