/*
 * Home Jarvis — completed-physical-line speaking caption reveal.
 *
 * Gemini Live output transcription is a stream of transport deltas. Deltas do
 * not have visual meaning, so this controller keeps one logical transcript and
 * measures only the uncommitted tail with Chromium's own typography and width.
 * A line becomes visible only when a following physical line proves that it
 * is complete. The final line has two bounded exceptions: clear punctuation
 * followed by a quiet interval, or the authoritative playback drain.
 *
 * The controller still buffers before semantic SPEAKING, drains after the
 * physical playback authority ends, suppresses consecutive exact duplicates,
 * and leaves visual-answer precedence in app.js untouched.
 */
(function (global) {
  'use strict';

  var DEFAULTS = {
    maxLines: 4,
    microBatchMs: 120,
    punctuationQuietMs: 400,
    lineDurationMs: 1050,
    drainLineDurationMs: 700,
    pageHoldMs: 600,
    drainPageHoldMs: 260,
    pageFadeMs: 520,
    drainHoldMs: 720,
    exitMs: 720,
  };

  function mergeOptions(options) {
    var merged = {};
    var key;
    for (key in DEFAULTS) merged[key] = DEFAULTS[key];
    options = options || {};
    for (key in options) {
      if (Object.prototype.hasOwnProperty.call(options, key)) {
        merged[key] = options[key];
      }
    }
    return merged;
  }

  function clearTimer(timer) {
    if (timer !== null) global.clearTimeout(timer);
    return null;
  }

  function isWhitespace(value) {
    return /\s/.test(value || '');
  }

  function skipWhitespace(text, index) {
    while (index < text.length && isWhitespace(text.charAt(index))) index++;
    return index;
  }

  function hasFinalPunctuation(text) {
    var withoutTrailingSpace = text.replace(/\s+$/, '');
    return /[.?!。？！]$/.test(withoutTrailingSpace);
  }

  function CaptionReveal(host, options) {
    if (!host) throw new Error('caption paragraph host is missing');
    if (!global.document) throw new Error('caption document is missing');

    this.host = host;
    this.document = global.document;
    this.options = mergeOptions(options);
    this.reducedMotion = this.options.reducedMotion === true ||
      (this.options.reducedMotion !== false && global.matchMedia &&
       global.matchMedia('(prefers-reduced-motion: reduce)').matches);
    if (this.reducedMotion) {
      /* Micro-batching and line-completion authority remain identical. Only
         decorative motion and the drain hold become minimal. */
      this.options.lineDurationMs = 1;
      this.options.drainLineDurationMs = 1;
      this.options.pageFadeMs = 1;
      this.options.drainPageHoldMs = 0;
      this.options.drainHoldMs = 180;
      this.options.exitMs = 180;
    }

    this.measure = this.document.createElement('span');
    this.measure.className = 'caption-measure';
    this.measure.setAttribute('aria-hidden', 'true');
    if (host.parentNode) host.parentNode.appendChild(this.measure);

    /* `text` is the exact delta-concatenated transcript. `committedEnd` is
       the first UTF-16 offset that still belongs to the composing tail. */
    this.text = '';
    this.pageStart = 0;
    this.committedEnd = 0;
    this.pageLineCount = 0;
    this.pagesShown = 0;

    this.pageElement = null;
    this.nextPageStart = null;
    this.nextPageCommit = null;
    this.forcedCommit = null;
    this.lineRevealTimers = [];

    this.speaking = false;
    this.draining = false;
    this.awaitingNewResponse = false;
    this.lastChunk = null;
    this.lastChunkLength = 0;

    this.microBatchTimer = null;
    this.punctuationTimer = null;
    this.pageTimer = null;
    this.pageFadeTimer = null;
    this.clearTimer = null;
  }

  CaptionReveal.prototype._setVisible = function (visible) {
    var textHost = this.host.parentNode;
    var surface = (this.host.closest && this.host.closest('#caption-surface')) ||
                  (textHost && textHost.parentNode ? textHost.parentNode : null) ||
                  textHost;
    if (surface && surface.style && surface.style.setProperty) {
      surface.style.setProperty('--caption-opacity', visible ? '1' : '0');
      surface.style.setProperty('--scrim-opacity', visible ? '1' : '0');
    }
    if (textHost && textHost !== surface && textHost.style && textHost.style.setProperty) {
      textHost.style.setProperty('--caption-opacity', visible ? '1' : '0');
      textHost.style.setProperty('--scrim-opacity', visible ? '1' : '0');
    }
  };

  CaptionReveal.prototype._cancelLineRevealTimers = function () {
    for (var i = 0; i < this.lineRevealTimers.length; i++) {
      this.lineRevealTimers[i] = clearTimer(this.lineRevealTimers[i]);
    }
    this.lineRevealTimers = [];
  };

  CaptionReveal.prototype._cancelTimers = function () {
    this.microBatchTimer = clearTimer(this.microBatchTimer);
    this.punctuationTimer = clearTimer(this.punctuationTimer);
    this.pageTimer = clearTimer(this.pageTimer);
    this.pageFadeTimer = clearTimer(this.pageFadeTimer);
    this.clearTimer = clearTimer(this.clearTimer);
    this._cancelLineRevealTimers();
  };

  CaptionReveal.prototype._resetContent = function (preserveSpeaking) {
    this._cancelTimers();
    this.host.classList.remove('is-leaving');
    this.host.replaceChildren();
    this.measure.textContent = '';
    this._setVisible(false);

    this.text = '';
    this.pageStart = 0;
    this.committedEnd = 0;
    this.pageLineCount = 0;
    this.pagesShown = 0;
    this.pageElement = null;
    this.nextPageStart = null;
    this.nextPageCommit = null;
    this.forcedCommit = null;
    this.draining = false;
    this.awaitingNewResponse = false;
    this.lastChunk = null;
    this.lastChunkLength = 0;
    if (!preserveSpeaking) this.speaking = false;
  };

  CaptionReveal.prototype.clear = function () {
    this._resetContent(false);
  };

  CaptionReveal.prototype._linePositions = function (text) {
    var positions = [];
    var node;
    var range;
    var lastTop = null;
    var i;

    if (!text) return positions;

    /* Hidden production typography gives Range the same line breaks Chromium
       uses for the visible page. One UTF-16 character range is intentionally
       simple and works in the deterministic contract harness too. */
    this.measure.textContent = text;
    node = this.measure.firstChild;
    if (!node || !this.document.createRange) {
      return [{ start: 0, top: 0 }];
    }

    range = this.document.createRange();
    for (i = 0; i < text.length; i++) {
      range.setStart(node, i);
      range.setEnd(node, Math.min(i + 1, text.length));
      var rects = range.getClientRects();
      var rect = rects && rects[0];
      if (!rect) continue;

      var top = typeof rect.top === 'number' ? rect.top : 0;
      if (lastTop === null || Math.abs(top - lastTop) > 1.5) {
        positions.push({ start: i, top: top });
        lastTop = top;
      }
    }

    if (!positions.length) positions.push({ start: 0, top: 0 });
    return positions;
  };

  CaptionReveal.prototype._firstLineBoundary = function (tail) {
    var positions;
    var overflowIndex;
    var lastWhitespace = -1;
    var end;

    if (!tail) return null;
    positions = this._linePositions(tail);
    if (positions.length < 2) return null;

    overflowIndex = positions[1].start;
    for (var i = 0; i < overflowIndex; i++) {
      if (isWhitespace(tail.charAt(i))) lastWhitespace = i;
    }

    /* Keep the separator in the committed range, then start the next range
       after all collapsed whitespace. This preserves the exact logical text
       without manufacturing a space at a page boundary. A leading-only
       whitespace run is not a separator, so fall back to Range's boundary. */
    if (lastWhitespace > 0) {
      end = skipWhitespace(tail, lastWhitespace);
    } else {
      end = overflowIndex;
    }
    if (end <= 0) end = overflowIndex;

    return {
      end: end,
      lineEnd: overflowIndex,
      reason: 'wrap',
    };
  };

  CaptionReveal.prototype._nextCommitEnd = function (forceAll, punctuationReady) {
    var tail;
    var boundary;

    if (this.forcedCommit !== null) {
      if (this.forcedCommit.end > this.committedEnd &&
          this.forcedCommit.end <= this.text.length) {
        boundary = this.forcedCommit;
        this.forcedCommit = null;
        return boundary;
      }
      this.forcedCommit = null;
    }

    tail = this.text.slice(this.committedEnd);
    if (!tail) return null;

    boundary = this._firstLineBoundary(tail);
    if (boundary) {
      return {
        end: this.committedEnd + boundary.end,
        lineEnd: this.committedEnd + boundary.lineEnd,
      };
    }

    if (forceAll || (punctuationReady && hasFinalPunctuation(tail))) {
      return { end: this.text.length, lineEnd: this.text.length };
    }
    return null;
  };

  CaptionReveal.prototype._createPage = function () {
    if (this.pageElement) return;
    this.pageElement = this.document.createElement('span');
    this.pageElement.className = 'caption-page';
    this.host.appendChild(this.pageElement);
    this.pagesShown++;
  };

  CaptionReveal.prototype._appendCommittedLine = function (lineText) {
    var element;
    var duration;
    var enterDelay = this.reducedMotion ? 0 : 16;
    var timer;

    if (!lineText || !lineText.trim()) return;

    this._createPage();
    element = this.document.createElement('span');
    element.className = 'caption-committed-line';
    element.textContent = lineText;
    duration = this.draining
      ? Math.max(1, Number(this.options.drainLineDurationMs) || 700)
      : Math.max(1, Number(this.options.lineDurationMs) || 1050);
    element.style.setProperty('--caption-line-duration', duration + 'ms');
    this.pageElement.appendChild(element);
    this.pageLineCount++;
    this._setVisible(true);

    timer = global.setTimeout(function () {
      var index = this.lineRevealTimers.indexOf(timer);
      if (index !== -1) this.lineRevealTimers.splice(index, 1);
      if (element.parentNode === this.pageElement) {
        element.classList.add('is-revealed');
      }
    }.bind(this), enterDelay);
    this.lineRevealTimers.push(timer);
  };

  CaptionReveal.prototype._commitThrough = function (end, lineEnd) {
    var lineText;
    if (end <= this.committedEnd) return false;
    lineText = this.text.slice(
      this.committedEnd,
      lineEnd === undefined ? end : Math.min(lineEnd, end)
    );
    this.committedEnd = end;
    this._appendCommittedLine(lineText);
    return true;
  };

  CaptionReveal.prototype._revealPendingLines = function () {
    this._cancelLineRevealTimers();
    if (!this.pageElement) return;
    for (var i = 0; i < this.pageElement.children.length; i++) {
      this.pageElement.children[i].classList.add('is-revealed');
    }
  };

  CaptionReveal.prototype._schedulePunctuation = function () {
    var tail;
    var positions;
    if (!this.speaking || this.punctuationTimer !== null ||
        this.pageTimer !== null || this.pageFadeTimer !== null ||
        this.committedEnd >= this.text.length) return;

    tail = this.text.slice(this.committedEnd);
    positions = this._linePositions(tail);
    if (positions.length !== 1 || !hasFinalPunctuation(tail)) return;
    this.punctuationTimer = global.setTimeout(function () {
      this.punctuationTimer = null;
      this._processComposition(false, true);
    }.bind(this), Math.max(0, Number(this.options.punctuationQuietMs) || 0));
  };

  CaptionReveal.prototype._scheduleClear = function () {
    var delay;
    if (this.clearTimer !== null || this.pageTimer !== null ||
        this.pageFadeTimer !== null || this.microBatchTimer !== null ||
        this.punctuationTimer !== null || this.committedEnd < this.text.length) {
      return;
    }

    if (!this.text || !this.pageElement) {
      this._resetContent(false);
      this.awaitingNewResponse = true;
      return;
    }

    delay = Math.max(0, Number(this.options.drainHoldMs) || 0);
    this.clearTimer = global.setTimeout(function () {
      this.clearTimer = null;
      this.host.classList.add('is-leaving');
      this._setVisible(false);
      this.clearTimer = global.setTimeout(function () {
        this._resetContent(false);
        this.awaitingNewResponse = true;
      }.bind(this), Math.max(0, Number(this.options.exitMs) || 0));
    }.bind(this), delay);
  };

  CaptionReveal.prototype._schedulePage = function (nextStart, nextCommit) {
    var delay;
    if (this.pageTimer !== null || this.pageFadeTimer !== null) return;
    if (nextStart === undefined || nextStart === null ||
        nextStart <= this.pageStart && nextStart <= this.committedEnd) return;

    this.nextPageStart = nextStart;
    this.nextPageCommit = nextCommit === undefined ? null : nextCommit;
    delay = this.draining
      ? Math.max(0, Number(this.options.drainPageHoldMs) || 0)
      : Math.max(0, Number(this.options.pageHoldMs) || 0);
    this.pageTimer = global.setTimeout(function () {
      this.pageTimer = null;
      this.host.classList.add('is-leaving');
      this._setVisible(false);
      this.pageFadeTimer = global.setTimeout(function () {
        var nextStartValue = this.nextPageStart;
        var nextCommitValue = this.nextPageCommit;
        this.pageFadeTimer = null;
        this._cancelLineRevealTimers();
        this.host.replaceChildren();
        this.host.classList.remove('is-leaving');
        this.pageStart = nextStartValue === null ? this.committedEnd : nextStartValue;
        this.committedEnd = this.pageStart;
        this.pageLineCount = 0;
        this.pageElement = null;
        this.nextPageStart = null;
        this.nextPageCommit = null;
        this.forcedCommit = nextCommitValue;
        this._processComposition(this.draining, false);
      }.bind(this), Math.max(0, Number(this.options.pageFadeMs) || 0));
    }.bind(this), delay);
  };

  CaptionReveal.prototype._processComposition = function (forceAll, punctuationReady) {
    var maxLines = Math.max(1, Number(this.options.maxLines) || 4);
    var nextEnd;
    var pendingEnd;

    if (!this.text || (!this.speaking && !this.draining)) return;
    if (this.pageTimer !== null || this.pageFadeTimer !== null ||
        this.clearTimer !== null) return;

    while (this.committedEnd < this.text.length &&
           this.pageLineCount < maxLines) {
      nextEnd = this._nextCommitEnd(Boolean(forceAll), Boolean(punctuationReady));
      if (nextEnd === null || nextEnd.end <= this.committedEnd) break;
      this._commitThrough(nextEnd.end, nextEnd.lineEnd);
    }

    if (this.committedEnd < this.text.length &&
        this.pageLineCount >= maxLines) {
      /* The next line must remain composing on the current page. A page
         transition starts at its cursor and carries one already-safe boundary
         across so punctuation-only final lines can appear on page two. */
      pendingEnd = this._nextCommitEnd(Boolean(forceAll), Boolean(punctuationReady));
      if (pendingEnd !== null && pendingEnd.end > this.committedEnd) {
        this._schedulePage(this.committedEnd, pendingEnd);
      } else if (!forceAll && !punctuationReady) {
        this._schedulePunctuation();
      }
    } else if (this.committedEnd < this.text.length && !forceAll &&
               !punctuationReady) {
      this._schedulePunctuation();
    } else if (this.committedEnd >= this.text.length && this.draining) {
      this._scheduleClear();
    }
  };

  CaptionReveal.prototype._scheduleMicroBatch = function () {
    if (this.microBatchTimer !== null || this.pageTimer !== null ||
        this.pageFadeTimer !== null) return;
    this.microBatchTimer = global.setTimeout(function () {
      this.microBatchTimer = null;
      this._processComposition(false, false);
    }.bind(this), Math.max(0, Number(this.options.microBatchMs) || 0));
  };

  CaptionReveal.prototype.push = function (chunk) {
    if (typeof chunk !== 'string' || chunk.length === 0) return;

    if (this.awaitingNewResponse || this.draining) {
      this._resetContent(this.speaking);
    }

    /* A reconnect or duplicated SSE delivery must not print the same delta
       twice. This remains consecutive/exact suppression: a repeated phrase
       separated by another delta is valid transcription. */
    if (chunk === this.lastChunk && this.text.length === this.lastChunkLength) {
      return;
    }

    this.text += chunk;
    this.lastChunk = chunk;
    this.lastChunkLength = this.text.length;
    this.awaitingNewResponse = false;
    this.punctuationTimer = clearTimer(this.punctuationTimer);

    if (this.speaking) this._scheduleMicroBatch();
  };

  CaptionReveal.prototype.setSpeaking = function (speaking) {
    speaking = Boolean(speaking);
    if (speaking) {
      if (this.awaitingNewResponse || this.draining) this._resetContent(true);
      this.speaking = true;
      this.draining = false;
      this.microBatchTimer = clearTimer(this.microBatchTimer);
      this.punctuationTimer = clearTimer(this.punctuationTimer);
      this._processComposition(false, false);
      return;
    }

    if (!this.speaking) return;
    this.speaking = false;
    this.draining = true;
    this.awaitingNewResponse = true;
    this.microBatchTimer = clearTimer(this.microBatchTimer);
    this.punctuationTimer = clearTimer(this.punctuationTimer);

    /* A speaking-time page hold is no longer allowed to delay the drain. The
       force-all pass will preserve its measured cursor and schedule the next
       page using the shorter drain hold. */
    if (this.pageTimer !== null && this.pageFadeTimer === null) {
      this.pageTimer = clearTimer(this.pageTimer);
      this.nextPageStart = null;
      this.nextPageCommit = null;
    }
    this._processComposition(true, false);
    this._revealPendingLines();

    if (this.committedEnd >= this.text.length &&
        this.pageTimer === null && this.pageFadeTimer === null) {
      this._scheduleClear();
    }
  };

  CaptionReveal.prototype.status = function () {
    var pageLines = this.pageElement ? this.pageElement.children.length : 0;
    return {
      speaking: this.speaking,
      draining: this.draining,
      textLength: this.text.length,
      transcript: this.text,
      pageStart: this.pageStart,
      committedEnd: this.committedEnd,
      pageLineCount: this.pageLineCount,
      pagesShown: this.pagesShown,
      domPages: this.host.children ? this.host.children.length : 0,
      domLines: pageLines,
      composingTextLength: Math.max(0, this.text.length - this.committedEnd),
      pendingTextLength: Math.max(0, this.text.length - this.committedEnd),
      composingVisible: false,
      reducedMotion: this.reducedMotion,
      batchTimerActive: this.microBatchTimer !== null,
      punctuationTimerActive: this.punctuationTimer !== null,
      hasActiveTimer: this.microBatchTimer !== null || this.punctuationTimer !== null ||
        this.pageTimer !== null || this.pageFadeTimer !== null ||
        this.clearTimer !== null || this.lineRevealTimers.length > 0,
    };
  };

  global.JarvisCaptionReveal = {
    create: function (host, options) {
      return new CaptionReveal(host, options);
    },
  };
}(typeof window !== 'undefined' ? window : globalThis));
