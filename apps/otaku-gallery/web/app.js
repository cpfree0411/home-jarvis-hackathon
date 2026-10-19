/*
 * OTAKU Gallery (English) - ambient gallery shell.
 * Plain browser JavaScript, no build step, no third-party requests. Remote or
 * model text is only ever placed with textContent.
 *
 * URL options: ?autoplay=0 (start paused) · ?interval=<seconds> (6-120)
 *              ?bg=host (framed card over a transparent page, for embedding)
 *              ?kiosk=1 (show source addresses instead of opening links)
 */
(function () {
  'use strict';
  var S = window.OTAKU_STRINGS;
  var params = new URLSearchParams(window.location.search);
  var app = document.getElementById('app');
  var $ = function (id) { return document.getElementById(id); };
  var layers = [$('layer-a'), $('layer-b')];
  var FAV_KEY = 'otaku-gallery-en:favorites';
  var IDLE_MS = 6000;

  var intervalS = Math.min(120, Math.max(6, parseInt(params.get('interval') || '14', 10) || 14));
  var state = {items: [], view: [], index: 0, tag: null, favOnly: false, favs: loadFavs(), userPaused: params.get('autoplay') === '0',
               holds: 0, front: 0, timer: null, idleTimer: null, kb: 0, config: {}};

  if (params.get('bg') === 'host') document.body.classList.add('host-bg');
  app.style.setProperty('--interval', intervalS + 's');

  /* ------------------------------------------------------------ helpers */
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function loadFavs() {
    try {
      var raw = JSON.parse(window.localStorage.getItem(FAV_KEY) || '[]');
      return Array.isArray(raw) ? raw.filter(function (v) { return typeof v === 'string'; }).slice(0, 200) : [];
    } catch (e) { return []; }
  }
  function saveFavs() {
    try { window.localStorage.setItem(FAV_KEY, JSON.stringify(state.favs)); } catch (e) { /* private mode: keep in memory */ }
  }
  function safeHttps(url) { return typeof url === 'string' && /^https:\/\/[^\s<>"']+$/.test(url) ? url : ''; }
  function current() { return state.view[state.index] || null; }
  function toast(text, ms) {
    var t = $('toast'); t.textContent = text; t.hidden = false;
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(function () { t.hidden = true; }, ms || 3600);
  }

  /* ------------------------------------------------------------ playlist */
  function rebuildView(keepId) {
    state.view = state.items.filter(function (it) {
      if (state.tag && it.tags.indexOf(state.tag) < 0) return false;
      if (state.favOnly && state.favs.indexOf(it.id) < 0) return false;
      return true;
    });
    var at = keepId ? state.view.findIndex(function (it) { return it.id === keepId; }) : -1;
    state.index = at >= 0 ? at : 0;
  }
  function show(index, instant) {
    if (!state.view.length) { renderEmpty(); return; }
    state.index = (index + state.view.length) % state.view.length;
    var item = current();
    var back = layers[1 - state.front], front = layers[state.front];
    state.kb = (state.kb + 1) % 3;
    back.className = 'layer kb-' + state.kb;
    back.onload = function () {
      back.onload = null;
      back.classList.add('is-active');
      front.classList.remove('is-active');
      state.front = 1 - state.front;
    };
    back.alt = '';
    back.src = item.url;
    if (back.complete && back.naturalWidth) back.onload && back.onload();
    app.dataset.state = 'ready';
    app.style.setProperty('--accent', item.accent);
    $('stage').setAttribute('aria-label', item.alt);
    renderCaption(item);
    renderInfo(item);
    $('counter').textContent = S.counter(state.index + 1, state.view.length, !!(state.tag || state.favOnly));
    syncFav();
    restartTimer();
    document.dispatchEvent(new CustomEvent('otaku:artwork', {detail: item}));
  }
  function step(delta) { show(state.index + delta); }

  /* ------------------------------------------------------------ rendering */
  function sourceLine(item) {
    return item.source_label + ' · ' + S.creatorLine(item.creator) + ' · ' + item.license_label;
  }
  function renderCaption(item) {
    $('cap-source').textContent = sourceLine(item);
    $('cap-title').textContent = item.title;
    $('cap-desc').textContent = item.description;
    var capTags = $('cap-tags'); capTags.replaceChildren();
    item.tags.forEach(function (t) {
      var li = el('li'), b = el('button', null, '#' + t);
      b.type = 'button'; b.setAttribute('aria-pressed', String(state.tag === t));
      b.addEventListener('click', function () { setFilter(t, false); });
      li.appendChild(b); capTags.appendChild(li);
    });
    var open = $('research-open');
    open.setAttribute('aria-label', 'Open the Research Guide for ' + item.title + ', powered by NVIDIA Nemotron 3 Ultra');
  }
  function renderEmpty() {
    $('cap-source').textContent = '';
    $('cap-title').textContent = state.favOnly ? S.noFavorites : S.noMatches;
    $('cap-desc').textContent = ''; $('cap-tags').replaceChildren();
    $('counter').textContent = S.counter(0, 0, true);
    window.clearTimeout(state.timer);
  }
  function renderInfo(item) {
    $('info-desc').textContent = item.description;
    $('info-creator').textContent = item.creator + ' (' + item.creator_kind.replace(/-/g, ' ') + ')';
    var lic = $('info-license'); lic.replaceChildren();
    if (safeHttps(item.license_url)) {
      var a = el('a', null, item.license_label); a.href = item.license_url; a.target = '_blank'; a.rel = 'noopener noreferrer';
      lic.appendChild(a);
    } else lic.textContent = item.license_label;
    var src = $('info-source'); src.replaceChildren();
    if (safeHttps(item.source_url)) {
      var s = el('a', null, item.source_label); s.href = item.source_url; s.target = '_blank'; s.rel = 'noopener noreferrer';
      src.appendChild(s);
    } else src.textContent = item.source_label;
    if (item.source_note) src.appendChild(el('span', 'fine note', item.source_note));
    var tags = [{label: S.tagAll, value: null}];
    var seen = {};
    state.items.forEach(function (it) { it.tags.forEach(function (t) { if (!seen[t]) { seen[t] = 1; tags.push({label: t, value: t}); } }); });
    var list = $('filter-tags'); list.replaceChildren();
    tags.forEach(function (t) {
      var li = el('li'), b = el('button', null, t.value === null ? t.label : '#' + t.label);
      b.type = 'button'; b.setAttribute('aria-pressed', String(!state.favOnly && state.tag === t.value));
      b.addEventListener('click', function () { setFilter(t.value, false); });
      li.appendChild(b); list.appendChild(li);
    });
    var li = el('li'), fb = el('button', null, S.tagFavorites);
    fb.type = 'button'; fb.setAttribute('aria-pressed', String(state.favOnly));
    fb.addEventListener('click', function () { setFilter(null, !state.favOnly); });
    li.appendChild(fb); list.appendChild(li);
    $('filter-note').textContent = S.filterNote(state.view.length);
    var topics = $('info-topics'); topics.replaceChildren();
    if (!item.topics.length) topics.appendChild(el('li', 'fine', S.topicsNone));
    item.topics.forEach(function (t) {
      var li2 = el('li'), b2 = el('button'); b2.type = 'button';
      b2.appendChild(el('span', 'nv-eye')); b2.appendChild(el('span', null, t.label));
      if (t.relation) b2.appendChild(el('em', null, t.relation));
      b2.addEventListener('click', function () { openResearch(t); });
      li2.appendChild(b2); topics.appendChild(li2);
    });
  }
  function setFilter(tag, favOnly) {
    var keep = current() ? current().id : null;
    state.tag = tag; state.favOnly = !!favOnly;
    rebuildView(keep);
    if (!state.view.length) { renderEmpty(); renderInfo(state.items[0]); return; }
    show(state.index);
  }

  /* ------------------------------------------------------------ favorites */
  function syncFav() {
    var item = current(), on = !!item && state.favs.indexOf(item.id) >= 0;
    var b = $('fav');
    b.setAttribute('aria-pressed', String(on));
    b.firstElementChild.textContent = on ? '♥' : '♡';
    b.lastElementChild.textContent = on ? S.unfavorite : S.favorite;
    b.dataset.tip = on ? S.unfavorite : S.favorite;
  }
  function toggleFav() {
    var item = current(); if (!item) return;
    var at = state.favs.indexOf(item.id);
    if (at >= 0) state.favs.splice(at, 1); else state.favs.push(item.id);
    saveFavs(); syncFav();
    if (state.favOnly && at >= 0) setFilter(null, true);
  }

  /* ------------------------------------------------------------ slideshow timing */
  function playing() { return !state.userPaused && state.holds === 0 && state.view.length > 1; }
  function restartTimer() {
    window.clearTimeout(state.timer);
    var bar = $('progress');
    bar.classList.remove('run'); void bar.offsetWidth;
    app.classList.toggle('is-paused', !playing());
    if (!playing()) return;
    bar.classList.add('run');
    state.timer = window.setTimeout(function () { step(1); }, intervalS * 1000);
  }
  function setPaused(paused) {
    state.userPaused = paused;
    var b = $('play');
    b.firstElementChild.textContent = paused ? '▶' : '❚❚';
    b.lastElementChild.textContent = paused ? S.resume : S.pause;
    b.dataset.tip = paused ? S.resume : S.pause;
    b.setAttribute('aria-pressed', String(paused));
    restartTimer();
  }
  function hold(delta) { state.holds = Math.max(0, state.holds + delta); restartTimer(); }

  /* ------------------------------------------------------------ chrome idle */
  function wake() {
    app.classList.remove('is-idle');
    window.clearTimeout(state.idleTimer);
    state.idleTimer = window.setTimeout(function () {
      if (state.holds === 0) app.classList.add('is-idle');
    }, IDLE_MS);
  }

  /* ------------------------------------------------------------ info sheet */
  function setInfo(open) {
    var panel = $('info');
    if (open !== panel.hidden) return;
    panel.hidden = !open;
    $('info-open').setAttribute('aria-expanded', String(open));
    hold(open ? 1 : -1);
    if (open) $('info-close').focus(); else $('info-open').focus();
  }
  function infoOpen() { return !$('info').hidden; }

  /* ------------------------------------------------------------ research bridge */
  function openResearch(topic) {
    if (infoOpen()) { $('info').hidden = true; $('info-open').setAttribute('aria-expanded', 'false'); hold(-1); }
    document.dispatchEvent(new CustomEvent('otaku:research-open', {detail: {item: current(), topic: topic || null}}));
  }
  window.OtakuApp = {
    current: current, hold: hold, toast: toast, el: el, kiosk: params.get('kiosk') === '1',
    get config() { return state.config; }, S: S
  };

  /* ------------------------------------------------------------ wiring */
  function wire() {
    $('prev').addEventListener('click', function () { step(-1); });
    $('next').addEventListener('click', function () { step(1); });
    $('fav').addEventListener('click', toggleFav);
    $('play').addEventListener('click', function () { setPaused(!state.userPaused); });
    $('info-open').addEventListener('click', function () { setInfo(!infoOpen()); });
    $('info-close').addEventListener('click', function () { setInfo(false); });
    $('research-open').addEventListener('click', function () { openResearch(null); });
    ['pointermove', 'pointerdown', 'keydown', 'touchstart'].forEach(function (name) { document.addEventListener(name, wake, {passive: true}); });
    var sx = null, sy = null;
    $('app').addEventListener('touchstart', function (e) { if (e.touches.length === 1) { sx = e.touches[0].clientX; sy = e.touches[0].clientY; } }, {passive: true});
    $('app').addEventListener('touchend', function (e) {
      if (sx === null || state.holds > 0) { sx = null; return; }
      var dx = e.changedTouches[0].clientX - sx, dy = e.changedTouches[0].clientY - sy;
      sx = null;
      if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.6) step(dx < 0 ? 1 : -1);
    }, {passive: true});
    document.addEventListener('keydown', function (e) {
      var tag = (e.target && e.target.tagName) || '';
      if (e.ctrlKey || e.metaKey || e.altKey || tag === 'INPUT' || tag === 'TEXTAREA') return;
      if (!$('research').hidden) return; // the Research Guide owns the keyboard while open
      if (e.key === 'ArrowRight') step(1);
      else if (e.key === 'ArrowLeft') step(-1);
      else if (e.key === ' ' && tag !== 'BUTTON') { e.preventDefault(); setPaused(!state.userPaused); }
      else if (e.key === 'i' || e.key === 'I') setInfo(!infoOpen());
      else if (e.key === 'f' || e.key === 'F') toggleFav();
      else if (e.key === 'r' || e.key === 'R') openResearch(null);
      else if (e.key === 'Escape' && infoOpen()) setInfo(false);
    });
  }

  function boot() {
    wire(); setPaused(state.userPaused); wake();
    $('counter').textContent = S.loading;
    Promise.all([
      fetch('api/gallery', {headers: {Accept: 'application/json'}}).then(function (r) { if (!r.ok) throw new Error('gallery'); return r.json(); }),
      fetch('api/config', {headers: {Accept: 'application/json'}}).then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; })
    ]).then(function (res) {
      state.items = res[0].items || []; state.config = res[1] || {};
      if (!state.items.length) throw new Error('empty');
      var want = params.get('art');
      rebuildView(want);
      show(state.index);
      document.dispatchEvent(new CustomEvent('otaku:ready'));
    }).catch(function () {
      app.dataset.state = 'error';
      $('cap-title').textContent = S.loadError;
    });
  }
  boot();
})();
