/*
 * WakeWaveSurface
 *
 * Explicit SVG rollback/debug surface for the Gemini Live entry moment.
 * Production uses the raw WebGL sine-ripple adapter instead. This legacy
 * adapter remains framework-free and never uploads or replaces a photo; it
 * applies one SVG displacement filter to the existing visual root so the
 * photo, caption, and full-screen surface move as one material.
 */
(function (global) {
  'use strict';

  var DURATION_MS = 900;
  var ATTACK_MS = 300;
  var PEAK_SCALE = 26;
  var CONTINUOUS_STRENGTH = 0.72;
  var BASE_FREQUENCY_X = 0.006;
  var BASE_FREQUENCY_Y = 0.010;

  function clamp01(value) {
    return Math.max(0, Math.min(1, value));
  }

  function smoothstep(value) {
    var t = clamp01(value);
    return t * t * (3 - 2 * t);
  }

  function transitionStrengthAt(elapsedMs) {
    if (elapsedMs <= 0) return 0;
    if (elapsedMs < ATTACK_MS) {
      var attack = elapsedMs / ATTACK_MS;
      return smoothstep(attack * attack);
    }
    if (elapsedMs >= DURATION_MS) return 0;
    var decay = (elapsedMs - ATTACK_MS) / (DURATION_MS - ATTACK_MS);
    return 1 - smoothstep(decay);
  }

  function setAttribute(node, name, value) {
    if (node && node.setAttribute) node.setAttribute(name, String(value));
  }

  function WakeWaveSurface(root, options) {
    var doc = global.document || document;
    var settings = options || {};

    if (!root) throw new Error('wake wave visual root is missing');

    this.root = root;
    this.document = doc;
    this.displacement = doc.getElementById('jarvis-wake-wave-displacement');
    this.offset = doc.getElementById('jarvis-wake-wave-offset');
    this.noise = doc.getElementById('jarvis-wake-wave-noise');
    this.continuous = Boolean(settings.continuous);
    this.enabled = false;
    this.playing = false;
    this.transitionStrength = 0;
    this.playStartedAt = null;
    this.waveLastTrigger = null;
    this.frameId = 0;

    if (!this.displacement || !this.offset || !this.noise) {
      throw new Error('wake wave SVG filter primitives are missing');
    }

    this._render = this._render.bind(this);
    this._visibilityChanged = this._visibilityChanged.bind(this);
    doc.addEventListener('visibilitychange', this._visibilityChanged);
    this._resetField();
  }

  WakeWaveSurface.prototype._setActiveClass = function (active) {
    if (!this.root.classList) return;
    if (active) {
      this.root.classList.add('is-wake-wave');
    } else {
      this.root.classList.remove('is-wake-wave');
    }
  };

  WakeWaveSurface.prototype._resetField = function () {
    setAttribute(this.displacement, 'scale', 0);
    setAttribute(this.offset, 'dx', 0);
    setAttribute(this.offset, 'dy', 0);
    setAttribute(this.noise, 'baseFrequency',
      BASE_FREQUENCY_X + ' ' + BASE_FREQUENCY_Y);
  };

  WakeWaveSurface.prototype._applyField = function (timestamp, strength) {
    var time = timestamp * 0.001;
    var scale = strength * PEAK_SCALE;
    var driftX = Math.sin(time * 0.72) * 18 + Math.sin(time * 0.31) * 7;
    var driftY = Math.cos(time * 0.58) * 14 + Math.sin(time * 0.27) * 5;
    var frequencyX = BASE_FREQUENCY_X + Math.sin(time * 0.34) * 0.0007;
    var frequencyY = BASE_FREQUENCY_Y + Math.cos(time * 0.29) * 0.0009;

    setAttribute(this.displacement, 'scale', scale.toFixed(3));
    setAttribute(this.offset, 'dx', (driftX * strength).toFixed(3));
    setAttribute(this.offset, 'dy', (driftY * strength).toFixed(3));
    setAttribute(this.noise, 'baseFrequency',
      frequencyX.toFixed(5) + ' ' + frequencyY.toFixed(5));
  };

  WakeWaveSurface.prototype._stop = function () {
    if (this.frameId && global.cancelAnimationFrame) {
      global.cancelAnimationFrame(this.frameId);
    }
    this.frameId = 0;
  };

  WakeWaveSurface.prototype._start = function () {
    if (!this.enabled || this.frameId || this.document.hidden) return;
    if (!global.requestAnimationFrame) return;
    this.frameId = global.requestAnimationFrame(this._render);
  };

  WakeWaveSurface.prototype._finish = function () {
    this.playing = false;
    this.enabled = false;
    this.transitionStrength = 0;
    this.playStartedAt = null;
    this._stop();
    this._applyField(0, 0);
    this._setActiveClass(false);
  };

  WakeWaveSurface.prototype._visibilityChanged = function () {
    if (this.document.hidden) {
      this._stop();
      return;
    }
    if (this.enabled) this._start();
  };

  WakeWaveSurface.prototype._render = function (timestamp) {
    this.frameId = 0;
    if (!this.enabled || this.document.hidden) return;

    if (this.playing) {
      if (this.playStartedAt === null) this.playStartedAt = timestamp;
      var elapsed = timestamp - this.playStartedAt;
      this.transitionStrength = transitionStrengthAt(elapsed);
      if (elapsed >= DURATION_MS) {
        this._finish();
        return;
      }
    } else {
      this.transitionStrength = CONTINUOUS_STRENGTH;
    }

    this._applyField(timestamp, this.transitionStrength);
    this._start();
  };

  WakeWaveSurface.prototype.setEnabled = function (enabled) {
    if (enabled) {
      this.enabled = true;
      this.playing = false;
      this.playStartedAt = null;
      this.transitionStrength = CONTINUOUS_STRENGTH;
      this._setActiveClass(true);
      this._start();
      return;
    }
    this._finish();
  };

  WakeWaveSurface.prototype.play = function () {
    this.waveLastTrigger = Date.now();
    this.enabled = true;
    this.playing = true;
    this.transitionStrength = 0;
    this.playStartedAt = null;
    this._setActiveClass(true);
    this._applyField(0, 0);
    this._start();
    return true;
  };

  WakeWaveSurface.prototype.getStatus = function () {
    return {
      enabled: this.enabled,
      running: Boolean(this.frameId),
      wavePlaying: this.playing,
      waveStrength: this.playing ? this.transitionStrength :
        (this.enabled ? CONTINUOUS_STRENGTH : 0),
      waveLastTrigger: this.waveLastTrigger,
      durationMs: DURATION_MS,
      attackMs: ATTACK_MS,
      peakScale: PEAK_SCALE,
      renderer: 'svg-displacement-screen'
    };
  };

  WakeWaveSurface.prototype.dispose = function () {
    this._finish();
    this.document.removeEventListener('visibilitychange', this._visibilityChanged);
  };

  global.WakeWaveSurface = {
    DURATION_MS: DURATION_MS,
    ATTACK_MS: ATTACK_MS,
    PEAK_SCALE: PEAK_SCALE,
    CONTINUOUS_STRENGTH: CONTINUOUS_STRENGTH,
    transitionStrengthAt: transitionStrengthAt,
    create: function (root, options) {
      return new WakeWaveSurface(root, options);
    }
  };
})(window);
