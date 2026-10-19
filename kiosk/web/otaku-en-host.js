/* OTAKU Gallery (English) host for the kiosk's otaku profile.
   The gallery app runs as its own server; the kiosk proxies it at /otaku-en/
   and lays it over the renderer stage only while nothing else needs the
   screen. Voice states, Ask the Three and the week calendar hide it, and an
   open Research Guide holds the shared overlay lease so the gallery does not
   advance underneath it. /api/exhibition selects it ("en") or shows the bare
   renderer ("renderer"). This is the same file that runs on the Pi, renamed
   from its private locale-bridge name. */
(function () {
  'use strict';
  var frame = document.createElement('iframe');
  frame.id = 'otaku-en-frame'; frame.title = 'English OTAKU Gallery';
  frame.src = 'about:blank'; frame.hidden = true;
  frame.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;border:0;z-index:2;background:#101015';
  document.body.appendChild(frame);
  var selected = 'renderer', loaded = false, held = false;
  var name = 'otaku-en-research';
  function release() {
    if (held) { held = false; window.jarvisOverlays.release(name); }
  }
  function closeResearch() {
    try {
      var d = frame.contentDocument;
      var close = d.querySelector('.rs-close');
      if (close) close.click();
      var info = d.getElementById('info-close');
      if (info) info.click();
    } catch (_) { /* unloaded iframe */ }
    release();
  }
  function sync() {
    var o = window.jarvisOverlays, g = window.jarvisGallery;
    if (!o || !g) return;
    var visible = selected === 'en' && g.profile === 'otaku';
    var other = o.holders.some(function (x) { return x !== name; });
    if (!visible || o.busy || o.sessionActive || other) closeResearch();
    visible = visible && !o.busy && !o.sessionActive && !other;
    frame.hidden = !visible;
    if (visible && !loaded) { loaded = true; frame.src = '/otaku-en/?kiosk=1'; }
    if (selected !== 'en' && loaded) { loaded = false; frame.src = 'about:blank'; }
    try {
      var d = frame.contentDocument;
      var research = d.getElementById('research'), info = d.getElementById('info');
      var reading = visible && ((research && !research.hidden) || (info && !info.hidden));
      if (reading && !held) { held = o.acquire(name); }
      else if (!reading) release();
    } catch (_) { release(); }
  }
  window.jarvisExhibition = {
    get mode() { return selected; },
    get ready() { return document.documentElement.dataset.exhibitionReady === 'true'; },
    get galleryVisible() { return !frame.hidden; },
    closeResearch: closeResearch
  };
  var o = window.jarvisOverlays;
  if (o) {
    o.onPreempt(closeResearch);
    o.onYield(name, function (reason) { if (reason !== name) closeResearch(); });
  }
  function refresh() {
    fetch('/api/exhibition', {cache:'no-store'}).then(function (r) {
      if (!r.ok) throw Error('locale unavailable');
      return r.json();
    }).then(function (s) {
      selected = s.mode === 'en' ? 'en' : 'renderer';
      document.documentElement.dataset.exhibitionReady = 'true';
      document.documentElement.dataset.exhibition = selected; sync();
    }).catch(function () { selected = 'renderer'; sync(); });
  }
  refresh(); setInterval(refresh, 1500); setInterval(sync, 100);
})();
