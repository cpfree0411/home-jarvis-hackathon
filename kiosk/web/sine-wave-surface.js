/*
 * SineWaveSurface
 *
 * Raw WebGL wake surface used by the canonical production sine-ripple path and
 * its visual tuning canaries. It deliberately owns no gallery scheduling and
 * only runs when app.js selects a debug mode or starts the Live-entry wake.
 */
(function (global) {
  'use strict';

  var DURATION_MS = 900;
  var ATTACK_MS = 300;
  var RELEASE_MS = 160;
  var PRODUCTION_MODE = 'sine-ripple';

  var PRESETS = {
    'sine-soft': {
      wave1Frequency: 6.2,
      wave2Frequency: 5.4,
      wave3Frequency: 7.0,
      wave1Speed: 0.68,
      wave2Speed: -0.50,
      wave3Speed: 0.38,
      wave1Direction: [0.82, 0.31],
      wave2Direction: [-0.22, 0.98],
      wave3Direction: [0.62, -0.76],
      wave1Phase: 0.0,
      wave2Phase: 1.7,
      wave3Phase: -0.9,
      amplitudeX: 0.018,
      amplitudeY: 0.014,
      duration: DURATION_MS,
      attack: ATTACK_MS
    },
    'sine-wave': {
      wave1Frequency: 7.4,
      wave2Frequency: 6.5,
      wave3Frequency: 8.2,
      wave1Speed: 0.85,
      wave2Speed: -0.62,
      wave3Speed: 0.48,
      wave1Direction: [0.82, 0.31],
      wave2Direction: [-0.22, 0.98],
      wave3Direction: [0.62, -0.76],
      wave1Phase: 0.0,
      wave2Phase: 1.7,
      wave3Phase: -0.9,
      amplitudeX: 0.026,
      amplitudeY: 0.020,
      duration: DURATION_MS,
      attack: ATTACK_MS
    },
    'sine-ripple': {
      wave1Frequency: 22.0,
      wave2Frequency: 28.0,
      wave3Frequency: 34.0,
      wave1Speed: 7.2,
      wave2Speed: -8.4,
      wave3Speed: 6.4,
      wave1Direction: [0.82, 0.31],
      wave2Direction: [-0.22, 0.98],
      wave3Direction: [0.62, -0.76],
      wave1Phase: 0.0,
      wave2Phase: 1.7,
      wave3Phase: -0.9,
      amplitudeX: 0.0055,
      amplitudeY: 0.0038,
      duration: 430,
      attack: 70
    }
  };

  var VERTEX_SHADER = [
    'attribute vec2 aPosition;',
    'attribute vec2 aUv;',
    'varying vec2 vUv;',
    '',
    'void main() {',
    '  vUv = aUv;',
    '  gl_Position = vec4(aPosition, 0.0, 1.0);',
    '}'
  ].join('\n');

  var FRAGMENT_SHADER = [
    'precision mediump float;',
    '',
    'uniform sampler2D uTexture;',
    'uniform float uTime;',
    'uniform float uStrength;',
    'uniform vec2 uViewportResolution;',
    'uniform vec2 uImageResolution;',
    'uniform vec2 uWave1Direction;',
    'uniform vec2 uWave2Direction;',
    'uniform vec2 uWave3Direction;',
    'uniform float uWave1Frequency;',
    'uniform float uWave2Frequency;',
    'uniform float uWave3Frequency;',
    'uniform float uWave1Speed;',
    'uniform float uWave2Speed;',
    'uniform float uWave3Speed;',
    'uniform float uWave1Phase;',
    'uniform float uWave2Phase;',
    'uniform float uWave3Phase;',
    'uniform vec2 uAmplitude;',
    '',
    'varying vec2 vUv;',
    '',
    'vec2 coverUv(vec2 uv) {',
    '  float viewportAspect = uViewportResolution.x / uViewportResolution.y;',
    '  float imageAspect = uImageResolution.x / uImageResolution.y;',
    '  vec2 crop = vec2(1.0);',
    '',
    '  if (viewportAspect > imageAspect) {',
    '    crop.y = imageAspect / viewportAspect;',
    '  } else {',
    '    crop.x = viewportAspect / imageAspect;',
    '  }',
    '',
    '  return (uv - 0.5) * crop + 0.5;',
    '}',
    '',
    'void main() {',
    '  vec2 centeredUv = vUv - 0.5;',
    '',
    '  // Three directional sine fields. There is intentionally no',
    '  // turbulence/noise field: the visual identity is coherent water-like',
    '  // refraction, not random crumpling or paper deformation.',
    '  float wave1 = sin(dot(centeredUv, uWave1Direction) * uWave1Frequency',
    '    + uTime * uWave1Speed + uWave1Phase);',
    '  float wave2 = sin(dot(centeredUv, uWave2Direction) * uWave2Frequency',
    '    + uTime * uWave2Speed + uWave2Phase);',
    '  float wave3 = sin(dot(centeredUv, uWave3Direction) * uWave3Frequency',
    '    + uTime * uWave3Speed + uWave3Phase);',
    '',
    '  vec2 offset = vec2(',
    '    wave1 + wave2 * 0.45,',
    '    wave2 + wave3 * 0.35',
    '  ) * uAmplitude * uStrength;',
    '',
    '  // Keep the original cover crop and clamp the final sample to the',
    '  // texture edge. CLAMP_TO_EDGE plus this inset avoids black seams when',
    '  // a wave reaches the outermost source texel.',
    '  vec2 sampleUv = clamp(coverUv(vUv + offset), vec2(0.001), vec2(0.999));',
    '  gl_FragColor = texture2D(uTexture, sampleUv);',
    '}'
  ].join('\n');

  function clone(value) {
    if (Array.isArray(value)) return value.slice();
    return value;
  }

  function settingsFor(mode, overrides) {
    var base = PRESETS[mode] || PRESETS['sine-soft'];
    var source = overrides || {};
    var settings = {};
    Object.keys(base).forEach(function (key) {
      settings[key] = source[key] !== undefined ? clone(source[key]) : clone(base[key]);
    });
    return settings;
  }

  function clamp01(value) {
    return Math.max(0, Math.min(1, value));
  }

  function smoothstep(value) {
    var t = clamp01(value);
    return t * t * (3 - 2 * t);
  }

  function envelopeAt(elapsedMs, settings) {
    var duration = settings.duration;
    var attackMs = settings.attack;
    if (elapsedMs <= 0) return 0;
    if (elapsedMs < attackMs) {
      var attack = elapsedMs / attackMs;
      return smoothstep(attack * attack);
    }
    if (elapsedMs >= duration) return 0;
    var decay = (elapsedMs - attackMs) / (duration - attackMs);
    return 1 - smoothstep(decay);
  }

  function compileShader(gl, type, source) {
    var shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      var info = gl.getShaderInfoLog(shader) || 'unknown sine shader error';
      gl.deleteShader(shader);
      throw new Error(info);
    }
    return shader;
  }

  function createProgram(gl) {
    var vertex = compileShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
    var fragment = compileShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
    var program = gl.createProgram();
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    gl.deleteShader(vertex);
    gl.deleteShader(fragment);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      var info = gl.getProgramInfoLog(program) || 'unknown sine program error';
      gl.deleteProgram(program);
      throw new Error(info);
    }
    return program;
  }

  function setUniforms(gl, program, settings) {
    return {
      texture: gl.getUniformLocation(program, 'uTexture'),
      time: gl.getUniformLocation(program, 'uTime'),
      strength: gl.getUniformLocation(program, 'uStrength'),
      viewport: gl.getUniformLocation(program, 'uViewportResolution'),
      image: gl.getUniformLocation(program, 'uImageResolution'),
      wave1Direction: gl.getUniformLocation(program, 'uWave1Direction'),
      wave2Direction: gl.getUniformLocation(program, 'uWave2Direction'),
      wave3Direction: gl.getUniformLocation(program, 'uWave3Direction'),
      wave1Frequency: gl.getUniformLocation(program, 'uWave1Frequency'),
      wave2Frequency: gl.getUniformLocation(program, 'uWave2Frequency'),
      wave3Frequency: gl.getUniformLocation(program, 'uWave3Frequency'),
      wave1Speed: gl.getUniformLocation(program, 'uWave1Speed'),
      wave2Speed: gl.getUniformLocation(program, 'uWave2Speed'),
      wave3Speed: gl.getUniformLocation(program, 'uWave3Speed'),
      wave1Phase: gl.getUniformLocation(program, 'uWave1Phase'),
      wave2Phase: gl.getUniformLocation(program, 'uWave2Phase'),
      wave3Phase: gl.getUniformLocation(program, 'uWave3Phase'),
      amplitude: gl.getUniformLocation(program, 'uAmplitude')
    };
  }

  function SineWaveSurface(canvas, mode, overrides) {
    this.canvas = canvas;
    this.stage = canvas && canvas.parentElement;
    this.mode = PRESETS[mode] ? mode : 'sine-soft';
    this.settings = settingsFor(this.mode, overrides);
    this.gl = null;
    this.program = null;
    this.uniforms = null;
    this.texture = null;
    this.vertexBuffer = null;
    this.image = null;
    this.imageVersion = 0;
    this.pendingImage = null;
    this.pendingLoad = null;
    this.pendingError = null;
    this.hasTexture = false;
    this.imageWidth = 1;
    this.imageHeight = 1;
    this.enabled = false;
    this.playing = false;
    this.waveStrength = 0;
    this.playStartedAt = null;
    this.waveLastTrigger = null;
    this.pendingPlay = false;
    this.releaseTimer = 0;
    this.frameId = 0;
    this.resizeObserver = null;

    this._render = this._render.bind(this);
    this._resize = this._resize.bind(this);
    this._visibilityChanged = this._visibilityChanged.bind(this);
    this._init();
  }

  SineWaveSurface.prototype._init = function () {
    if (!this.canvas || !this.stage) throw new Error('sine wave canvas host is missing');

    var gl = this.canvas.getContext('webgl', {
      alpha: false,
      antialias: false,
      depth: false,
      stencil: false,
      premultipliedAlpha: false,
      preserveDrawingBuffer: false,
      powerPreference: 'low-power'
    });
    if (!gl) {
      gl = this.canvas.getContext('experimental-webgl', {
        alpha: false,
        antialias: false,
        depth: false,
        stencil: false,
        premultipliedAlpha: false,
        preserveDrawingBuffer: false
      });
    }
    if (!gl) throw new Error('WebGL is unavailable for sine canary');

    this.gl = gl;
    this.program = createProgram(gl);
    this.texture = gl.createTexture();
    this.vertexBuffer = gl.createBuffer();

    gl.useProgram(this.program);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
      -1, -1, 0, 0,
       1, -1, 1, 0,
      -1,  1, 0, 1,
       1,  1, 1, 1
    ]), gl.STATIC_DRAW);

    var position = gl.getAttribLocation(this.program, 'aPosition');
    var uv = gl.getAttribLocation(this.program, 'aUv');
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 16, 0);
    gl.enableVertexAttribArray(uv);
    gl.vertexAttribPointer(uv, 2, gl.FLOAT, false, 16, 8);

    this.uniforms = setUniforms(gl, this.program, this.settings);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    this._setStaticUniforms();

    global.addEventListener('resize', this._resize);
    global.document.addEventListener('visibilitychange', this._visibilityChanged);
    if (global.ResizeObserver) {
      this.resizeObserver = new global.ResizeObserver(this._resize);
      this.resizeObserver.observe(this.stage);
    }
    this._resize();
    if (this.stage.classList) this.stage.classList.add('is-sine-wave-host');
  };

  SineWaveSurface.prototype._setStaticUniforms = function () {
    var gl = this.gl;
    var u = this.uniforms;
    var s = this.settings;
    gl.useProgram(this.program);
    gl.uniform1i(u.texture, 0);
    gl.uniform2f(u.wave1Direction, s.wave1Direction[0], s.wave1Direction[1]);
    gl.uniform2f(u.wave2Direction, s.wave2Direction[0], s.wave2Direction[1]);
    gl.uniform2f(u.wave3Direction, s.wave3Direction[0], s.wave3Direction[1]);
    gl.uniform1f(u.wave1Frequency, s.wave1Frequency);
    gl.uniform1f(u.wave2Frequency, s.wave2Frequency);
    gl.uniform1f(u.wave3Frequency, s.wave3Frequency);
    gl.uniform1f(u.wave1Speed, s.wave1Speed);
    gl.uniform1f(u.wave2Speed, s.wave2Speed);
    gl.uniform1f(u.wave3Speed, s.wave3Speed);
    gl.uniform1f(u.wave1Phase, s.wave1Phase);
    gl.uniform1f(u.wave2Phase, s.wave2Phase);
    gl.uniform1f(u.wave3Phase, s.wave3Phase);
    gl.uniform2f(u.amplitude, s.amplitudeX, s.amplitudeY);
    gl.uniform1f(u.strength, 0);
  };

  SineWaveSurface.prototype._resize = function () {
    if (!this.gl || !this.canvas || !this.stage) return;
    var width = Math.max(1, this.stage.clientWidth || global.innerWidth || 1);
    var height = Math.max(1, this.stage.clientHeight || global.innerHeight || 1);
    if (this.canvas.width === width && this.canvas.height === height) return;
    this.canvas.width = width;
    this.canvas.height = height;
    this.gl.viewport(0, 0, width, height);
  };

  SineWaveSurface.prototype._setReady = function (ready) {
    if (!this.stage || !this.stage.classList) return;
    if (ready) this.stage.classList.add('is-sine-wave-ready');
    else this.stage.classList.remove('is-sine-wave-ready');
  };

  SineWaveSurface.prototype._setPlaying = function (playing) {
    if (!this.stage || !this.stage.classList) return;
    if (playing) this.stage.classList.add('is-sine-wave-playing');
    else this.stage.classList.remove('is-sine-wave-playing');
  };

  SineWaveSurface.prototype._setReleasing = function (releasing) {
    if (!this.stage || !this.stage.classList) return;
    if (releasing) this.stage.classList.add('is-sine-wave-releasing');
    else this.stage.classList.remove('is-sine-wave-releasing');
  };

  SineWaveSurface.prototype._clearReleaseTimer = function () {
    if (this.releaseTimer && global.clearTimeout) {
      global.clearTimeout(this.releaseTimer);
    }
    this.releaseTimer = 0;
  };

  SineWaveSurface.prototype._stop = function () {
    if (this.frameId && global.cancelAnimationFrame) {
      global.cancelAnimationFrame(this.frameId);
    }
    this.frameId = 0;
  };

  SineWaveSurface.prototype._start = function () {
    if (!this.enabled || !this.hasTexture || global.document.hidden || this.frameId) return;
    if (global.requestAnimationFrame) this.frameId = global.requestAnimationFrame(this._render);
  };

  SineWaveSurface.prototype._visibilityChanged = function () {
    if (global.document.hidden) this._stop();
    else this._start();
  };

  SineWaveSurface.prototype._deactivate = function () {
    this._clearReleaseTimer();
    this.pendingPlay = false;
    this.playing = false;
    this.enabled = false;
    this.waveStrength = 0;
    this.playStartedAt = null;
    this._stop();
    this._setPlaying(false);
    this._setReleasing(false);
    this._setReady(false);
  };

  SineWaveSurface.prototype._finish = function () {
    this.pendingPlay = false;
    this.playing = false;
    this.enabled = false;
    this.waveStrength = 0;
    this.playStartedAt = null;
    this._stop();
    this._setPlaying(false);

    if (!this.hasTexture || !global.setTimeout) {
      this._deactivate();
      return;
    }

    this._clearReleaseTimer();
    /* Keep the zero-strength canvas over the image while its opacity eases
       out. The two pixels are now the same, so the handoff is continuous. */
    this._setReleasing(true);
    var self = this;
    this.releaseTimer = global.setTimeout(function () {
      self._deactivate();
    }, RELEASE_MS);
  };

  SineWaveSurface.prototype._draw = function (timestamp) {
    var gl = this.gl;
    var u = this.uniforms;
    gl.useProgram(this.program);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.uniform1f(u.time, timestamp * 0.001);
    gl.uniform1f(u.strength, this.waveStrength);
    gl.uniform2f(u.viewport, this.canvas.width, this.canvas.height);
    gl.uniform2f(u.image, this.imageWidth, this.imageHeight);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  };

  SineWaveSurface.prototype._render = function (timestamp) {
    this.frameId = 0;
    if (!this.enabled || !this.hasTexture || global.document.hidden) return;

    this._resize();
    if (this.playing) {
      if (this.playStartedAt === null) this.playStartedAt = timestamp;
      var elapsed = timestamp - this.playStartedAt;
      this.waveStrength = envelopeAt(elapsed, this.settings);
      if (elapsed >= this.settings.duration) {
        this.waveStrength = 0;
        this._resize();
        this._draw(timestamp);
        this._finish();
        return;
      }
    } else {
      this.waveStrength = 1;
    }

    this._draw(timestamp);
    this._start();
  };

  SineWaveSurface.prototype._removePendingListeners = function () {
    if (!this.pendingImage) return;
    if (this.pendingLoad) this.pendingImage.removeEventListener('load', this.pendingLoad);
    if (this.pendingError) this.pendingImage.removeEventListener('error', this.pendingError);
    this.pendingImage = null;
    this.pendingLoad = null;
    this.pendingError = null;
  };

  SineWaveSurface.prototype._upload = function (image, version) {
    if (version !== this.imageVersion || image !== this.image) return;
    var width = image.naturalWidth || image.width;
    var height = image.naturalHeight || image.height;
    if (!width || !height) return;
    var gl = this.gl;
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
    this.imageWidth = width;
    this.imageHeight = height;
    this.hasTexture = true;
    if (this.pendingPlay) {
      this.pendingPlay = false;
      this.play();
      return;
    }
    if (this.enabled) this._setReady(true);
    this._setPlaying(this.enabled);
    this._start();
  };

  SineWaveSurface.prototype.setImage = function (image) {
    this._removePendingListeners();
    this._clearReleaseTimer();
    var pendingPlay = this.pendingPlay;
    this.imageVersion += 1;
    var version = this.imageVersion;
    this.image = image || null;
    this.hasTexture = false;
    this.pendingPlay = pendingPlay;
    this._setReleasing(false);
    this._setReady(false);
    this._setPlaying(false);
    this._stop();
    if (!image) return;

    var self = this;
    var load = function () {
      self._removePendingListeners();
      try {
        self._upload(image, version);
      } catch (error) {
        self.hasTexture = false;
        self._setReady(false);
        if (global.console && global.console.warn) {
          global.console.warn('[SineWave] image texture upload failed; using normal gallery image', error);
        }
      }
    };
    var fail = function () {
      self._removePendingListeners();
      self.hasTexture = false;
      self._setReady(false);
      self._setPlaying(false);
      self._stop();
    };

    if (image.complete && (image.naturalWidth || image.width)) {
      load();
      return;
    }
    this.pendingImage = image;
    this.pendingLoad = load;
    this.pendingError = fail;
    image.addEventListener('load', load);
    image.addEventListener('error', fail);
  };

  SineWaveSurface.prototype.setEnabled = function (enabled) {
    this.enabled = Boolean(enabled);
    if (this.enabled) {
      this._setPlaying(this.hasTexture);
      this._start();
      return;
    }
    this._finish();
  };

  SineWaveSurface.prototype.play = function () {
    this.waveLastTrigger = Date.now();
    if (!this.hasTexture) return false;
    this._clearReleaseTimer();
    this.enabled = true;
    this.playing = true;
    this.waveStrength = 0;
    this.playStartedAt = null;
    this._setReady(true);
    this._setReleasing(false);
    this._setPlaying(true);
    this._start();
    return true;
  };

  SineWaveSurface.prototype.playWhenReady = function () {
    this.waveLastTrigger = Date.now();
    if (this.hasTexture) return this.play();
    this.pendingPlay = true;
    return true;
  };

  SineWaveSurface.prototype.getStatus = function () {
    return {
      mode: this.mode,
      enabled: this.enabled,
      ready: this.hasTexture,
      running: Boolean(this.frameId),
      wavePlaying: this.playing,
      waveStrength: this.waveStrength,
      waveLastTrigger: this.waveLastTrigger,
      durationMs: this.settings.duration,
      attackMs: this.settings.attack,
      releaseMs: RELEASE_MS,
      releasing: Boolean(this.releaseTimer),
      imageWidth: this.imageWidth,
      imageHeight: this.imageHeight,
      preset: settingsFor(this.mode, this.settings),
      renderer: 'raw-webgl-directional-sine'
    };
  };

  SineWaveSurface.prototype.dispose = function () {
    this._deactivate();
    this._removePendingListeners();
    global.removeEventListener('resize', this._resize);
    global.document.removeEventListener('visibilitychange', this._visibilityChanged);
    if (this.resizeObserver) this.resizeObserver.disconnect();
    if (this.stage && this.stage.classList) this.stage.classList.remove('is-sine-wave-host');
    if (this.gl) {
      if (this.texture) this.gl.deleteTexture(this.texture);
      if (this.vertexBuffer) this.gl.deleteBuffer(this.vertexBuffer);
      if (this.program) this.gl.deleteProgram(this.program);
    }
  };

  global.SineWaveSurface = {
    DURATION_MS: DURATION_MS,
    ATTACK_MS: ATTACK_MS,
    RELEASE_MS: RELEASE_MS,
    PRODUCTION_MODE: PRODUCTION_MODE,
    PRESETS: PRESETS,
    VERTEX_SHADER: VERTEX_SHADER,
    FRAGMENT_SHADER: FRAGMENT_SHADER,
    envelopeAt: envelopeAt,
    create: function (canvas, mode, overrides) {
      return new SineWaveSurface(canvas, mode || PRODUCTION_MODE, overrides);
    }
  };
})(window);
