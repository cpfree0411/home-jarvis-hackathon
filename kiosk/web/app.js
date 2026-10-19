/*
 * Home Jarvis — Gallery / Room Light renderer.
 *
 * Boundaries this file keeps:
 *   - jarvis-live only ever sends semantic states (idle/listening/thinking/
 *     speaking) and one-shot events. It knows nothing about the gallery,
 *     the media list, video playback position, or captions.
 *   - Gallery playback (including pause/resume across a session) is owned
 *     here, in the browser.
 *   - Captions are a non-critical side channel. Losing them changes nothing
 *     about the Room Light lifecycle.
 */
(function () {
  'use strict';

  var ACTIVE_STATES = { listening: 1, thinking: 1, searching: 1, speaking: 1 };
  var WAKE_MS = 950;              // wave settle window before the semantic state
  var LISTENING_ADMISSION_MS = 350; // visual-answer-only pill admission debounce
  var THINKING_STYLES = ['focus', 'desat', 'both'];
  var IMAGE_DWELL_MS = 42000;     // gallery advance interval for stills

  var body = document.body;
  var CAPTION_PREVIEW_TEXT =
    'It is clear and 28 degrees today. Gemini is looking at the scene on screen and can describe the picture in more detail if you ask.';
  var CAPTION_STYLE_MODES = {
    baseline: true,
    'neo-plain': true,
    neo: true,
  };
  var slots = [
    document.querySelector('.media-slot[data-slot="a"]'),
    document.querySelector('.media-slot[data-slot="b"]')
  ];
  var waveCanary = false;
  var sineWaveCanaryMode = null;
  var waveSurface = null;
  var sineWaveSurface = null;
  var statePill = null;
  var statePillHost = document.getElementById('state-pill-host');
  var captionLine = document.querySelector('.caption-line');
  var visualAnswerSurface = document.getElementById('visual-answer-surface');
  var weatherFrame = document.getElementById('weather-frame');
  var fxFrame = document.getElementById('fx-frame');
  var portfolioFrame = document.getElementById('portfolio-frame');
  var isVisualAnswerActive = false;
  var isVisualAnswerExiting = false;
  var visualAnswerExitGeneration = 0;
  var visualAnswerExitTimer = null;
  var visualAnswerExitStartTime = 0;
  var visualAnswerExitReason = null;
  var VISUAL_ANSWER_EXIT_FAILSAFE_MS = 600;
  var currentVisualAnswerKind = null;
  var pendingWeatherPayload = null;
  var pendingFXPayload = null;
  var pendingPortfolioPayload = null;
  var captionStyleMode = 'baseline';
  var captionPreviewEnabled = false;
  var captionFontReady = true;
  var pendingCaptionChunks = [];
  var captionFontStatus = {
    mode: 'baseline',
    family: 'NanumBarunGothic',
    state: 'baseline',
    loaded: null,
    checked: null,
  };

  /* Weather v3 is the default. `?weather-style=v2` restores the previous
     panel (its source files are untouched) and `?weather-style=v1` the one
     before it. The switch is the kiosk URL, so rollback needs no code change:
     see docs/weather-opus-v3.md. */
  function weatherStyleRequested() {
    var value = new URLSearchParams(window.location.search).get('weather-style');
    if (value === 'v1') return 'v1';
    if (value === 'v2') return 'v2';
    return 'v3';
  }

  var weatherStyleMode = weatherStyleRequested();
  if (weatherFrame && weatherStyleMode === 'v1') {
    weatherFrame.src = 'weather-template.html?live=1';
  } else if (weatherFrame && weatherStyleMode === 'v2') {
    weatherFrame.src = 'weather-template-v2.html?live=1';
  }

  /* Only v3 receives the daily forecast and day/night phase. v1 and v2 get
     exactly the options they always did, so a rollback is the old behaviour. */
  function weatherOptionsFor(data) {
    var options = data.options || {};
    if (weatherStyleMode !== 'v3') return options;
    var extended = {};
    Object.keys(options).forEach(function (key) { extended[key] = options[key]; });
    if (data.daily) extended.daily = data.daily;
    if (data.sun && typeof data.sun.is_daytime === 'boolean') extended.isDaytime = data.sun.is_daytime;
    return extended;
  }

  function captionStyleRequested() {
    var value = new URLSearchParams(window.location.search).get('caption-style');
    if (value === 'baseline' || value === 'neo-plain' || value === 'neo') return value;
    return 'neo';
  }

  function captionPreviewRequested() {
    return new URLSearchParams(window.location.search).get('caption-preview') === 'sample';
  }

  captionStyleMode = captionStyleRequested();
  captionPreviewEnabled = captionPreviewRequested();
  body.dataset.captionStyle = captionStyleMode;
  if (captionStyleMode !== 'baseline') {
    captionFontReady = false;
    captionFontStatus = {
      mode: captionStyleMode,
      family: 'NanumSquare Neo',
      state: 'loading',
      loaded: false,
      checked: false,
    };
  }
  var captionReveal = null;
  if (window.JarvisCaptionReveal && captionLine) {
    try {
      captionReveal = window.JarvisCaptionReveal.create(captionLine);
    } catch (error) {
      console.warn('[Caption] continuous reveal unavailable; continuing without text', error);
    }
  }

  function flushPendingCaptionChunks() {
    if (!captionFontReady || !captionReveal || !pendingCaptionChunks.length) return;
    var chunks = pendingCaptionChunks;
    pendingCaptionChunks = [];
    chunks.forEach(function (chunk) { captionReveal.push(chunk); });
  }

  function finishCaptionFontLoad(state, loaded, checked) {
    captionFontReady = true;
    captionFontStatus.state = state;
    captionFontStatus.loaded = Boolean(loaded);
    captionFontStatus.checked = Boolean(checked);
    flushPendingCaptionChunks();
  }

  function beginCaptionFontLoad() {
    if (captionStyleMode === 'baseline') return;
    if (!document.fonts || typeof document.fonts.load !== 'function') {
      finishCaptionFontLoad('font-api-unavailable', false, false);
      return;
    }

    var loadPromise;
    try {
      loadPromise = document.fonts.load('600 34px "NanumSquare Neo"');
    } catch (error) {
      finishCaptionFontLoad('font-load-error', false, false);
      return;
    }

    Promise.resolve(loadPromise).then(function (faces) {
      var loaded = Array.isArray(faces) && faces.some(function (face) {
        return face && face.family && face.family.indexOf('NanumSquare Neo') !== -1 &&
          face.status === 'loaded';
      });
      var checked = false;
      try {
        checked = document.fonts.check('600 34px "NanumSquare Neo"') ||
                  document.fonts.check('500 34px "NanumSquare Neo"') ||
                  document.fonts.check('400 32px "NanumSquare Neo"');
      } catch (error) {
        checked = false;
      }
      finishCaptionFontLoad(loaded && checked ? 'loaded' : 'fallback', loaded, checked);
    }).catch(function () {
      finishCaptionFontLoad('font-load-error', false, false);
    });
  }

  var playlist = [];
  var registry = { states: {}, events: {} };
  var slideIndex = -1;
  var activeSlot = 0;
  var advanceTimer = null;

  var visualState = 'idle';       // what the screen is currently expressing
  var steadyState = 'idle';       // last semantic state from the controller
  var pendingState = null;        // state that arrived during the wake moment
  var wakeTimer = null;
  var eventTimer = null;
  var listeningAdmissionTimer = null;
  var listeningAdmissionGeneration = 0;

  /* BRIEFING: the copy layer over a briefing frame. Inert on every other
     profile — these lookups simply find the hidden surface and nothing calls
     renderBriefing(). */
  var briefingSurface = document.getElementById('briefing-surface');
  var briefingCopy = document.getElementById('briefing-copy');
  var briefingEls = {
    category: document.getElementById('briefing-category'),
    topic: document.getElementById('briefing-topic'),
    time: document.getElementById('briefing-time'),
    headline: document.getElementById('briefing-headline'),
    deck: document.getElementById('briefing-deck'),
    source: document.getElementById('briefing-source'),
    relevance: document.getElementById('briefing-relevance')
  };
  /* A headline is a fixed amount of room, not a fixed size: the largest step
     that still fits three lines wins, and below the floor the answer is a
     shorter headline rather than a smaller one. */
  var BRIEFING_LADDER = [64, 56, 51, 46, 42];
  var briefingDwellMs = null;
  var profileDwellMs = IMAGE_DWELL_MS;

  /* ART: a quiet museum label beside the un-cropped image. Like Briefing,
     this is a copy layer only; the artwork stays in the shared media slots. */
  var artCopy = document.getElementById('art-copy');
  var artEls = {
    kicker: document.getElementById('art-kicker'),
    title: document.getElementById('art-title'),
    creator: document.getElementById('art-creator'),
    meta: document.getElementById('art-meta'),
    note: document.getElementById('art-note'),
    source: document.getElementById('art-source'),
    license: document.getElementById('art-license')
  };

  /* Multiple profiles, not one. `requestedProfile` is what this display has been
     asked to show and is the only thing the media queries ever name;
     `currentProfile` is what is actually on the screen, which can legitimately
     differ (an empty briefing is served as the family gallery) — and when it
     does, the request stands and keeps being polled. `pendingProfileSwitch`
     marks a playlist that arrived from an explicit voice request, so it is
     applied at the first safe idle rather than waiting out a full dwell. */
  var requestedProfile = null;
  var currentProfile = 'family';
  var currentGeneration = null;
  var pendingPlaylist = null;
  var pendingGeneration = null;
  var pendingActiveProfile = null;
  var pendingDwellMs = null;
  var pendingProfileSwitch = false;
  var reportedProfile = null;
  var mediaCheckTimer = null;
  var MEDIA_CHECK_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes

  var briefingContextSeq = 0;
  var lastReportedBriefingStoryId = null;

  function reportBriefingContext(storyId, gen) {
    var sid = storyId || null;
    briefingContextSeq++;
    var seq = briefingContextSeq;
    lastReportedBriefingStoryId = sid;
    fetch('/api/briefing/context', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        story_id: sid,
        generation: gen !== undefined ? gen : currentGeneration,
        seq: seq
      })
    }).catch(function () { /* fail-open: context is ephemeral observability */ });
  }

  /* Nature carries the same referential split as Briefing: this renderer is
     the only thing that knows which photograph is physically admitted, and
     the Home Server manifest is the only thing that knows what it is. Only
     the identity is reported. */
  var natureContextSeq = 0;
  var lastReportedNatureItemId = null;

  function reportNatureContext(itemId, gen) {
    var iid = itemId || null;
    natureContextSeq++;
    var seq = natureContextSeq;
    lastReportedNatureItemId = iid;
    fetch('/api/nature/context', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_id: iid,
        generation: gen !== undefined ? gen : currentGeneration,
        seq: seq
      })
    }).catch(function () { /* fail-open: context is ephemeral observability */ });
  }

  /* OTAKU carries the same referential split as Nature and Briefing: this renderer
     is the only thing that knows which illustration is physically admitted, and
     the Home Server manifest is the only thing that knows what it is. Only
     the identity is reported. */
  // Persist identity ordering across Chromium-only watchdog reloads. The
  // server keeps its last sequence until restart; resetting to zero would
  // leave voice looking at the previously displayed slide.
  var otakuContextSeq = Date.now();
  try {
    var savedOtakuSeq = Number(window.localStorage.getItem('jarvisOtakuContextSeq'));
    if (Number.isSafeInteger(savedOtakuSeq)) otakuContextSeq = Math.max(otakuContextSeq, savedOtakuSeq);
  } catch (e) { /* wall-clock seed still orders ordinary reloads */ }
  var lastReportedOtakuItemId = null;

  function reportOtakuContext(itemId, gen) {
    var iid = itemId || null;
    otakuContextSeq = Math.max(otakuContextSeq + 1, Date.now());
    try { window.localStorage.setItem('jarvisOtakuContextSeq', String(otakuContextSeq)); } catch (e) {}
    var seq = otakuContextSeq;
    lastReportedOtakuItemId = iid;
    if (window.jarvisOtakuGuide) window.jarvisOtakuGuide.sync();
    if (window.jarvisOtakuResearch) window.jarvisOtakuResearch.sync();
    fetch('/api/otaku/context', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_id: iid,
        generation: gen !== undefined ? gen : currentGeneration,
        seq: seq
      })
    }).catch(function () { /* fail-open: context is ephemeral observability */ });
  }

  window.jarvisGallery = {
    get state() { return visualState; },
    get steadyState() { return steadyState; },
    get profile() { return currentProfile; },
    get requestedProfile() { return requestedProfile; },
    get activeProfile() { return currentProfile; },
    get pendingProfileSwitch() { return pendingProfileSwitch; },
    requestProfile: function (id) { return applyProfileRequest(id); },
    get generation() { return currentGeneration; },
    get pendingGeneration() { return pendingGeneration; },
    get hasPendingPlaylist() { return Boolean(pendingPlaylist && pendingPlaylist.length); },
    get playlist() { return playlist; },
    /* Compatibility hook: exercise the canonical Live-entry sine-ripple wave
       (or the explicit SVG rollback canary when one is selected). */
    wakeBeat: function () { return playWaveTransition(); },
    get slide() { return playlist[slideIndex] || null; },
    get mediaTime() {
      var v = currentVideo();
      return v ? v.currentTime : null;
    },
    get mediaPaused() {
      var v = currentVideo();
      return v ? v.paused : null;
    },
    get playlistLength() { return playlist.length; },
    get briefingStory() { return currentProfile === 'briefing' ? (playlist[slideIndex] || null) : null; },
    get briefingContextSeq() { return briefingContextSeq; },
    get lastReportedBriefingStoryId() { return lastReportedBriefingStoryId; },
    get natureItem() { return currentProfile === 'nature' ? (playlist[slideIndex] || null) : null; },
    get natureContextSeq() { return natureContextSeq; },
    get lastReportedNatureItemId() { return lastReportedNatureItemId; },
    get otakuItem() { return currentProfile === 'otaku' ? (playlist[slideIndex] || null) : null; },
    get otakuContextSeq() { return otakuContextSeq; },
    get lastReportedOtakuItemId() { return lastReportedOtakuItemId; },
    get captionText() { return captionLine ? captionLine.textContent : ''; },
    get captionStatus() { return captionReveal ? captionReveal.status() : null; },
    get captionStyle() { return captionStyleMode; },
    get captionFontStatus() { return Object.assign({}, captionFontStatus); },
    get captionPreviewText() { return CAPTION_PREVIEW_TEXT; },
    get isBrightCaptionBg() { return body.classList.contains('has-bright-caption-bg'); },
    previewCaption: function (text) { return startCaptionPreview(text); },
    pushCaption: function (text) { pushCaptionChunk(text); return true; },
    /* Compare the thinking treatments on the real display without a redeploy:
       'focus' (defocus), 'desat' (colour drains), 'both'. */
    get thinking() { return body.dataset.think; },
    get waveCanary() { return waveCanary; },
    get waveStatus() { return waveSurface ? waveSurface.getStatus() : null; },
    get sineWaveCanaryMode() { return sineWaveCanaryMode; },
    get sineWaveStatus() { return sineWaveSurface ? sineWaveSurface.getStatus() : null; },
    get pillStatus() { return statePill ? statePill.getStatus() : null; },
    setThinking: function (style) {
      if (THINKING_STYLES.indexOf(style) === -1) return false;
      body.dataset.think = style;
      try { window.localStorage.setItem('jarvisThinking', style); } catch (e) {}
      return true;
    },
    get visualAnswer() { return (isVisualAnswerActive || isVisualAnswerExiting) ? currentVisualAnswerKind : null; },
    get isVisualAnswerActive() { return isVisualAnswerActive; },
    get isVisualAnswerExiting() { return isVisualAnswerExiting; },
    get visualAnswerState() {
      if (isVisualAnswerActive) return 'active';
      if (isVisualAnswerExiting) return 'exiting';
      return 'inactive';
    },
    get listeningAdmission() {
      return {
        delayMs: LISTENING_ADMISSION_MS,
        pending: listeningAdmissionTimer !== null
      };
    },
    showWeather: function (data) { showWeatherVisualAnswer(data); },
    showFX: function (data) { showFXVisualAnswer(data); },
    clearVisualAnswer: function (reason, options) { hideVisualAnswer(reason || 'debug', options); },
    /* Media check and playlist rotation hooks */
    checkMedia: function () { return checkMediaUpdate(); },
    applyPending: function () {
      if (visualState === 'idle' && !isVisualAnswerActive && !isVisualAnswerExiting) {
        var applied = applyPendingPlaylist();
        if (applied) {
          showSlide(slideIndex + 1);
        }
        return applied;
      }
      return false;
    },
    /* Debug hook used by tools/cdp_eval.py to put a known slide on screen
       during validation. Not used by the renderer itself. */
    show: function (i) { if (visualState === 'idle') showSlide(i); },
    transitions: []
  };

  /* ------------------------------------------------------- overlay host

     The gallery does not know what a calendar is, and the calendar does not
     know what a gallery is. This is the whole contract between them: an
     overlay asks for the screen, and while it holds it the gallery stops
     advancing, the current video holds where it is, and a profile switch
     that arrived by voice waits rather than replacing the scene underneath a
     panel the user is reading. Releasing it puts everything back exactly
     where it was — the video resumes in place, it is never restarted.

     Presentation arbitration: a Visual Answer answers the turn that produced
     it and outranks an overlay somebody left open, so overlays are preempted
     rather than stacked. */
  var overlayHolders = {};
  var overlayHolderCount = 0;
  var preemptHandlers = [];

  /* One explicit priority edge, not a framework. An ambient caption is a
     glance at the photograph; the Calendar is an interaction with a deadline
     attached, and it owns the right-edge gesture. So a caption may declare
     that it steps aside — and whatever outranks it is, in turn, allowed to
     treat it as if it were not holding at all, which is what keeps the edge
     swipe working without the user dismissing the caption by hand first.
     Only the Nature caption registers here. */
  var yieldHandlers = {};

  function overlaysHolding() { return overlayHolderCount > 0; }

  function preemptOverlays(reason) {
    for (var i = 0; i < preemptHandlers.length; i++) {
      try { preemptHandlers[i](reason); } catch (e) { /* fail-open */ }
    }
  }

  window.jarvisOverlays = {
    acquire: function (name) {
      if (overlayHolders[name]) return true;
      overlayHolders[name] = true;
      overlayHolderCount++;
      holdGallery();
      return true;
    },
    release: function (name) {
      if (!overlayHolders[name]) return false;
      delete overlayHolders[name];
      overlayHolderCount--;
      /* A session already owns the hold; only an idle screen resumes here. */
      if (!overlaysHolding() && visualState === 'idle' && !isVisualAnswerActive && !isVisualAnswerExiting) {
        if (!applyPendingProfileSwitch()) resumeGallery();
      }
      return true;
    },
    onPreempt: function (fn) {
      if (typeof fn === 'function') preemptHandlers.push(fn);
    },
    get holding() { return overlaysHolding(); },
    get holders() { return Object.keys(overlayHolders); },
    /* What an overlay is allowed to ask about the rest of the screen: whether
       Jarvis is mid-conversation, and whether something outranks it. */
    get sessionActive() { return visualState !== 'idle'; },
    get busy() { return isVisualAnswerActive || isVisualAnswerExiting; },
    /* `onYield` is how an ambient caption declares it steps aside;
       `yields` is how a higher-priority surface recognises one; and
       `claimScreen` is that surface saying it is taking the screen now. A
       claimant acquires its own hold first, so a caption letting go here
       never lets the gallery resume for an instant in between. */
    onYield: function (name, fn) {
      if (name && typeof fn === 'function') yieldHandlers[name] = fn;
    },
    yields: function (name) {
      return Object.prototype.hasOwnProperty.call(yieldHandlers, name);
    },
    claimScreen: function (reason) {
      var names = Object.keys(yieldHandlers);
      var yielded = [];
      for (var i = 0; i < names.length; i++) {
        if (!overlayHolders[names[i]]) continue;
        try {
          yieldHandlers[names[i]](reason || 'claimed');
          yielded.push(names[i]);
        } catch (e) { /* fail-open: the claimant still gets the screen */ }
      }
      return yielded;
    }
  };

  function claimScreenFromCaptions(reason) {
    return window.jarvisOverlays.claimScreen(reason);
  }

  /* ---------------------------------------------------------------- media */

  /* Every media call names the *requested* profile, so a fallback served under
     a different profile never rewrites what this display is asking for. */
  function mediaQuery(extra) {
    var params = new URLSearchParams(window.location.search);
    if (requestedProfile) params.set('profile', requestedProfile);
    if (extra) params.set(extra[0], extra[1]);
    var q = params.toString();
    return q ? '?' + q : '';
  }

  function waveModeRequested() {
    var value = new URLSearchParams(window.location.search).get('wave');
    if (value === 'sine-soft' || value === 'sine-wave' || value === 'sine-ripple') return value;
    if (value === 'svg' || value === '1' || value === 'true' || value === 'on') return 'svg';
    return null;
  }

  function pillModeRequested() {
    var value = new URLSearchParams(window.location.search).get('pill');
    if (value === 'listening' || value === 'thinking' ||
        value === 'searching' || value === 'cycle') return value;
    return null;
  }

  function initStatePill() {
    if (!statePillHost || !window.JarvisStatePill) return;
    try {
      statePill = window.JarvisStatePill.create(statePillHost);
      var mode = pillModeRequested();
      if (mode) statePill.startCanary(mode);
    } catch (error) {
      console.warn('[StatePill] adapter unavailable; continuing without pill', error);
      statePill = null;
    }
  }

  function initWakeWaveSurface() {
    var mode = waveModeRequested();
    waveCanary = mode === 'svg';
    sineWaveCanaryMode = mode === 'sine-soft' || mode === 'sine-wave' || mode === 'sine-ripple' ? mode : null;
    if (!waveCanary) return;
    body.dataset.wave = 'on';

    if (!window.WakeWaveSurface) {
      if (waveCanary) {
        console.warn('[WakeWave] adapter is unavailable; using normal viewport');
      }
      return;
    }

    var root = document.getElementById('jarvis-visual-root');
    if (!root) {
      console.warn('[WakeWave] visual root is unavailable; using normal viewport');
      return;
    }

    try {
      waveSurface = window.WakeWaveSurface.create(root, {
        continuous: waveCanary
      });
      /* ?wave=1 is the continuous screen-distortion inspection path.
         Production keeps the filter dormant until the idle -> Live boundary. */
      waveSurface.setEnabled(waveCanary);
    } catch (error) {
      if (waveCanary) {
        console.warn('[WakeWave] canary disabled; using normal viewport', error);
      }
      waveSurface = null;
    }
  }

  function initSineWaveSurface() {
    if (!window.SineWaveSurface) {
      console.warn('[SineWave] adapter is unavailable; using normal gallery image');
      return;
    }

    var canvas = document.getElementById('sine-wave-surface');
    if (!canvas) {
      console.warn('[SineWave] canvas is unavailable; using normal gallery image');
      return;
    }

    body.dataset.waveSine = sineWaveCanaryMode || 'production';
    try {
      sineWaveSurface = sineWaveCanaryMode
        ? window.SineWaveSurface.create(canvas, sineWaveCanaryMode)
        : window.SineWaveSurface.create(canvas);
      /* The original two canaries remain continuous for visual comparison.
         sine-ripple models the short wake candidate and starts once after its
         current gallery image is ready. Production stays dormant until the
         authoritative idle -> Live transition calls playWaveTransition(). */
      if (sineWaveCanaryMode && sineWaveCanaryMode !== 'sine-ripple') {
        sineWaveSurface.setEnabled(true);
      }
    } catch (error) {
      console.warn('[SineWave] canary disabled; using normal gallery image', error);
      sineWaveSurface = null;
      delete body.dataset.waveSine;
    }
  }

  function syncSineWaveSurface(item, slot) {
    if (!sineWaveSurface) return;
    if (!item || item.type === 'video' || currentProfile === 'art') {
      /* The sine shader reproduces the normal full-bleed cover crop. ART uses
         a contained image in a bounded left field, so reusing that texture
         would jump to the wrong composition during wake. Keep the artwork
         untouched until the shader learns a contain-region contract. */
      sineWaveSurface.setImage(null);
      return;
    }
    var image = slot && slot.firstElementChild;
    if (!image || image.tagName !== 'IMG') {
      sineWaveSurface.setImage(null);
      return;
    }
    sineWaveSurface.setImage(image);
    if (sineWaveCanaryMode === 'sine-ripple' && typeof sineWaveSurface.playWhenReady === 'function') {
      sineWaveSurface.playWhenReady();
    }
  }

  function playWaveTransition() {
    /* ART's composition is contain-in-a-bounded-field, while both wake-wave
       image paths assume a full-bleed gallery frame. Preserve the work rather
       than briefly replacing it with a cropped texture at Live entry. */
    if (currentProfile === 'art') return false;
    if (waveCanary) {
      if (!waveSurface || typeof waveSurface.play !== 'function') return false;
      try {
        return waveSurface.play();
      } catch (error) {
        console.warn('[WakeWave] SVG rollback playback failed; using normal viewport', error);
        return false;
      }
    }
    if (sineWaveCanaryMode && sineWaveSurface && typeof sineWaveSurface.playWhenReady === 'function') {
      var image = slots[activeSlot] && slots[activeSlot].firstElementChild;
      if (!image || image.tagName !== 'IMG') return false;
      try {
        return sineWaveSurface.playWhenReady();
      } catch (error) {
        console.warn('[SineWave] Live-entry playback failed; using normal viewport', error);
        return false;
      }
    }
    return false;
  }

  function currentVideo() {
    var el = slots[activeSlot].firstElementChild;
    return el && el.tagName === 'VIDEO' ? el : null;
  }

  function releaseSlot(slot) {
    var el = slot.firstElementChild;
    if (el && el.tagName === 'VIDEO') {
      try {
        el.pause();
        el.removeAttribute('src');
        el.load();  // release the decoder rather than waiting for GC
      } catch (e) { /* fail-open */ }
    }
    slot.replaceChildren();
  }

  function buildMediaElement(item) {
    if (item.type === 'video') {
      var video = document.createElement('video');
      video.src = item.url;
      video.muted = true;
      video.autoplay = true;
      video.playsInline = true;
      video.loop = true;
      video.setAttribute('playsinline', '');
      video.setAttribute('disablepictureinpicture', '');
      video.disableRemotePlayback = true;
      video.addEventListener('error', function () {
        console.warn('[Gallery] video failed, advancing:', item.url);
        advance();
      });
      return video;
    }
    var img = document.createElement('img');
    /* The production sine adapter and its canaries reuse this exact gallery
       image as their single WebGL texture. Set CORS before src so a redirected
       media URL remains usable; if the adapter is unavailable, the ordinary
       DOM image path remains unchanged. */
    if (sineWaveSurface || sineWaveCanaryMode) img.crossOrigin = 'anonymous';
    img.src = item.url;
    img.decoding = 'async';
    img.alt = '';
    img.addEventListener('error', function () {
      console.warn('[Gallery] image failed, advancing:', item.url);
      advance();
    });
    return img;
  }

  function renderArt(item) {
    if (!item || !artCopy) return;
    artCopy.classList.remove('is-revealed');

    var kindLabels = {
      painting: 'PAINTING', sculpture: 'SCULPTURE', photography: 'PHOTOGRAPHY',
      architecture: 'ARCHITECTURE', drawing: 'DRAWING', print: 'PRINT', artwork: 'ARTWORK'
    };
    var kind = item.artwork_type || 'artwork';
    var ratio = Number(item.aspect_ratio) || 0;
    body.dataset.artLayout = ratio >= 1.45 ? 'wide' : 'side';
    artEls.kicker.textContent = (kindLabels[kind] || 'ARTWORK') + ' / OPEN ACCESS';
    artEls.title.textContent = item.title || 'Untitled';
    artEls.creator.textContent = item.creator || 'Artist unknown';

    var meta = [];
    if (item.date) meta.push(item.date);
    if (item.medium) meta.push(item.medium);
    artEls.meta.textContent = meta.join(' · ');
    artEls.note.textContent = item.note || item.source_description || '';
    artEls.source.textContent = item.attribution || item.source || '';
    artEls.license.textContent = item.license || '';

    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () {
        if (currentProfile === 'art') artCopy.classList.add('is-revealed');
      });
    });
  }

  function briefingLineCount(el, size) {
    el.style.fontSize = size + 'px';
    var maxHeight = el.style.maxHeight;
    var overflow = el.style.overflow;
    el.style.maxHeight = 'none';
    el.style.overflow = 'visible';
    var lh = parseFloat(window.getComputedStyle(el).lineHeight);
    var lines = Math.round(el.offsetHeight / lh);
    el.style.maxHeight = maxHeight;
    el.style.overflow = overflow;
    return lines;
  }

  function fitBriefingHeadline(el, text) {
    el.textContent = text;
    var chosen = BRIEFING_LADDER[BRIEFING_LADDER.length - 1];
    if (briefingLineCount(el, BRIEFING_LADDER[0]) <= 2) {
      chosen = BRIEFING_LADDER[0];
    } else {
      for (var i = 1; i < BRIEFING_LADDER.length; i++) {
        if (briefingLineCount(el, BRIEFING_LADDER[i]) <= 3) { chosen = BRIEFING_LADDER[i]; break; }
      }
    }
    el.style.fontSize = chosen + 'px';
    if (briefingLineCount(el, chosen) > 3) {
      var words = text.split(' ');
      while (words.length > 2 && briefingLineCount(el, chosen) > 3) {
        words.pop();
        el.textContent = words.join(' ') + '\u2026';
      }
    }
  }

  function renderBriefing(story) {
    if (!story) return;
    briefingCopy.classList.remove('is-revealed');

    briefingEls.category.textContent = story.category || '';
    briefingEls.topic.textContent = story.topic || '';
    briefingEls.time.textContent = story.freshness || '';
    briefingEls.deck.textContent = story.deck || '';
    briefingEls.source.textContent = story.source || '';

    fitBriefingHeadline(briefingEls.headline, story.headline || '');

    briefingCopy.dataset.deck = story.deck ? 'yes' : 'none';
    if (story.relevance) {
      briefingEls.relevance.textContent = 'Related · ' + story.relevance;
      briefingCopy.dataset.relevance = 'on';
    } else {
      briefingEls.relevance.textContent = '';
      briefingCopy.dataset.relevance = 'off';
    }

    /* How far the shadow has to be carried is a property of the photograph.
       The curator measured it once at ingest so the renderer never has to. */
    var luma = typeof story.zone_luma === 'number' ? story.zone_luma : 90;
    var lift = Math.max(0, Math.min(1, (luma - 58) / 150));
    briefingSurface.style.setProperty('--well-extra', lift.toFixed(3));

    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () {
        briefingCopy.classList.add('is-revealed');
      });
    });
  }

  function showSlide(index) {
    if (!playlist.length) return;
    if (currentProfile === 'otaku') {
      var checked = 0;
      while (checked < playlist.length) {
        var candidate = playlist[((index % playlist.length) + playlist.length) % playlist.length];
        var vote = window.jarvisOtakuPersonal ? window.jarvisOtakuPersonal.vote(candidate) : candidate.feedback;
        if (vote !== 'dislike') break;
        index++; checked++;
      }
      if (checked === playlist.length) {
        // No eligible picture remains. Do not redisplay a disliked work.
        slots.forEach(function (slot) { slot.classList.remove('is-active'); });
        window.clearTimeout(advanceTimer);
        advanceTimer = window.setTimeout(advance, 10000);
        return;
      }
    }
    slideIndex = ((index % playlist.length) + playlist.length) % playlist.length;
    var item = playlist[slideIndex];
    var next = activeSlot === 0 ? 1 : 0;

    releaseSlot(slots[next]);
    slots[next].appendChild(buildMediaElement(item));
    slots[next].classList.add('is-active');
    slots[activeSlot].classList.remove('is-active');

    var previous = activeSlot;
    activeSlot = next;
    body.dataset.media = item.type === 'briefing' ? 'image' : item.type;
    syncSineWaveSurface(item, slots[next]);
    updateCaptionTone(item, slots[next]);
    if (currentProfile === 'art') {
      renderArt(item);
    }
    if (currentProfile === 'briefing') {
      renderBriefing(item);
      if (item && item.id) {
        reportBriefingContext(item.id, currentGeneration);
      }
    }
    if (currentProfile === 'nature' && item && item.id) {
      reportNatureContext(item.id, currentGeneration);
    }
    if (currentProfile === 'otaku' && item && item.id) {
      reportOtakuContext(item.id, currentGeneration);
    }

    // Free the outgoing slot only after the cross-dissolve has finished.
    window.setTimeout(function () { releaseSlot(slots[previous]); }, 2800);

    var video = currentVideo();
    if (video) {
      /* Whatever put this frame on the stage, it does not start moving while
         an overlay holds the screen. Guarding only the callers left one way
         in: a slide shown under an open calendar would autoplay and then be
         resumed a second time on release. resumeGallery() starts it, in
         place, when the hold is handed back. */
      if (overlaysHolding()) {
        video.pause();
      } else {
        var p = video.play();
        if (p) p.catch(function () { /* autoplay policy is relaxed in kiosk */ });
      }
    }
    scheduleAdvance();
  }

  function scheduleAdvance() {
    window.clearTimeout(advanceTimer);
    if (playlist.length < 2) return;
    // The gallery only advances while idle; a session holds the frame, and so
    // does an open overlay — the photograph behind the calendar must not move.
    if (visualState !== 'idle') return;
    if (overlaysHolding()) return;
    var item = playlist[slideIndex];
    var dwell = profileDwellMs || IMAGE_DWELL_MS;
    /* A briefing frame is read, not glanced at. Its editorial cadence remains
       independently tunable; ART uses the profile's slower 50s museum dwell. */
    if (currentProfile === 'briefing') dwell = briefingDwellMs || 32000;
    if (currentProfile === 'otaku' && item && window.jarvisOtakuPersonal && window.jarvisOtakuPersonal.vote(item) === 'like') dwell *= 2;
    if (item && item.type === 'video') {
      dwell = Math.max(12000, (item.duration || 24) * 1000);
    }
    advanceTimer = window.setTimeout(advance, dwell);
  }

  var currentPersonalRevision = 0;
  function checkMediaUpdate() {
    return fetch('/api/media' + mediaQuery(['check', '1']))
      .then(function (r) {
        if (!r.ok) throw new Error('check media failed: ' + r.status);
        return r.json();
      })
      .then(function (data) {
        if (!data || !data.ok) return false;
        var newGen = data.generation;
        if ((newGen !== undefined && currentGeneration !== null && newGen !== currentGeneration) ||
            (currentProfile === 'otaku' && data.personal_revision !== undefined && data.personal_revision !== currentPersonalRevision)) {
          console.log('[Gallery] detected playlist generation change: ' + currentGeneration + ' -> ' + newGen);
          return fetchFullPlaylist(newGen);
        }
        return false;
      })
      .catch(function (err) {
        console.warn('[Gallery] checkMediaUpdate error:', err);
        return false;
      });
  }

  function fetchFullPlaylist(newGen) {
    return fetch('/api/media' + mediaQuery())
      .then(function (r) {
        if (!r.ok) throw new Error('full media fetch failed: ' + r.status);
        return r.json();
      })
      .then(function (data) {
        if (data && Array.isArray(data.items) && data.items.length > 0) {
          if (data.personal_revision !== undefined) currentPersonalRevision = data.personal_revision;
          /* The briefing can fall back to the family gallery when its pool is
             empty, so the served profile can legitimately differ from the one
             requested. It is carried with the playlist rather than applied on
             arrival: restyling the page for a profile whose first frame is not
             up yet would change the screen outside a safe boundary. */
          pendingActiveProfile = data.profile || null;
          pendingDwellMs = data.dwell_ms || null;
          pendingPlaylist = data.items;
          pendingGeneration = data.generation !== undefined ? data.generation : newGen;
          console.log('[Gallery] stored pending playlist with ' + pendingPlaylist.length + ' items (generation: ' + pendingGeneration + ')');
          // If the stage was empty, apply immediately
          if (!playlist.length) {
            applyPendingPlaylist();
            showSlide(0);
          }
          return true;
        }
        return false;
      })
      .catch(function (err) {
        console.warn('[Gallery] fetchFullPlaylist error:', err);
        return false;
      });
  }

  function applyPendingPlaylist() {
    if (!pendingPlaylist || !pendingPlaylist.length) return false;
    var currentItem = playlist[slideIndex] || null;
    var switching = pendingProfileSwitch;
    playlist = pendingPlaylist;
    currentGeneration = pendingGeneration;
    if (pendingActiveProfile && pendingActiveProfile !== currentProfile) {
      var prevProfile = currentProfile;
      currentProfile = pendingActiveProfile;
      body.dataset.profile = currentProfile;
      if (prevProfile === 'briefing' && currentProfile !== 'briefing') {
        reportBriefingContext(null, currentGeneration);
      }
      if (prevProfile === 'nature' && currentProfile !== 'nature') {
        reportNatureContext(null, currentGeneration);
      }
      if (prevProfile === 'otaku' && currentProfile !== 'otaku') {
        reportOtakuContext(null, currentGeneration);
      }
    }
    profileDwellMs = pendingDwellMs || IMAGE_DWELL_MS;
    if (currentProfile === 'briefing') briefingDwellMs = pendingDwellMs || 32000;
    pendingPlaylist = null;
    pendingGeneration = null;
    pendingActiveProfile = null;
    pendingDwellMs = null;
    pendingProfileSwitch = false;
    reportActiveProfile();

    /* A profile switch is a new screen, not a continuation of the old one. */
    if (switching) {
      slideIndex = -1;
      console.log('[Gallery] applied profile switch (active: ' + currentProfile + ', requested: ' + requestedProfile + ')');
      return true;
    }

    // Preserve continuity if current slide exists in new playlist
    if (currentItem) {
      var foundIdx = -1;
      for (var i = 0; i < playlist.length; i++) {
        if (playlist[i].id === currentItem.id || (currentProfile !== 'otaku' && playlist[i].source_id && playlist[i].source_id === currentItem.source_id)) {
          foundIdx = i;
          break;
        }
      }
      if (foundIdx !== -1) {
        slideIndex = foundIdx;
      } else {
        // Current item was evicted: keep index within range so next advance is in bounds
        slideIndex = (slideIndex % playlist.length);
      }
    } else {
      slideIndex = -1;
    }
    console.log('[Gallery] applied pending playlist (generation: ' + currentGeneration + ', count: ' + playlist.length + ')');
    return true;
  }

  /* An explicit switch is not a background refresh. The playlist is fetched
     and held immediately — a conversation must not be interrupted by the
     screen changing under it — and then applied at the first moment the
     gallery is allowed to move: reaching idle with no visual answer up. That
     boundary is the whole wait; the user does not also serve out the rest of
     the current frame's dwell. */
  function applyProfileRequest(profileId) {
    var id = String(profileId || '').trim().toLowerCase();
    if (!id) return false;
    if (id === requestedProfile && !pendingProfileSwitch && id === currentProfile) {
      return true;   // already showing exactly what was asked for
    }
    if (id !== 'otaku' && window.jarvisOtakuGuide) window.jarvisOtakuGuide.close('profile_requested');
    if (id !== 'otaku' && window.jarvisOtakuResearch) window.jarvisOtakuResearch.close('profile_requested');
    if (id !== 'otaku' && window.jarvisOtakuPersonal) window.jarvisOtakuPersonal.close('profile_requested');
    requestedProfile = id;
    rememberProfileInUrl(id);
    pendingProfileSwitch = true;
    console.log('[Gallery] profile requested: ' + id + ' (active: ' + currentProfile + ')');
    fetchFullPlaylist(null).then(function () {
      applyPendingProfileSwitch();
    });
    return true;
  }

  function applyPendingProfileSwitch() {
    if (!pendingProfileSwitch) return false;
    if (!pendingPlaylist || !pendingPlaylist.length) return false;
    if (visualState !== 'idle' || isVisualAnswerActive || isVisualAnswerExiting) return false;
    /* A profile switch replaces the whole scene. Doing that under an open
       overlay would change the screen out from under someone reading it, so
       the request stands and lands when the overlay closes. */
    if (overlaysHolding()) return false;
    if (!applyPendingPlaylist()) return false;
    showSlide(0);
    return true;
  }

  /* So an ordinary browser reload — the kiosk watchdog's recovery path — comes
     back on the profile that was chosen by voice, without this switch itself
     ever depending on navigation. */
  function rememberProfileInUrl(id) {
    try {
      var url = new URL(window.location.href);
      url.searchParams.set('profile', id);
      window.history.replaceState(null, '', url.toString());
    } catch (e) { /* fail-open: the runtime switch does not need the URL */ }
  }

  function reportActiveProfile() {
    if (currentProfile === reportedProfile) return;
    reportedProfile = currentProfile;
    fetch('/api/profile/applied', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile: currentProfile })
    }).catch(function () { /* fail-open: reporting is observability, not state */ });
  }

  function startMediaCheckTimer() {
    window.clearTimeout(mediaCheckTimer);
    mediaCheckTimer = window.setTimeout(function () {
      checkMediaUpdate().finally(function () {
        startMediaCheckTimer();
      });
    }, MEDIA_CHECK_INTERVAL_MS);
  }

  function advance(freshPreferences) {
    if (visualState !== 'idle') return;
    if (isVisualAnswerActive || isVisualAnswerExiting) return;
    if (overlaysHolding()) return;

    if (currentProfile === 'otaku' && window.jarvisOtakuPersonal && freshPreferences !== true) {
      window.jarvisOtakuPersonal.refresh().finally(function () { advance(true); });
      return;
    }

    if (pendingPlaylist && pendingPlaylist.length > 0) {
      applyPendingPlaylist();
    }

    showSlide(slideIndex + 1);
  }

  /* Session ownership of gallery playback: freeze the current frame for the
     whole conversation, then continue from exactly where it stopped. */
  function holdGallery() {
    window.clearTimeout(advanceTimer);
    var video = currentVideo();
    if (video && !video.paused) video.pause();
  }

  function resumeGallery() {
    var video = currentVideo();
    if (video && video.paused) {
      var p = video.play();   // no currentTime reset: it resumes in place
      if (p) p.catch(function () { /* fail-open */ });
    }
    scheduleAdvance();
  }

  /* ---------------------------------------------------------- state grammar */

  /* Listening is authoritative immediately, but a follow-up pill over a full
     visual answer is admitted only after a short presentation interval. This
     is intentionally renderer-only: the Live state, microphone, input path,
     and idle policy continue on their existing schedule. */
  function cancelListeningAdmission() {
    listeningAdmissionGeneration += 1;
    if (listeningAdmissionTimer !== null) {
      window.clearTimeout(listeningAdmissionTimer);
      listeningAdmissionTimer = null;
    }
  }

  function scheduleListeningAdmission() {
    cancelListeningAdmission();
    if (!statePill) return;

    /* A Visual Answer may become active after the semantic state is already
       listening. Force the pill back to its hidden state so admission always
       starts from the same visual boundary. */
    statePill.setState('hidden');
    var generation = listeningAdmissionGeneration;
    listeningAdmissionTimer = window.setTimeout(function () {
      listeningAdmissionTimer = null;
      if (generation !== listeningAdmissionGeneration) return;
      if (!isVisualAnswerActive || visualState !== 'listening' ||
          steadyState !== 'listening') return;
      statePill.setState('listening');
    }, LISTENING_ADMISSION_MS);
  }

  function applyStatePill(name, options) {
    if (!statePill) {
      cancelListeningAdmission();
      return;
    }
    if (name === 'listening' && isVisualAnswerActive) {
      scheduleListeningAdmission();
      return;
    }
    cancelListeningAdmission();
    statePill.setState(name, options);
  }

  function hideStatePillBeforeVisualAnswerExit() {
    cancelListeningAdmission();
    if (statePill) statePill.setState('hidden');
  }

  function applyVisualState(name, options) {
    if (visualState === name) return;
    var previous = visualState;
    window.jarvisGallery.transitions.push({
      from: previous, to: name, t: Date.now()
    });
    if (window.jarvisGallery.transitions.length > 200) {
      window.jarvisGallery.transitions.splice(0, 100);
    }
    visualState = name;
    body.dataset.state = name;
    applyStatePill(name, options);
    if (name === 'idle') {
      // The switch the user asked for during the conversation lands here,
      // before the frame resumes, rather than after another full dwell.
      // An overlay that is still open keeps the hold: the session ended, the
      // reason to freeze the frame did not.
      if (overlaysHolding() || isVisualAnswerActive || isVisualAnswerExiting) {
        holdGallery();
      } else if (!applyPendingProfileSwitch()) {
        resumeGallery();
      }
    } else {
      holdGallery();
    }
  }

  function setSemanticState(name) {
    var captionWasSpeaking = false;
    var previousSteadyState = steadyState;
    if (!registry.states[name] && name !== 'idle') {
      console.warn('[Gallery] unknown state, ignoring:', name);
      return;
    }
    steadyState = name;

    window.clearTimeout(eventTimer);

    if (captionReveal) {
      var captionStatus = captionReveal.status();
      captionWasSpeaking = Boolean(captionStatus && captionStatus.speaking);
      captionReveal.setSpeaking(name === 'speaking');
    }
    if (name === 'idle') {
      /* Conversation IDLE and result presentation are independent. Keep a
         leased card visible while hiding the interaction pill. The lease
         clear event will later reveal/resume the ambient Gallery. */
      hideStatePillBeforeVisualAnswerExit();
      /* SPEAKING -> idle is the playback-drain authority. Let the renderer
         flush and hold its final completed lines; only an orphaned buffer
         that never entered SPEAKING should be cleared immediately. */
      if (!captionWasSpeaking) clearCaption(true);
    } else if (previousSteadyState === 'idle' && (isVisualAnswerActive || isVisualAnswerExiting)) {
      /* Fresh wake always outranks a result left by the previous session.
         This renderer-side boundary also protects against cross-queue HTTP
         ordering between the state and visual-answer side channels. */
      hideStatePillBeforeVisualAnswerExit();
      hideVisualAnswer('new_wake');
    }

    /* A conversation starting is not a moment to keep a caption up: the
       photograph underneath is preserved exactly as it was, and the answer
       gets the screen. The gallery hold is already owned by the session. */
    if (previousSteadyState === 'idle' && name !== 'idle') {
      claimScreenFromCaptions('session_start');
    }

    // Fresh wake boundary: idle -> Live session.
    // The gallery remains completely still. The State Pill alone performs its
    // drop-in entrance animation with overshoot. Subsequent turns within the same
    // session preserve the pill in place without replaying entrance.
    if (visualState === 'idle' && name !== 'idle') {
      if (waveCanary || sineWaveCanaryMode) {
        playWaveTransition();
      }
      applyVisualState(name, { entrance: true });
      return;
    }

    if (visualState === 'wake') {
      pendingState = name;
      return;
    }

    applyVisualState(name);
  }

  /* One-shot events keep the legacy server contract: express them with the
     speaking grammar, then report completion so /api/status is never stuck. */
  function runEvent(name) {
    var info = registry.events[name];
    var duration = (info && info.duration ? info.duration : 6.0) * 1000;
    applyVisualState('speaking');
    window.clearTimeout(eventTimer);
    eventTimer = window.setTimeout(function () {
      fetch('/api/event_completed', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      }).catch(function () { /* fail-open */ });
      applyVisualState(steadyState === 'idle' ? 'idle' : steadyState);
    }, duration);
  }

  /* -------------------------------------------------------------- captions

     Caption transport remains the same fail-open SSE side channel. The
     renderer-owned controller buffers output transcription, but only the
     semantic SPEAKING transition allows it to create visible completed-line
     DOM. Rapid deltas only coalesce hidden composition measurement; the
     incomplete current line never paints. Chromium's actual typography and
     width own wrapping, and a page changes only when the next committed line
     would exceed four physical lines.
     ------------------------------------------------------------------------ */

  function clearCaption(immediate) {
    pendingCaptionChunks = [];
    if (captionReveal) captionReveal.clear(Boolean(immediate));
  }

  function clearCaptionFromTransport() {
    var captionStatus;
    if (!captionReveal) return;
    try {
      captionStatus = captionReveal.status();
      /* jarvis-live sends its non-critical cleanup clear on a separate queue
         from the semantic idle event. SPEAKING/draining remains authoritative
         even if that clear arrives first or immediately after idle. */
      if (captionStatus && (captionStatus.speaking || captionStatus.draining)) {
        return;
      }
    } catch (error) {
      /* A caption probe failure must not affect the normal cleanup path. */
    }
    clearCaption(true);
  }

  function pushCaptionChunk(chunk) {
    if (isVisualAnswerActive || isVisualAnswerExiting || !captionReveal) return;
    if (!captionFontReady) {
      if (typeof chunk === 'string' && chunk.length) pendingCaptionChunks.push(chunk);
      return;
    }
    captionReveal.push(chunk);
  }

  function startCaptionPreview(customText) {
    if (!captionReveal) return false;
    clearCaption(true);
    captionReveal.setSpeaking(true);
    pushCaptionChunk(customText || CAPTION_PREVIEW_TEXT);
    return true;
  }

  function setElementClass(el, className, enabled) {
    if (!el || !el.classList) return;
    if (typeof el.classList.toggle === 'function') {
      el.classList.toggle(className, Boolean(enabled));
    } else if (enabled) {
      el.classList.add(className);
    } else {
      el.classList.remove(className);
    }
  }

  function applyCaptionTone(isBright) {
    setElementClass(body, 'has-bright-caption-bg', isBright);
    var surface = document.getElementById('caption-surface');
    if (surface) setElementClass(surface, 'is-bright-bg', isBright);
  }

  function updateCaptionTone(item, slotEl) {
    if (item && typeof item.zone_luma === 'number') {
      applyCaptionTone(item.zone_luma >= 140);
      return;
    }
    var img = (slotEl && typeof slotEl.querySelector === 'function') ? slotEl.querySelector('img') : null;
    if (!img) {
      applyCaptionTone(false);
      return;
    }
    function sample() {
      if (!img.naturalWidth || !img.naturalHeight) return;
      try {
        var canvas = document.createElement('canvas');
        canvas.width = 16;
        canvas.height = 8;
        var ctx = canvas.getContext('2d', { willReadFrequently: true });
        var sx = Math.floor(img.naturalWidth * 0.15);
        var sy = Math.floor(img.naturalHeight * 0.35);
        var sw = Math.floor(img.naturalWidth * 0.70);
        var sh = Math.floor(img.naturalHeight * 0.30);
        ctx.drawImage(img, sx, sy, sw, sh, 0, 0, 16, 8);
        var data = ctx.getImageData(0, 0, 16, 8).data;
        var sum = 0;
        for (var i = 0; i < data.length; i += 4) {
          sum += 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
        }
        var luma = sum / (data.length / 4);
        applyCaptionTone(luma >= 140);
      } catch (e) {
        applyCaptionTone(false);
      }
    }
    if (img.complete && img.naturalWidth) {
      sample();
    } else {
      img.addEventListener('load', sample, { once: true });
    }
  }

  /* ------------------------------------------------------------- transport */

  function activateVisualAnswer(kind) {
    if (isVisualAnswerExiting) {
      if (visualAnswerExitTimer !== null) {
        window.clearTimeout(visualAnswerExitTimer);
        visualAnswerExitTimer = null;
      }
      visualAnswerExitGeneration++;
      isVisualAnswerExiting = false;
      console.log('[VisualAnswer] exit preempted by new visual answer: kind=' + kind);
    }
    body.classList.add('has-visual-answer');
    if (visualAnswerSurface) {
      visualAnswerSurface.classList.remove('is-exiting');
      visualAnswerSurface.dataset.kind = kind;
      visualAnswerSurface.classList.add('is-active');
    }
    isVisualAnswerActive = true;
    currentVisualAnswerKind = kind;
    holdGallery();

    /* The answer can arrive after the semantic state is already listening.
       Re-enter the same scoped admission path used by the state transition. */
    if (visualState === 'listening' && steadyState === 'listening') {
      applyStatePill('listening');
    }
  }

  function handleVisualAnswer(msg) {
    if (!msg || typeof msg !== 'object') return;
    if (msg.clear) {
      hideVisualAnswer(msg.reason || 'clear_requested');
    } else if (msg.kind === 'weather' && msg.data) {
      showWeatherVisualAnswer(msg.data);
    } else if (msg.kind === 'fx' && msg.data) {
      showFXVisualAnswer(msg.data);
    } else if (msg.kind === 'portfolio' && msg.data) {
      showPortfolioVisualAnswer(msg.data);
    }
  }

  function showWeatherVisualAnswer(data) {
    clearCaption(true);
    preemptOverlays('visual_answer');
    if (!weatherFrame) return;

    function applyToFrame() {
      var cw = weatherFrame.contentWindow;
      if (!cw || !cw.jarvisWeather || !cw.jarvisWeather.showHA) {
        console.warn('[VisualAnswer] weather renderer not ready inside iframe');
        return;
      }
      activateVisualAnswer('weather');
      cw.jarvisWeather.showHA(data.entity, data.response, weatherOptionsFor(data))
        .then(function (res) {
          if (res) {
            console.log('[VisualAnswer] weather scene revealed: cond=' + res.condition + ' temp=' + res.temperature);
          }
        })
        .catch(function (err) {
          console.warn('[VisualAnswer] failed to render weather scene', err);
        });
    }

    try {
      var cw = weatherFrame.contentWindow;
      if (cw && cw.jarvisWeather && cw.jarvisWeather.showHA) {
        applyToFrame();
      } else {
        pendingWeatherPayload = data;
        weatherFrame.onload = function () {
          if (pendingWeatherPayload) {
            var p = pendingWeatherPayload;
            pendingWeatherPayload = null;
            applyToFrame();
          }
        };
      }
    } catch (e) {
      console.warn('[VisualAnswer] iframe access error', e);
    }
  }

  function showFXVisualAnswer(data) {
    clearCaption(true);
    preemptOverlays('visual_answer');
    if (!fxFrame) return;

    function applyToFrame() {
      var cw = fxFrame.contentWindow;
      if (!cw || !cw.jarvisFX || !cw.jarvisFX.show) {
        console.warn('[VisualAnswer] FX renderer not ready inside iframe');
        return;
      }
      activateVisualAnswer('fx');
      cw.jarvisFX.show(data)
        .then(function (res) {
          if (res) {
            console.log('[VisualAnswer] FX scene revealed');
          }
        })
        .catch(function (err) {
          console.warn('[VisualAnswer] failed to render FX scene', err);
        });
    }

    try {
      var cw = fxFrame.contentWindow;
      if (cw && cw.jarvisFX && cw.jarvisFX.show) {
        applyToFrame();
      } else {
        pendingFXPayload = data;
        fxFrame.onload = function () {
          if (pendingFXPayload) {
            var p = pendingFXPayload;
            pendingFXPayload = null;
            applyToFrame();
          }
        };
      }
    } catch (e) {
      console.warn('[VisualAnswer] FX iframe access error', e);
    }
  }

  function showPortfolioVisualAnswer(data) {
    clearCaption(true);
    preemptOverlays('visual_answer');
    if (!portfolioFrame) return;

    function applyToFrame() {
      var cw = portfolioFrame.contentWindow;
      if (!cw || !cw.jarvisPortfolio || !cw.jarvisPortfolio.show) {
        console.warn('[VisualAnswer] portfolio renderer not ready inside iframe');
        return;
      }
      activateVisualAnswer('portfolio');
      cw.jarvisPortfolio.show(data)
        .then(function (res) {
          if (res) {
            console.log('[VisualAnswer] portfolio scene revealed');
          }
        })
        .catch(function (err) {
          console.warn('[VisualAnswer] failed to render portfolio scene', err);
        });
    }

    try {
      var cw = portfolioFrame.contentWindow;
      if (cw && cw.jarvisPortfolio && cw.jarvisPortfolio.show) {
        applyToFrame();
      } else {
        pendingPortfolioPayload = data;
        portfolioFrame.onload = function () {
          if (pendingPortfolioPayload) {
            var p = pendingPortfolioPayload;
            pendingPortfolioPayload = null;
            applyToFrame();
          }
        };
      }
    } catch (e) {
      console.warn('[VisualAnswer] portfolio iframe access error', e);
    }
  }

  function hasClass(el, name) {
    return Boolean(el && el.classList && typeof el.classList.contains === 'function' && el.classList.contains(name));
  }

  function addClass(el, name) {
    if (el && el.classList && typeof el.classList.add === 'function') {
      el.classList.add(name);
    }
  }

  function removeClass(el, name) {
    if (el && el.classList && typeof el.classList.remove === 'function') {
      el.classList.remove(name);
    }
  }

  function isDissolveExitReason(reason) {
    if (!reason) return false;
    return reason === 'rearm_chime_completed' ||
           reason.indexOf('rearm_chime') === 0 ||
           reason === 'chime_disabled' ||
           reason === 'playback_timeout' ||
           reason === 'lease_expired';
  }

  function finalizeVisualAnswerClear(reason, source) {
    if (visualAnswerExitTimer !== null) {
      window.clearTimeout(visualAnswerExitTimer);
      visualAnswerExitTimer = null;
    }
    visualAnswerExitGeneration++;

    var wasActiveOrExiting = isVisualAnswerActive || isVisualAnswerExiting ||
      hasClass(visualAnswerSurface, 'is-active') ||
      hasClass(visualAnswerSurface, 'is-exiting') ||
      body.classList.contains('has-visual-answer');

    if (!wasActiveOrExiting) return;

    var duration = visualAnswerExitStartTime ? (Date.now() - visualAnswerExitStartTime) : 0;
    var completedKind = currentVisualAnswerKind;
    var finalReason = reason || visualAnswerExitReason || 'unknown';

    isVisualAnswerActive = false;
    isVisualAnswerExiting = false;
    currentVisualAnswerKind = null;
    pendingWeatherPayload = null;
    pendingFXPayload = null;
    pendingPortfolioPayload = null;
    visualAnswerExitStartTime = 0;
    visualAnswerExitReason = null;

    if (visualAnswerSurface) {
      removeClass(visualAnswerSurface, 'is-active');
      removeClass(visualAnswerSurface, 'is-exiting');
      if (typeof visualAnswerSurface.removeAttribute === 'function') {
        visualAnswerSurface.removeAttribute('data-kind');
      }
    }
    body.classList.remove('has-visual-answer');
    clearCaption(true);

    console.log('[VisualAnswer] visual_result_exit_completed: reason=' + finalReason +
                ' kind=' + (completedKind || 'none') +
                ' duration=' + duration + 'ms' +
                ' source=' + (source || 'direct'));

    // A visual answer outranks the gallery: a profile requested while the
    // card was up waits for the card to go, and applies as soon as it does.
    var profileApplied = applyPendingProfileSwitch();
    if (visualState === 'idle' && !profileApplied && !overlaysHolding()) {
      resumeGallery();
    }
  }

  function hideVisualAnswer(reason, options) {
    var immediate = Boolean(options && options.immediate) || !isDissolveExitReason(reason);

    if (!isVisualAnswerActive && !isVisualAnswerExiting &&
        !body.classList.contains('has-visual-answer') &&
        !hasClass(visualAnswerSurface, 'is-active') &&
        !hasClass(visualAnswerSurface, 'is-exiting')) {
      return;
    }

    cancelListeningAdmission();
    var restoreListeningPill = statePill && visualState === 'listening' &&
      steadyState === 'listening';

    if (immediate) {
      finalizeVisualAnswerClear(reason, 'preempted');
      if (restoreListeningPill) statePill.setState('listening');
      return;
    }

    // Idempotent: duplicate release during EXITING must not restart transition or resume gallery.
    if (isVisualAnswerExiting) {
      console.log('[VisualAnswer] exit already in progress, ignoring duplicate call: reason=' + (reason || 'unknown'));
      return;
    }

    // Start Frozen Cross-Dissolve exit
    isVisualAnswerActive = false;
    isVisualAnswerExiting = true;
    visualAnswerExitStartTime = Date.now();
    visualAnswerExitReason = reason || 'rearm_chime_completed';
    visualAnswerExitGeneration++;
    var generation = visualAnswerExitGeneration;

    console.log('[VisualAnswer] visual_result_exit_started: reason=' + visualAnswerExitReason +
                ' kind=' + currentVisualAnswerKind);

    // Gallery must remain held during transition:
    holdGallery();

    if (restoreListeningPill) statePill.setState('listening');

    if (!visualAnswerSurface || typeof visualAnswerSurface.addEventListener !== 'function') {
      finalizeVisualAnswerClear(visualAnswerExitReason, 'no_surface');
      return;
    }

    removeClass(visualAnswerSurface, 'is-active');
    addClass(visualAnswerSurface, 'is-exiting');

    function onTransitionEnd(e) {
      if (e.target !== visualAnswerSurface) return;
      if (e.propertyName !== 'opacity') return;
      if (generation !== visualAnswerExitGeneration) return;
      if (typeof visualAnswerSurface.removeEventListener === 'function') {
        visualAnswerSurface.removeEventListener('transitionend', onTransitionEnd);
      }
      if (visualAnswerExitTimer !== null) {
        window.clearTimeout(visualAnswerExitTimer);
        visualAnswerExitTimer = null;
      }
      finalizeVisualAnswerClear(visualAnswerExitReason, 'transitionend');
    }

    visualAnswerSurface.addEventListener('transitionend', onTransitionEnd);

    // Bounded fail-safe timer (500-700ms, here 600ms) in case transitionend does not fire
    visualAnswerExitTimer = window.setTimeout(function () {
      visualAnswerExitTimer = null;
      if (generation !== visualAnswerExitGeneration) return;
      if (typeof visualAnswerSurface.removeEventListener === 'function') {
        visualAnswerSurface.removeEventListener('transitionend', onTransitionEnd);
      }
      console.warn('[VisualAnswer] transitionend timed out; finalizing via fallback');
      finalizeVisualAnswerClear(visualAnswerExitReason, 'fallback');
    }, VISUAL_ANSWER_EXIT_FAILSAFE_MS);
  }

  function handleMessage(msg) {
    if (!msg || typeof msg !== 'object') return;
    if (msg.type === 'state') {
      setSemanticState(msg.name);
    } else if (msg.type === 'event') {
      if (msg.steady_state) steadyState = msg.steady_state;
      runEvent(msg.name);
    } else if (msg.type === 'caption') {
      if (msg.clear) {
        clearCaptionFromTransport();
      } else {
        pushCaptionChunk(msg.text || '');
      }
    } else if (msg.type === 'visual_answer') {
      handleVisualAnswer(msg);
    } else if (msg.type === 'otaku_guide') {
      if (window.jarvisOtakuGuide) window.jarvisOtakuGuide.handle(msg);
    } else if (msg.type === 'gallery_profile') {
      applyProfileRequest(msg.profile);
    } else if (msg.type === 'week_skin') {
      if (window.jarvisWeekCalendar) window.jarvisWeekCalendar.setSkin(msg.skin);
    } else if (msg.type === 'calendar') {
      /* Voice and touch drive the same overlay state; there is no separate
         voice calendar UI. The gallery only forwards. */
      routeCalendarMessage(msg);
    } else if (msg.type === 'ask_overlay') {
      if (window.jarvisAskOverlay) window.jarvisAskOverlay.handle(msg);
    }
  }

  /* Two calendar surfaces, one channel. A message that names `view` goes to
     that surface; one that does not is the original month-overlay command
     and keeps its old meaning unless the week is the calendar on screen.
     Mutation lifecycle messages reach both — each ignores what is not its own
     question — except a new question, which belongs to whichever calendar is
     open, and to the week when neither is. */
  function routeCalendarMessage(msg) {
    var week = window.jarvisWeekCalendar;
    var month = window.jarvisCalendar;
    var monthOpen = Boolean(month && month.state && month.state !== 'closed');
    var weekOpen = Boolean(week && week.isOpen);
    if (msg.action === 'mutation') {
      if (msg.event === 'proposal') {
        if (monthOpen || !week) { if (month) month.handle(msg); }
        else week.handle(msg);
        return;
      }
      if (week) week.handle(msg);
      if (month) month.handle(msg);
      return;
    }
    if (msg.action === 'close') {
      if (week) week.handle(msg);
      if (month) month.handle(msg);
      return;
    }
    var view = msg.view || (weekOpen ? 'week' : 'month');
    if (view === 'week' && week) {
      week.handle(msg);
      return;
    }
    if (weekOpen) week.close('month');
    if (month) month.handle(msg);
  }

  function connectSSE() {
    var source = new EventSource('/api/events');
    source.onopen = function () { console.log('[Gallery] SSE connected'); };
    source.onmessage = function (e) {
      try {
        handleMessage(JSON.parse(e.data));
      } catch (err) {
        console.error('[Gallery] bad SSE payload', err);
      }
    };
    source.onerror = function () {
      console.warn('[Gallery] SSE disconnected; EventSource will retry');
    };
  }

  /* ------------------------------------------------------------------ boot */

  function boot() {
    beginCaptionFontLoad();
    initStatePill();
    initWakeWaveSurface();
    initSineWaveSurface();

    /* A treatment chosen on the display survives a reload while we compare. */
    try {
      var saved = window.localStorage.getItem('jarvisThinking');
      if (THINKING_STYLES.indexOf(saved) !== -1) body.dataset.think = saved;
    } catch (e) { /* fail-open */ }

    /* The URL is this display's default; the server's standing request, if it
       has one, outranks it — that is what carries a voice-chosen profile
       across a reload the renderer did not initiate. */
    var urlProfile = new URLSearchParams(window.location.search).get('profile');
    if (urlProfile) requestedProfile = urlProfile.trim().toLowerCase();

    fetch('/api/profile').then(function (r) { return r.json(); })
      .catch(function () { return null; })
      .then(function (state) {
        if (state && state.requested_profile) {
          requestedProfile = state.requested_profile;
          rememberProfileInUrl(requestedProfile);
        }
        return Promise.all([
          fetch('/api/registry').then(function (r) { return r.json(); })
            .catch(function () { return null; }),
          fetch('/api/media' + mediaQuery()).then(function (r) { return r.json(); })
            .catch(function () { return null; })
        ]);
      }).then(function (results) {
      if (results[0] && results[0].registry) registry = results[0].registry;
      if (results[1]) {
        if (results[1].profile) currentProfile = results[1].profile;
        body.dataset.profile = currentProfile;
        profileDwellMs = results[1].dwell_ms || IMAGE_DWELL_MS;
        if (currentProfile === 'briefing') briefingDwellMs = results[1].dwell_ms || 32000;
        if (results[1].generation !== undefined) currentGeneration = results[1].generation;
        if (results[1].personal_revision !== undefined) currentPersonalRevision = results[1].personal_revision;
        if (Array.isArray(results[1].items)) {
          playlist = results[1].items;
        }
      }
      reportActiveProfile();
      if (!playlist.length) {
        console.warn('[Gallery] no media available; showing empty stage');
      } else {
        showSlide(0);
      }
      if (captionPreviewEnabled) {
        window.setTimeout(startCaptionPreview, 900);
      }
      connectSSE();
      startMediaCheckTimer();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
