(function () {
  'use strict';
  var overlay = document.getElementById('ask-overlay');
  var frame = document.getElementById('ask-frame');
  var heartbeat = null;
  function action(name) {
    return fetch('/api/ask/overlay', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: name })
    }).then(function (r) { return r.json(); });
  }
  function freeScreen() {
    var o = window.jarvisOverlays;
    return o && !o.busy && !o.sessionActive && !o.holding;
  }
  function close() {
    if (overlay.dataset.state !== 'open') return;
    frame.src = 'about:blank';
    overlay.dataset.state = 'closed';
    overlay.classList.add('is-inert');
    overlay.setAttribute('aria-hidden', 'true');
    if (heartbeat) { clearInterval(heartbeat); heartbeat = null; }
    if (window.jarvisOverlays) window.jarvisOverlays.release('ask-the-three');
    action('close').catch(function () { /* bridge watchdog still recovers wake */ });
  }
  function openFromVoice() {
    if (!freeScreen()) { action('reject').catch(function () {}); return; }
    action('opened').then(function (result) {
      if (result.status !== 'open') return;
      if (!freeScreen()) { action('reject').catch(function () {}); return; }
      if (!window.jarvisOverlays.acquire('ask-the-three')) {
        action('reject').catch(function () {}); return;
      }
      overlay.classList.remove('is-inert');
      overlay.dataset.state = 'open';
      overlay.setAttribute('aria-hidden', 'false');
      fetch('/api/exhibition', {cache:'no-store'}).then(function (r) { return r.json(); })
        .then(function (s) {
          if (overlay.dataset.state === 'open') {
            frame.title = s.mode === 'en' ? 'Ask the Three' : 'Ask the Three';
            frame.src = s.mode === 'en' ? '/ask-en/' : '/ask/';
          }
        }).catch(close);
      heartbeat = setInterval(function () {
        fetch('/api/ask/session', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: '{"action":"heartbeat"}'
        }).then(function (r) { if (!r.ok) close(); })
          .catch(function () { close(); });
      }, 60000);
    }).catch(function () { action('reject').catch(function () {}); });
  }
  if (window.jarvisOverlays) window.jarvisOverlays.onPreempt(close);
  window.jarvisAskOverlay = { handle: function (msg) {
    if (msg && msg.action === 'open') openFromVoice();
  }};
  window.addEventListener('message', function (e) {
    if (e.origin === location.origin && e.source === frame.contentWindow &&
        e.data && e.data.type === 'ask-three-close') close();
  });
})();
