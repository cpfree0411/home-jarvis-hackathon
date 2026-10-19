/*
 * Jarvis State Pill
 *
 * A deliberately small Vanilla adapter around the official thinking-orbs
 * drawing engine. The rest of the renderer stays framework-free; this module
 * owns the pill DOM, the two-layer cross-fade, and one shared canvas loop.
 */
(function (global) {
  'use strict';

  var ENGINE = global.ThinkingOrbsEngine;
  var ENGINE_SIZE = 64; // thinking-orbs has separately tuned 20px and 64px presets.
  var ORB_SIZE = 36;    // CSS size inside the 58px pill.
  var ENTER_MS = 340;
  var EXIT_MS = 320;
  var STATE_TRANSITION_MS = 260;
  var CYCLE_VISIBLE_MS = 1700;
  var CYCLE_HIDDEN_MS = 900;

  var LABELS = {
    listening: 'Listening....',
    thinking: 'Thinking....',
    searching: 'Searching....'
  };

  var ORB_STATES = {
    listening: 'listening',
    // `working` keeps the organic orbit texture of the reference. `solving`
    // is a more angular Rubik-band treatment and reads as a different visual
    // metaphor on the small 1024x600 display.
    thinking: 'working',
    searching: 'searching'
  };

  var VALID_STATES = {
    hidden: true,
    listening: true,
    thinking: true,
    searching: true
  };

  function requestFrame(fn) {
    if (global.requestAnimationFrame) return global.requestAnimationFrame(fn);
    return global.setTimeout(function () { fn(Date.now()); }, 16);
  }

  function cancelFrame(id) {
    if (!id) return;
    if (global.cancelAnimationFrame) {
      global.cancelAnimationFrame(id);
    } else {
      global.clearTimeout(id);
    }
  }

  function StatePill(host) {
    if (!host) throw new Error('state pill host is missing');
    if (!global.document) throw new Error('state pill document is missing');
    if (!ENGINE || !ENGINE.resolvePreset || !ENGINE.MODE_DRAWS) {
      throw new Error('thinking-orbs engine is unavailable');
    }

    this.host = host;
    this.document = global.document;
    this.state = 'hidden';
    this.canaryMode = null;
    this.canaryTimer = null;
    this.transitionTimer = null;
    this.enterTimer = null;
    this.exitTimer = null;
    this.frameId = 0;
    this.looping = false;
    this.transitioning = false;
    this.activeOrbIndex = 0;
    this.activeLabelIndex = 0;
    this.orbPresets = [null, null];
    this.contexts = [null, null];
    this.motionMedia = null;
    this.reducedMotion = false;

    this.pill = this.document.createElement('div');
    this.pill.className = 'jarvis-state-pill';
    this.pill.setAttribute('role', 'status');
    this.pill.setAttribute('aria-live', 'polite');
    this.pill.setAttribute('aria-atomic', 'true');
    this.pill.setAttribute('aria-hidden', 'true');

    this.orbStack = this.document.createElement('span');
    this.orbStack.className = 'jarvis-state-pill-orb-stack';
    this.orbLayers = [this._createOrbCanvas(), this._createOrbCanvas()];
    this.orbStack.appendChild(this.orbLayers[0]);
    this.orbStack.appendChild(this.orbLayers[1]);

    this.copyStack = this.document.createElement('span');
    this.copyStack.className = 'jarvis-state-pill-copy';
    this.labels = [this._createLabel(), this._createLabel()];
    this.copyStack.appendChild(this.labels[0]);
    this.copyStack.appendChild(this.labels[1]);

    this.pill.appendChild(this.orbStack);
    this.pill.appendChild(this.copyStack);
    this.host.appendChild(this.pill);

    this._render = this._render.bind(this);
    this._visibilityChanged = this._visibilityChanged.bind(this);
    this._motionChanged = this._motionChanged.bind(this);
    this._cycleTick = this._cycleTick.bind(this);

    this.document.addEventListener('visibilitychange', this._visibilityChanged);
    this._watchMotionPreference();
    this._prepareCanvas(this.orbLayers[0], 0);
    this._prepareCanvas(this.orbLayers[1], 1);
  }

  StatePill.prototype._createOrbCanvas = function () {
    var canvas = this.document.createElement('canvas');
    canvas.className = 'jarvis-state-pill-orb-layer';
    canvas.setAttribute('aria-hidden', 'true');
    canvas.setAttribute('role', 'presentation');
    return canvas;
  };

  StatePill.prototype._createLabel = function () {
    var label = this.document.createElement('span');
    label.className = 'jarvis-state-pill-label';
    return label;
  };

  StatePill.prototype._watchMotionPreference = function () {
    if (!global.matchMedia) return;
    this.motionMedia = global.matchMedia('(prefers-reduced-motion: reduce)');
    this.reducedMotion = Boolean(this.motionMedia.matches);
    if (this.motionMedia.addEventListener) {
      this.motionMedia.addEventListener('change', this._motionChanged);
    } else if (this.motionMedia.addListener) {
      this.motionMedia.addListener(this._motionChanged);
    }
  };

  StatePill.prototype._motionChanged = function (event) {
    this.reducedMotion = Boolean(event.matches);
  };

  StatePill.prototype._prepareCanvas = function (canvas, index) {
    var dpr = Math.min(2, global.devicePixelRatio || 1);
    canvas.width = Math.round(ENGINE_SIZE * dpr);
    canvas.height = Math.round(ENGINE_SIZE * dpr);
    canvas.style.width = ORB_SIZE + 'px';
    canvas.style.height = ORB_SIZE + 'px';
    this.contexts[index] = canvas.getContext('2d');
    if (this.contexts[index]) {
      this.contexts[index].setTransform(dpr, 0, 0, dpr, 0, 0);
      this.contexts[index].clearRect(0, 0, ENGINE_SIZE, ENGINE_SIZE);
    }
  };

  StatePill.prototype._setOrbPreset = function (index, state) {
    var orbState = ORB_STATES[state];
    this.orbPresets[index] = ENGINE.resolvePreset(orbState, ENGINE_SIZE);
  };

  StatePill.prototype._paint = function (index, timestamp) {
    var context = this.contexts[index];
    var preset = this.orbPresets[index];
    if (!context || !preset) return;

    var dpr = Math.min(2, global.devicePixelRatio || 1);
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, ENGINE_SIZE, ENGINE_SIZE);
    ENGINE.MODE_DRAWS[preset.mode](
      context,
      ENGINE_SIZE,
      this.reducedMotion ? 0.6 : (timestamp * 0.001 * preset.speed),
      true,
      preset.opts
    );
  };

  StatePill.prototype._render = function (timestamp) {
    this.frameId = 0;
    if (!this.looping || this.document.hidden) return;

    this._paint(this.activeOrbIndex, timestamp);
    if (this.transitioning) {
      this._paint(1 - this.activeOrbIndex, timestamp);
    }
    this.frameId = requestFrame(this._render);
  };

  StatePill.prototype._startLoop = function () {
    if (this.looping || this.document.hidden) return;
    this.looping = true;
    this.frameId = requestFrame(this._render);
  };

  StatePill.prototype._stopLoop = function () {
    this.looping = false;
    cancelFrame(this.frameId);
    this.frameId = 0;
  };

  StatePill.prototype._visibilityChanged = function () {
    if (this.document.hidden) {
      this._stopLoop();
    } else if (this.state !== 'hidden') {
      this._startLoop();
    }
  };

  StatePill.prototype._clearTransition = function () {
    global.clearTimeout(this.transitionTimer);
    this.transitionTimer = null;
    this.transitioning = false;
  };

  StatePill.prototype._setContent = function (state, immediate) {
    var nextOrbIndex = 1 - this.activeOrbIndex;
    var nextLabelIndex = 1 - this.activeLabelIndex;
    var oldOrbIndex = this.activeOrbIndex;
    var oldLabelIndex = this.activeLabelIndex;

    this._clearTransition();
    this._setOrbPreset(nextOrbIndex, state);
    this.labels[nextLabelIndex].textContent = LABELS[state];
    this.labels[nextLabelIndex].classList.remove('is-current');
    this.orbLayers[nextOrbIndex].classList.remove('is-active');

    if (immediate) {
      this.labels[oldLabelIndex].classList.remove('is-current');
      this.orbLayers[oldOrbIndex].classList.remove('is-active');
      this.labels[nextLabelIndex].classList.add('is-current');
      this.orbLayers[nextOrbIndex].classList.add('is-active');
      this.activeOrbIndex = nextOrbIndex;
      this.activeLabelIndex = nextLabelIndex;
      return;
    }

    this.transitioning = true;
    this.activeOrbIndex = nextOrbIndex;
    this.activeLabelIndex = nextLabelIndex;
    requestFrame(function () {
      this.labels[nextLabelIndex].classList.add('is-current');
      this.labels[oldLabelIndex].classList.remove('is-current');
      this.orbLayers[nextOrbIndex].classList.add('is-active');
      this.orbLayers[oldOrbIndex].classList.remove('is-active');
    }.bind(this));

    this.transitionTimer = global.setTimeout(function () {
      this.transitioning = false;
      this.transitionTimer = null;
    }.bind(this), STATE_TRANSITION_MS);
  };

  StatePill.prototype._setStateInternal = function (state, options) {
    if (state === this.state) return;
    if (state === 'hidden') {
      var wasVisible = this.state !== 'hidden';
      this.state = 'hidden';
      this.host.dataset.state = 'hidden';
      this.pill.setAttribute('aria-hidden', 'true');
      global.clearTimeout(this.enterTimer);
      this.enterTimer = null;
      this.pill.classList.remove('is-entering');
      this.pill.classList.remove('is-visible');

      if (wasVisible) {
        this.pill.classList.add('is-exiting');
      }

      global.clearTimeout(this.transitionTimer);
      global.clearTimeout(this.exitTimer);
      this.exitTimer = global.setTimeout(function () {
        this.pill.classList.remove('is-exiting');
        if (this.state === 'hidden') this._stopLoop();
        this.exitTimer = null;
      }.bind(this), EXIT_MS);
      return;
    }

    var wasHidden = this.state === 'hidden';
    var isEntrance = Boolean(options && (options.entrance || options.wake));
    this.state = state;
    this.host.dataset.state = state;
    this.pill.setAttribute('aria-label', LABELS[state]);
    this.pill.setAttribute('aria-hidden', 'false');
    this._setContent(state, wasHidden);
    this._startLoop();

    global.clearTimeout(this.exitTimer);
    this.exitTimer = null;
    this.pill.classList.remove('is-exiting');

    if (wasHidden && isEntrance) {
      global.clearTimeout(this.enterTimer);
      this.pill.classList.remove('is-entering');
      if (typeof this.pill.offsetWidth === 'number') {
        void this.pill.offsetWidth;
      }
      this.pill.classList.add('is-entering');
      this.pill.classList.add('is-visible');
      this.enterTimer = global.setTimeout(function () {
        this.pill.classList.remove('is-entering');
        this.enterTimer = null;
      }.bind(this), ENTER_MS);
    } else {
      if (!isEntrance) {
        global.clearTimeout(this.enterTimer);
        this.enterTimer = null;
        this.pill.classList.remove('is-entering');
      }
      this.pill.classList.add('is-visible');
    }
  };

  StatePill.prototype.setState = function (state, options) {
    var next = VALID_STATES[state] ? state : 'hidden';
    if (this.canaryMode) return this.state;
    this._setStateInternal(next, options);
    return this.state;
  };

  StatePill.prototype._cycleDelay = function (state) {
    return state === 'hidden' ? CYCLE_HIDDEN_MS : CYCLE_VISIBLE_MS;
  };

  StatePill.prototype._cycleTick = function () {
    if (this.canaryMode !== 'cycle') return;
    var cycle = ['listening', 'thinking', 'searching', 'hidden'];
    var state = cycle[this.cycleIndex % cycle.length];
    var isWake = (state === 'listening' && (this.cycleIndex === 0 || this.state === 'hidden'));
    this.cycleIndex += 1;
    this._setStateInternal(state, { entrance: isWake });
    this.canaryTimer = global.setTimeout(this._cycleTick, this._cycleDelay(state));
  };

  StatePill.prototype.startCanary = function (mode) {
    if (mode !== 'listening' && mode !== 'thinking' &&
        mode !== 'searching' && mode !== 'cycle') return false;
    global.clearTimeout(this.canaryTimer);
    this.canaryMode = mode;
    if (mode === 'cycle') {
      this.cycleIndex = 0;
      this._cycleTick();
    } else {
      this._setStateInternal(mode, { entrance: true });
    }
    return true;
  };

  StatePill.prototype.getStatus = function () {
    return {
      state: this.state,
      visible: this.state !== 'hidden',
      canary: this.canaryMode,
      looping: this.looping,
      canvasCount: 2,
      orbState: this.state !== 'hidden' ? ORB_STATES[this.state] : null,
      label: this.state !== 'hidden' ? LABELS[this.state] : null,
      labels: LABELS
    };
  };

  StatePill.prototype.destroy = function () {
    global.clearTimeout(this.canaryTimer);
    global.clearTimeout(this.enterTimer);
    global.clearTimeout(this.exitTimer);
    this._clearTransition();
    this._stopLoop();
    this.document.removeEventListener('visibilitychange', this._visibilityChanged);
    if (this.motionMedia) {
      if (this.motionMedia.removeEventListener) {
        this.motionMedia.removeEventListener('change', this._motionChanged);
      } else if (this.motionMedia.removeListener) {
        this.motionMedia.removeListener(this._motionChanged);
      }
    }
    if (this.pill.parentNode) this.pill.parentNode.removeChild(this.pill);
  };

  global.JarvisStatePill = {
    LABELS: LABELS,
    ORB_STATES: ORB_STATES,
    create: function (host) { return new StatePill(host); }
  };
})(window);
