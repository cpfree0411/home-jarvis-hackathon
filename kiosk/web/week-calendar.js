/*
 * Home Jarvis — Weekly Calendar Visual Reaction ("seven slats").
 *
 * A temporary overlay, never a page. Seven slats sweep in over the gallery
 * when somebody asks about their week, stay for as long as they are useful —
 * a conversation ending is not a reason to leave — and fold away again when
 * swiped up or left alone long enough.
 *
 * What this file may know:
 *   - normalised events from /api/calendar and the profile binding from
 *     /api/calendar/profiles. Never a token, never an HA schema.
 *   - the overlay host contract on window.jarvisOverlays. It holds the
 *     gallery through it and never touches a slot, a video or a profile.
 *   - the mutation lifecycle that arrives over SSE. It asks the questions the
 *     server raises and answers them with the same operation_id the voice
 *     path uses. It never decides that a change happened: it shows one only
 *     after the server said so and a fresh read of the calendar agrees.
 *
 * Time: every date on this surface is a Korean date. Arithmetic is done on
 * UTC-shifted instants (Korea has no daylight saving time), so the result is
 * the same whatever zone the device itself is set to.
 */
(function () {
  'use strict';

  /* ------------------------------------------------------------- tuning */

  var KST_MS = 9 * 3600 * 1000;
  var DAY_MS = 24 * 3600 * 1000;

  // Signature entrance. The slats arrive as one gesture, not seven.
  var ENTER_STAGGER = 54;      // ms between one slat and the next
  var ENTER_FILL_MS = 660;     // a slat sweeping out of the left edge
  var ENTER_TEXT_DELAY = 150;  // type follows the slat's leading edge
  var ENTER_TEXT_MS = 420;
  var ENTER_EVENT_STEP = 38;   // each further event on a slat

  // Week turn and exit.
  var TURN_OUT_MS = 170;
  var TURN_IN_MS = 360;
  var TURN_STAGGER = 22;
  var TURN_OUT_STAGGER = 14;
  var TURN_TRAVEL = 56;
  var EXIT_STAGGER = 36;
  var EXIT_FILL_MS = 380;

  // Gesture discipline.
  var TAP_SLOP = 10;           // movement under which a touch is a tap
  var AXIS_LOCK = 14;          // movement at which an axis is decided
  var AXIS_RATIO = 1.25;       // ... and only if clearly dominant
  var LONG_PRESS_MS = 700;     // a resting finger is not a tap
  var WEEK_COMMIT_PX = 86;
  var WEEK_FLICK = 0.42;       // px/ms
  var CLOSE_COMMIT_PX = 110;
  var CLOSE_FLICK = 0.5;
  var BTN_SLOP = 14;

  // Lifetime.
  var IDLE_MS = 180000;        // left alone this long with no session: retire
  var HEARTBEAT_MS = 60000;    // keep "here" alive while the panel is up
  var DATA_TTL_MS = 120000;
  var RETRY_MS = 20000;
  var NOTE_MS = 3200;
  var RESULT_MS = 2200;
  var FAILED_MS = 4200;
  var DIFF_WINDOW_MS = 9000;   // how long a confirmed change waits for readback
  var BUSY_WAIT_MS = 2000;     // a voice open waits this long for a card to go

  // Skin change: the old print is peeled away Monday -> Sunday while the new
  // one settles in underneath, slats staying exactly where they are.
  var SKIN_STAGGER = 56;
  var SKIN_OUT_MS = 560;
  var SKIN_IN_MS = 540;
  var SKIN_FONT_WAIT_MS = 1500;

  var SKINS = ['riso', 'linen', 'moonlight', 'tape', 'ribbon'];
  var DEFAULT_SKIN = 'riso';
  /* Faces each skin needs before it may be shown, so a change never flashes
     fallback type. */
  var SKIN_FONTS = {
    riso: ['800 48px "Riso Display"', '700 18px "Jarvis Week"'],
    linen: ['360 46px "Linen Serif"', 'italic 400 14px "Linen Serif"', '700 20px "Linen Batang"', '400 13px "Linen Batang"'],
    moonlight: ['300 54px "Moonlight Serif"', 'italic 400 14px "Moonlight Serif"', '400 20px "Jarvis Week"'],
    tape: ['700 46px "Tape Hand"', '700 20px "Jarvis Week"'],
    ribbon: ['580 42px "Ribbon Serif"', '700 20px "Jarvis Week"']
  };

  var WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function monthName(iso) { return MONTHS[monthNum(iso) - 1] || ''; }
  var FOCUS_CLASSES = ['is-focus'];

  var root = document.getElementById('week-calendar');
  if (!root) return;
  var stack = root.querySelector('.wk-stack');
  var noteEl = root.querySelector('.wk-note');
  var flyEl = root.querySelector('.wk-fly');
  var toneEl = root.querySelector('.wk-tone');

  /* -------------------------------------------------------------- state */

  var state = 'closed';        // closed | opening | open | turning | closing
  var weekStart = null;        // ISO date of the Monday on screen
  var weeks = {};              // monday -> { ts, events, byDate, labels, error, partial, stale }
  var inflight = {};
  var calMeta = {};            // calendar_id -> { writable, name }
  var whoByCalendar = null;    // calendar_id -> { id, label }
  var selectedIso = null;
  var focusedEventId = null;
  var focus = null;            // { dates: {iso:1}, person, title }
  var proposal = null;
  var mutating = false;
  var askMode = null;          // null | confirm | executing | result
  var pendingDiff = null;      // { snapshot, until }
  var bars = [];
  var gesture = null;
  var pressedBtn = null;
  var listening = false;
  var openAnims = [];
  var skin = SKINS.indexOf(root.dataset.skin) >= 0 ? root.dataset.skin : DEFAULT_SKIN;
  var skinGhost = null;
  var skinSeq = 0;
  var timers = { idle: 0, heartbeat: 0, retry: 0, note: 0, result: 0, inert: 0, busy: 0, prefetch: 0 };

  /* --------------------------------------------------------- date helpers */

  function pad2(n) { return n < 10 ? '0' + n : String(n); }
  function nowMs() { return Date.now(); }
  function kstDate(ms) { return new Date(ms + KST_MS); }
  function isoOfMs(ms) {
    var d = kstDate(ms);
    return d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1) + '-' + pad2(d.getUTCDate());
  }
  function todayIso() { return isoOfMs(nowMs()); }
  function utcOfIso(iso) {
    var p = String(iso).split('-');
    return Date.UTC(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
  }
  function isoAdd(iso, days) {
    var d = new Date(utcOfIso(iso) + days * DAY_MS);
    return d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1) + '-' + pad2(d.getUTCDate());
  }
  function weekdayIndex(iso) { return (new Date(utcOfIso(iso)).getUTCDay() + 6) % 7; }
  function mondayOf(iso) { return isoAdd(iso, -weekdayIndex(iso)); }
  function isIso(s) { return typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s) && !isNaN(utcOfIso(s)); }
  function dayNum(iso) { return Number(iso.slice(8, 10)); }
  function monthNum(iso) { return Number(iso.slice(5, 7)); }
  function hm(ms) { var d = kstDate(ms); return pad2(d.getUTCHours()) + ':' + pad2(d.getUTCMinutes()); }
  function minuteOfDay(ms) { var d = kstDate(ms); return d.getUTCHours() * 60 + d.getUTCMinutes(); }
  function parseMs(s) { var t = Date.parse(s); return isNaN(t) ? null : t; }

  /* The inclusive Korean days an event touches. All-day ends are exclusive
     dates; a timed end exactly on midnight belongs to the day before. */
  function dayRange(ev) {
    if (ev.all_day) {
      var first = String(ev.start).slice(0, 10);
      var endEx = String(ev.end || '').slice(0, 10);
      if (!isIso(first)) return null;
      var last = isIso(endEx) && endEx > first ? isoAdd(endEx, -1) : first;
      return [first, last];
    }
    var s = parseMs(ev.start), e = parseMs(ev.end);
    if (s === null) return null;
    if (e === null || e <= s) e = s + 1;
    return [isoOfMs(s), isoOfMs(Math.max(s, e - 1))];
  }

  /* Stable across a date move: the adapter's id ends in the occurrence start,
     so the calendar + provider identity before it names the same event after
     it has been moved to another day. */
  function stableKey(ev) {
    var id = String(ev.id || '');
    var start = String(ev.start || '');
    if (start && id.slice(-start.length) === start) return id.slice(0, id.length - start.length - 1);
    return id;
  }

  /* ---------------------------------------------------------------- data */

  function whoOf(calendarId) {
    if (whoByCalendar && whoByCalendar[calendarId]) return whoByCalendar[calendarId];
    if (calendarId === 'birthdays') return { id: 'birthdays', label: '' };
    return { id: 'other', label: '' };
  }

  /* A calendar nobody can write to and that belongs to no person — the
     public-holiday subscription — annotates the date instead of adding
     a line of "events". */
  function isAnnotationCalendar(calendarId) {
    var meta = calMeta[calendarId];
    if (!meta || meta.writable) return false;
    return !(whoByCalendar && whoByCalendar[calendarId]);
  }

  function indexWeek(events, monday) {
    var sunday = isoAdd(monday, 6);
    var byDate = {}, labels = {};
    for (var i = 0; i < 7; i++) { byDate[isoAdd(monday, i)] = []; }
    for (var j = 0; j < events.length; j++) {
      var ev = events[j];
      var r = dayRange(ev);
      if (!r) continue;
      var first = r[0] < monday ? monday : r[0];
      var last = r[1] > sunday ? sunday : r[1];
      if (first > last) continue;
      var annotation = isAnnotationCalendar(ev.calendar_id);
      for (var iso = first, guard = 0; iso <= last && guard < 8; iso = isoAdd(iso, 1), guard++) {
        if (annotation) {
          if (!labels[iso]) labels[iso] = ev.title || '';
          continue;
        }
        byDate[iso].push({ ev: ev, iso: iso, first: r[0], last: r[1] });
      }
    }
    for (var k in byDate) byDate[k] = sortDay(dedupeDay(byDate[k]));
    return { byDate: byDate, labels: labels };
  }

  function wholeDay(entry) {
    var ev = entry.ev;
    if (ev.all_day) return true;
    if (entry.first !== entry.last) return entry.iso !== entry.first && entry.iso !== entry.last;
    var s = parseMs(ev.start), e = parseMs(ev.end);
    return s !== null && e !== null && minuteOfDay(s) === 0 && e - s >= DAY_MS - 60000;
  }

  function sortDay(list) {
    return list.sort(function (a, b) {
      var aw = wholeDay(a), bw = wholeDay(b);
      if (aw !== bw) return aw ? -1 : 1;
      if (a.ev.start !== b.ev.start) return a.ev.start < b.ev.start ? -1 : 1;
      return (a.ev.title || '') < (b.ev.title || '') ? -1 : 1;
    });
  }

  /* The same title at the same moment on two calendars is one line. */
  function dedupeDay(list) {
    var seen = {}, out = [];
    for (var i = 0; i < list.length; i++) {
      var ev = list[i].ev;
      var key = (ev.title || '') + '|' + (ev.all_day ? 'D' : parseMs(ev.start)) + '|' + whoOf(ev.calendar_id).id;
      if (seen[key]) continue;
      seen[key] = 1;
      out.push(list[i]);
    }
    return out;
  }

  function whenLabel(entry) {
    var ev = entry.ev;
    var multi = entry.first !== entry.last;
    if (wholeDay(entry)) {
      if (multi && entry.iso === entry.first) return 'All day · to ' + monthName(entry.last) + ' ' + dayNum(entry.last);
      if (multi) return 'All day · continues';
      return 'All day';
    }
    var s = parseMs(ev.start), e = parseMs(ev.end);
    if (multi && entry.iso === entry.first) return 'from ' + hm(s);
    if (multi && entry.iso === entry.last) return '~ ' + hm(e);
    return hm(s) + '–' + hm(e);
  }

  function loadProfiles(done) {
    if (whoByCalendar) { if (done) done(); return; }
    fetch('/api/calendar/profiles')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var map = {};
        ((data && data.profiles) || []).forEach(function (p) {
          if (p.kind !== 'person') return;
          (p.calendar_ids || []).forEach(function (cid) { map[cid] = { id: p.id, label: p.label || '' }; });
        });
        whoByCalendar = map;
        if (done) done();
      })
      .catch(function () { whoByCalendar = {}; if (done) done(); });
  }

  /* One bounded read per week, never per day and never while closed. */
  function loadWeek(monday, done, force) {
    var cached = weeks[monday];
    if (!force && cached && !cached.error && nowMs() - cached.ts < DATA_TTL_MS) {
      if (done) done(cached);
      return;
    }
    if (inflight[monday]) {
      if (done) inflight[monday].push(done);
      return;
    }
    inflight[monday] = done ? [done] : [];
    fetch('/api/calendar?start=' + monday + '&end=' + isoAdd(monday, 7))
      .then(function (r) { return r.json(); })
      .then(function (data) { finishLoad(monday, data); })
      .catch(function () { finishLoad(monday, null); });
  }

  function finishLoad(monday, data) {
    var waiters = inflight[monday] || [];
    delete inflight[monday];
    var rec;
    if (!data || !data.ok) {
      var prior = weeks[monday];
      rec = { ts: nowMs(), events: prior && !prior.error ? prior.events : [], error: (data && data.error) || 'unreachable' };
      if (prior && !prior.error) { rec.byDate = prior.byDate; rec.labels = prior.labels; rec.keptPrior = true; }
    } else {
      (data.calendars || []).forEach(function (c) { calMeta[c.id] = { writable: Boolean(c.writable), name: c.name || '' }; });
      var failed = Array.isArray(data.partial) ? data.partial.length > 0 : Boolean(data.partial);
      rec = { ts: nowMs(), events: data.events || [], error: null, partial: failed, stale: Boolean(data.stale) };
    }
    if (!rec.byDate) {
      var ix = indexWeek(rec.events, monday);
      rec.byDate = ix.byDate;
      rec.labels = ix.labels;
    }
    weeks[monday] = rec;
    waiters.forEach(function (fn) { try { fn(rec); } catch (e) { console.error('[Week] render failed', e); } });
  }

  function dropCache() { weeks = {}; }

  /* ------------------------------------------------------------- DOM build */

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function buildStack() {
    stack.replaceChildren();
    bars = [];
    for (var i = 0; i < 7; i++) {
      var bar = el('div', 'wk-bar');
      bar.dataset.row = String(i);
      var fill = el('div', 'wk-fill');
      var face = el('div', 'wk-face');
      var tab = el('div', 'wk-tab');
      var tabfill = el('i', 'wk-tabfill');
      var num = el('span', 'wk-num');
      var meta = el('span', 'wk-tabmeta');
      var wd = el('span', 'wk-wd');
      var sub = el('span', 'wk-sub');
      meta.appendChild(wd); meta.appendChild(sub);
      tab.appendChild(tabfill); tab.appendChild(num); tab.appendChild(meta);
      var lane = el('div', 'wk-lane');
      var evs = el('div', 'wk-evs');
      var more = el('span', 'wk-more');
      more.hidden = true;
      var ribbon = el('div', 'wk-ribbon');
      lane.appendChild(evs); lane.appendChild(more); lane.appendChild(ribbon);
      face.appendChild(tab); face.appendChild(lane);

      var ask = el('div', 'wk-ask');
      var copy = el('div', 'wk-ask-copy');
      var kicker = el('span', 'wk-ask-kicker');
      var title = el('span', 'wk-ask-title');
      var change = el('span', 'wk-ask-change');
      var from = el('span', 'wk-ask-from');
      var arrow = el('span', 'wk-ask-arrow', '→');
      var to = el('span', 'wk-ask-to');
      change.appendChild(from); change.appendChild(arrow); change.appendChild(to);
      copy.appendChild(kicker); copy.appendChild(title); copy.appendChild(change);
      var status = el('span', 'wk-ask-status');
      var actions = el('div', 'wk-ask-actions');
      var cancel = el('span', 'wk-btn', 'Cancel'); cancel.dataset.choice = 'cancel';
      var confirm = el('span', 'wk-btn', 'Change'); confirm.dataset.choice = 'confirm';
      actions.appendChild(cancel); actions.appendChild(confirm);
      ask.appendChild(copy); ask.appendChild(status); ask.appendChild(actions);
      var progress = el('div', 'wk-progress'); progress.appendChild(el('i'));

      bar.appendChild(fill); bar.appendChild(face); bar.appendChild(ask); bar.appendChild(progress);
      stack.appendChild(bar);
      bars.push({
        el: bar, fill: fill, face: face, tab: tab, tabfill: tabfill, num: num, wd: wd, sub: sub,
        lane: lane, evs: evs, more: more, ribbon: ribbon,
        ask: { root: ask, kicker: kicker, title: title, change: change, from: from, to: to,
               status: status, confirm: confirm },
        iso: null
      });
    }
  }

  /* ---------------------------------------------------------------- render */

  function weekRecord() { return weekStart ? weeks[weekStart] : null; }

  function renderWeek() {
    var rec = weekRecord();
    var today = todayIso();
    for (var i = 0; i < 7; i++) renderBar(bars[i], isoAdd(weekStart, i), rec, today);
    layoutBars();
    renderStatus(rec);
    if (focusedEventId && rec && !rec.error && !findEntry(focusedEventId)) {
      // Changed or removed somewhere else: the screen must not keep pointing
      // at something that is no longer there.
      focusedEventId = null;
      pushContext();
    }
  }

  function renderBar(b, iso, rec, today) {
    b.iso = iso;
    var e = b.el;
    e.dataset.date = iso;
    var wdx = weekdayIndex(iso);
    var label = rec && rec.labels ? rec.labels[iso] : '';
    e.classList.toggle('is-sat', wdx === 5);
    e.classList.toggle('is-sun', wdx === 6);
    e.classList.toggle('is-holiday', Boolean(label));
    e.classList.toggle('is-today', iso === today);
    e.classList.toggle('is-past', iso < today);
    e.classList.toggle('is-selected', iso === selectedIso);
    e.classList.toggle('is-focus', Boolean(focus && focus.dates[iso]));

    b.num.textContent = String(dayNum(iso));
    b.wd.textContent = WEEKDAYS[wdx];
    var sub = '';
    if (label) sub = label;
    else if (iso === today) sub = 'Today';
    else if (wdx === 0 || dayNum(iso) === 1) sub = monthName(iso);
    b.sub.textContent = sub;

    var frag = document.createDocumentFragment();
    var ribbon = document.createDocumentFragment();
    var list = rec && rec.byDate ? (rec.byDate[iso] || []) : [];
    if (!rec) {
      frag.appendChild(el('span', 'wk-empty', ''));
    } else if (rec.error && !rec.keptPrior) {
      frag.appendChild(el('span', 'wk-empty is-error', i18nError(iso)));
    } else if (!list.length) {
      frag.appendChild(el('span', 'wk-empty', 'Nothing planned'));
    } else {
      for (var j = 0; j < list.length; j++) {
        frag.appendChild(entryNode(list[j]));
        var seg = ribbonSegment(list[j]);
        if (seg) ribbon.appendChild(seg);
      }
    }
    if (iso === today) {
      var now = el('b');
      now.style.left = (minuteOfDay(nowMs()) / 1440 * 100).toFixed(2) + '%';
      ribbon.appendChild(now);
    }
    b.evs.replaceChildren(frag);
    b.ribbon.replaceChildren(ribbon);
  }

  function i18nError(iso) {
    return weekdayIndex(iso) === 3 ? 'Could not read the calendar · retrying shortly' : '';
  }

  function entryNode(entry) {
    var ev = entry.ev;
    var who = whoOf(ev.calendar_id);
    var n = el('div', 'wk-ev');
    n.dataset.eventId = ev.id;
    n.dataset.key = stableKey(ev);
    n.dataset.who = who.id;
    if (ev.id === focusedEventId) n.classList.add('is-focused');
    if (focus && focus.dates[entry.iso] && focusMatches(ev)) n.classList.add('is-focus');

    var when = el('span', 'wk-ev-when');
    when.appendChild(el('i', 'wk-ev-mark'));
    when.appendChild(document.createTextNode(whenLabel(entry)));
    if (who.label) when.appendChild(el('span', 'wk-ev-who', who.label));
    var recurring = ev.source_ref && ev.source_ref.recurring;
    if (recurring) when.appendChild(el('span', 'wk-ev-flag', 'Repeats'));
    if (!ev.writable) when.appendChild(el('span', 'wk-ev-flag', 'Read-only'));
    n.appendChild(when);
    n.appendChild(el('span', 'wk-ev-title', ev.title || '(Untitled)'));
    return n;
  }

  function ribbonSegment(entry) {
    var ev = entry.ev;
    var a = 0, z = 1440;
    if (!wholeDay(entry)) {
      var s = parseMs(ev.start), e = parseMs(ev.end);
      if (entry.iso === entry.first || entry.first === entry.last) a = minuteOfDay(s);
      if (entry.iso === entry.last || entry.first === entry.last) z = isoOfMs(e) !== entry.iso ? 1440 : minuteOfDay(e);
      if (z <= a) z = Math.min(1440, a + 15);
    }
    var seg = el('i');
    seg.dataset.who = whoOf(ev.calendar_id).id;
    seg.style.left = (a / 1440 * 100).toFixed(2) + '%';
    seg.style.width = Math.max(0.6, (z - a) / 1440 * 100).toFixed(2) + '%';
    return seg;
  }

  function focusMatches(ev) {
    if (!focus) return false;
    if (focus.person && whoOf(ev.calendar_id).id !== focus.person) return false;
    if (focus.title && (ev.title || '').toLowerCase().indexOf(focus.title.toLowerCase()) < 0) return false;
    return Boolean(focus.person || focus.title);
  }

  function renderStatus(rec) {
    root.classList.toggle('has-focus', Boolean(focus));
    if (rec && rec.error) scheduleRetry();
    if (rec && rec.error && rec.keptPrior) showNote('Could not refresh · showing the previous copy', true);
    else if (rec && rec.partial) showNote('Some calendars could not be read', true);
  }

  /* --------------------------------------------------------- lane fitting */

  /* A slat shows what fits, in order, and says how many more there are.
     Measured once per render, never per frame. */
  function fitAll() {
    for (var i = 0; i < bars.length; i++) fitBar(bars[i]);
  }

  function fitBar(b) {
    var items = b.evs.children;
    var entries = [];
    for (var i = 0; i < items.length; i++) {
      if (items[i].classList.contains('wk-ev')) { items[i].hidden = false; entries.push(items[i]); }
    }
    b.more.hidden = true;
    if (!entries.length) return;
    var open = b.el.classList.contains('is-open');
    var limit = b.evs.clientWidth;
    var hiddenCount = 0;
    if (!open) {
      var moreW = 64;
      var base = b.evs.getBoundingClientRect().left;
      for (var k = 0; k < entries.length; k++) {
        var r = entries[k].getBoundingClientRect();
        var right = r.right - base - 11;
        var reserve = k < entries.length - 1 ? moreW : 0;
        if (right > limit - reserve && k > 0) {
          for (var m = k; m < entries.length; m++) { entries[m].hidden = true; hiddenCount++; }
          break;
        }
      }
    } else {
      // Wrapped: drop from the end until the block fits the slat's height.
      var guard = entries.length;
      while (b.evs.scrollHeight > b.evs.clientHeight + 2 && guard-- > 1) {
        entries[entries.length - 1 - hiddenCount].hidden = true;
        hiddenCount++;
      }
    }
    if (hiddenCount) {
      b.more.textContent = '+' + hiddenCount;
      b.more.hidden = false;
    }
    // Whether the day needs more room is only ever judged on one line.
    if (!open) b.needsRoom = hiddenCount > 0;
  }

  /* Measure every slat on one line, give the room to the day that needs it,
     then fit that day again wrapped — once now and once the rows settle. */
  var refitTimer = 0;
  function layoutBars() {
    for (var i = 0; i < bars.length; i++) bars[i].el.classList.remove('is-open');
    fitAll();
    applyRows();
    for (var j = 0; j < bars.length; j++) if (bars[j].el.classList.contains('is-open')) fitBar(bars[j]);
    window.clearTimeout(refitTimer);
    refitTimer = window.setTimeout(function () {
      if (!isOpen()) return;
      for (var k = 0; k < bars.length; k++) if (bars[k].el.classList.contains('is-open')) fitBar(bars[k]);
    }, 380);
  }

  /* An opened day — selected with more than fits, or asking a question —
     takes the room it needs; the other six give it up evenly and keep their
     order. Nothing jumps: the rows interpolate. */
  function applyRows() {
    var openRow = -1;
    for (var i = 0; i < bars.length; i++) {
      var b = bars[i];
      var wantsOpen = Boolean(b.el.dataset.ask) || (b.iso === selectedIso && Boolean(b.needsRoom));
      b.el.classList.toggle('is-open', wantsOpen);
      if (wantsOpen && openRow < 0) openRow = i;
    }
    var rows = [];
    for (var j = 0; j < 7; j++) rows.push(j === openRow ? '2.5fr' : '1fr');
    stack.style.gridTemplateRows = rows.join(' ');
  }

  /* ---------------------------------------------------------- animation */

  var reduceMotion = false;
  try { reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { /* fail-open */ }

  function animate(node, frames, opts) {
    if (!node || typeof node.animate !== 'function') return null;
    try {
      var a = node.animate(frames, opts);
      openAnims.push(a);
      // A finished animation that holds its end state ("forwards") is still
      // painting, so it stays tracked until it is explicitly cancelled.
      var holds = opts && opts.fill && (opts.fill === 'forwards' || opts.fill === 'both');
      var drop = function () {
        var i = openAnims.indexOf(a);
        if (i >= 0) openAnims.splice(i, 1);
      };
      a.oncancel = drop;
      if (!holds) a.onfinish = drop;
      return a;
    } catch (e) { return null; }
  }

  function cancelAnims() {
    var list = openAnims.slice();
    openAnims = [];
    list.forEach(function (a) { try { a.cancel(); } catch (e) { /* fail-open */ } });
  }

  var EASE_OUT = 'cubic-bezier(0.16, 1, 0.3, 1)';      // swift, then settles
  var EASE_IN = 'cubic-bezier(0.7, 0, 0.84, 0)';
  var EASE_TURN_OUT = 'cubic-bezier(0.4, 0, 1, 1)';

  /* How a slat's body travels: "scale" stretches it out of the left edge
     (sharp-cornered skins); "slide" moves it in behind the slat's own
     rounded clip so round ends stay round. Declared by each skin. */
  function sweepMode() {
    var v = '';
    try { v = getComputedStyle(stack).getPropertyValue('--wk-sweep').trim(); } catch (e) { /* fail-open */ }
    return v === 'slide' ? 'slide' : 'scale';
  }

  /* The signature: Monday sweeps out of the left edge, Tuesday a beat later,
     and so on down the week, each slat carrying its type in behind its
     leading edge. Overlapping, so the seven read as one movement. */
  function playEntrance(done) {
    if (reduceMotion) { root.classList.remove('is-pre'); if (done) done(); return; }
    animate(toneEl, [{ opacity: 0 }, { opacity: 1 }], { duration: 420, easing: 'ease-out', fill: 'backwards' });
    var slide = sweepMode() === 'slide';
    var fillIn = slide
      ? [{ transform: 'translateX(-101%)' }, { transform: 'translateX(0)' }]
      : [{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }];
    var last = null;
    for (var i = 0; i < bars.length; i++) {
      var b = bars[i];
      var d0 = i * ENTER_STAGGER;
      var fillAnim = animate(b.fill, fillIn,
        { duration: ENTER_FILL_MS, delay: d0, easing: EASE_OUT, fill: 'backwards' });
      animate(b.tab.querySelector('.wk-num'), [
        { opacity: 0, transform: 'translateX(-18px)' },
        { opacity: 1, transform: 'none' }
      ], { duration: ENTER_TEXT_MS, delay: d0 + ENTER_TEXT_DELAY * 0.6, easing: EASE_OUT, fill: 'backwards' });
      animate(b.tab.querySelector('.wk-tabmeta'), [
        { opacity: 0, transform: 'translateX(-12px)' },
        { opacity: 1, transform: 'none' }
      ], { duration: ENTER_TEXT_MS, delay: d0 + ENTER_TEXT_DELAY, easing: EASE_OUT, fill: 'backwards' });
      if (b.el.classList.contains('is-today')) {
        animate(b.tabfill, [
          { transform: 'scaleX(0)' },
          { transform: 'scaleX(1)' }
        ], { duration: 520, delay: d0 + 220, easing: EASE_OUT, fill: 'backwards' });
      }
      var kids = b.evs.children;
      for (var j = 0; j < kids.length; j++) {
        animate(kids[j], [
          { opacity: 0, transform: 'translateX(-22px)' },
          { opacity: 1, transform: 'none' }
        ], { duration: ENTER_TEXT_MS, delay: d0 + ENTER_TEXT_DELAY + 60 + j * ENTER_EVENT_STEP,
             easing: EASE_OUT, fill: 'backwards' });
      }
      if (!b.more.hidden) {
        animate(b.more, [{ opacity: 0 }, { opacity: 1 }],
          { duration: 300, delay: d0 + ENTER_TEXT_DELAY + 200, easing: 'ease-out', fill: 'backwards' });
      }
      animate(b.ribbon, [
        { transform: 'scaleX(0)', opacity: 0 },
        { transform: 'scaleX(1)', opacity: 1 }
      ], { duration: 560, delay: d0 + 260, easing: EASE_OUT, fill: 'backwards' });
      last = fillAnim;
    }
    root.classList.remove('is-pre');
    var total = (bars.length - 1) * ENTER_STAGGER + Math.max(ENTER_FILL_MS, ENTER_TEXT_DELAY + 260 + ENTER_TEXT_MS);
    window.setTimeout(function () { if (done) done(); }, total);
    return last;
  }

  /* Swiped up: the week folds away from the bottom up, each slat wiping off
     to the right — the direction it arrived in — while the stack lifts. */
  function playExit(done) {
    if (reduceMotion) { if (done) done(); return; }
    var lift = currentLift();
    animate(toneEl, [{ opacity: 1 }, { opacity: 0 }],
      { duration: 360, delay: 4 * EXIT_STAGGER, easing: 'ease-in', fill: 'forwards' });
    animate(stack, [
      { transform: 'translateY(' + lift + 'px)' },
      { transform: 'translateY(' + (Math.min(lift, 0) - 26) + 'px)' }
    ], { duration: EXIT_FILL_MS + 6 * EXIT_STAGGER, easing: EASE_OUT, fill: 'forwards' });
    for (var i = 0; i < bars.length; i++) {
      var b = bars[i];
      var d0 = (bars.length - 1 - i) * EXIT_STAGGER;
      animate(b.face, [{ opacity: Number(getComputedStyle(b.face).opacity) || 1 }, { opacity: 0 }],
        { duration: 150, delay: d0, easing: 'ease-in', fill: 'forwards' });
      animate(b.ask.root, [{ opacity: 1 }, { opacity: 0 }],
        { duration: 150, delay: d0, easing: 'ease-in', fill: 'forwards' });
      var slideOut = sweepMode() === 'slide';
      if (!slideOut) b.fill.style.transformOrigin = '100% 50%';
      animate(b.fill, slideOut
        ? [{ transform: 'translateX(0)', opacity: 1 }, { transform: 'translateX(101%)', opacity: 0.6 }]
        : [{ transform: 'scaleX(1)', opacity: 1 }, { transform: 'scaleX(0)', opacity: 0.6 }],
        { duration: EXIT_FILL_MS, delay: d0 + 40, easing: EASE_IN, fill: 'forwards' });
    }
    window.setTimeout(function () { if (done) done(); }, EXIT_FILL_MS + 40 + 6 * EXIT_STAGGER + 20);
  }

  function currentLift() {
    var t = stack.style.transform || '';
    var m = t.match(/translateY\((-?[\d.]+)px\)/);
    return m ? Number(m[1]) : 0;
  }

  /* A week turn keeps the seven slats exactly where they are. Only what is
     written on them changes: the old week slides out the way the finger went,
     the new one slides in behind it, one slat after another. */
  function playTurn(dir, swap, done) {
    var faces = bars.map(function (b) { return b.face; });
    var startX = faces.map(function (f) {
      var m = (f.style.transform || '').match(/translateX\((-?[\d.]+)px\)/);
      return m ? Number(m[1]) : 0;
    });
    var startO = faces.map(function (f) { return f.style.opacity === '' ? 1 : Number(f.style.opacity); });
    var swapped = false;
    function doSwap() {
      if (swapped) return;
      swapped = true;
      swap();
    }
    if (reduceMotion) {
      faces.forEach(function (f) { f.style.transform = ''; f.style.opacity = ''; });
      doSwap();
      if (done) done();
      return;
    }
    var outEnd = (bars.length - 1) * TURN_OUT_STAGGER + TURN_OUT_MS;
    var outs = [];
    for (var i = 0; i < faces.length; i++) {
      outs[i] = animate(faces[i], [
        { transform: 'translateX(' + startX[i] + 'px)', opacity: startO[i] },
        { transform: 'translateX(' + (-dir * TURN_TRAVEL) + 'px)', opacity: 0 }
      ], { duration: TURN_OUT_MS, delay: i * TURN_OUT_STAGGER, easing: EASE_TURN_OUT, fill: 'forwards' });
      faces[i].style.transform = '';
      faces[i].style.opacity = '';
    }
    window.setTimeout(function () {
      outs.forEach(function (a) { if (a) { try { a.cancel(); } catch (e) { /* fail-open */ } } });
      if (state === 'closed' || state === 'closing') return;
      doSwap();
      for (var j = 0; j < faces.length; j++) {
        animate(faces[j], [
          { transform: 'translateX(' + (dir * TURN_TRAVEL) + 'px)', opacity: 0 },
          { transform: 'none', opacity: 1 }
        ], { duration: TURN_IN_MS, delay: j * TURN_STAGGER, easing: EASE_OUT, fill: 'backwards' });
      }
      window.setTimeout(function () { if (done) done(); }, (bars.length - 1) * TURN_STAGGER + TURN_IN_MS);
    }, outEnd);
  }

  /* --------------------------------------------- readback-confirmed motion */

  function snapshotEntries() {
    var snap = {};
    var rootRect = root.getBoundingClientRect();
    for (var i = 0; i < bars.length; i++) {
      var kids = bars[i].evs.children;
      for (var j = 0; j < kids.length; j++) {
        var n = kids[j];
        if (!n.dataset || !n.dataset.key || n.hidden) continue;
        var r = n.getBoundingClientRect();
        snap[n.dataset.key] = {
          id: n.dataset.eventId, iso: bars[i].iso, node: n.cloneNode(true),
          x: r.left - rootRect.left, y: r.top - rootRect.top, w: r.width, h: r.height
        };
      }
    }
    return snap;
  }

  /* Called after a fresh read. Only a difference the calendar itself now
     reports is animated: a moved event flies to its new day, a deleted one
     lifts away, a new one settles in. If the read has not caught up yet,
     nothing moves and the next read is compared again. */
  function applyDiff() {
    if (!pendingDiff) return false;
    if (nowMs() > pendingDiff.until) { pendingDiff = null; return false; }
    var before = pendingDiff.snapshot;
    var rootRect = root.getBoundingClientRect();
    var now = {};
    for (var i = 0; i < bars.length; i++) {
      var kids = bars[i].evs.children;
      for (var j = 0; j < kids.length; j++) {
        var n = kids[j];
        if (n.dataset && n.dataset.key) now[n.dataset.key] = { node: n, iso: bars[i].iso };
      }
    }
    var changed = false;
    var k;
    for (k in before) {
      var was = before[k];
      var is = now[k];
      if (is && is.iso === was.iso && is.node.dataset.eventId === was.id) continue;
      changed = true;
      if (is && !is.node.hidden) flyTo(was, is.node, rootRect);
      else liftAway(was);
    }
    for (k in now) {
      if (before[k] || now[k].node.hidden) continue;
      changed = true;
      settleIn(now[k].node);
    }
    if (changed) pendingDiff = null;
    return changed;
  }

  function placeClone(snap) {
    var c = snap.node.cloneNode(true);
    c.classList.remove('is-focused', 'is-focus');
    c.hidden = false;
    c.style.left = snap.x + 'px';
    c.style.top = snap.y + 'px';
    c.style.width = snap.w + 'px';
    c.style.boxSizing = 'border-box';
    flyEl.appendChild(c);
    return c;
  }

  function flyTo(was, node, rootRect) {
    var r = node.getBoundingClientRect();
    var dx = r.left - rootRect.left - was.x;
    var dy = r.top - rootRect.top - was.y;
    var clone = placeClone(was);
    node.style.visibility = 'hidden';
    var a = animate(clone, [
      { transform: 'translate(0,0) scale(1)', offset: 0 },
      { transform: 'translate(' + (dx * 0.5) + 'px,' + (dy * 0.5 - 10) + 'px) scale(1.04)', offset: 0.5 },
      { transform: 'translate(' + dx + 'px,' + dy + 'px) scale(1)', offset: 1 }
    ], { duration: 720, easing: 'cubic-bezier(0.45, 0, 0.2, 1)', fill: 'forwards' });
    var finish = function () {
      node.style.visibility = '';
      if (clone.parentNode) clone.parentNode.removeChild(clone);
      animate(node, [{ opacity: 0.4 }, { opacity: 1 }], { duration: 260, easing: 'ease-out' });
    };
    if (a) a.finished.then(finish, finish); else finish();
  }

  function liftAway(was) {
    var clone = placeClone(was);
    var a = animate(clone, [
      { transform: 'none', opacity: 1 },
      { transform: 'translateY(-10px) scale(0.94)', opacity: 0 }
    ], { duration: 420, easing: EASE_IN, fill: 'forwards' });
    var finish = function () { if (clone.parentNode) clone.parentNode.removeChild(clone); };
    if (a) a.finished.then(finish, finish); else finish();
  }

  function settleIn(node) {
    animate(node, [
      { opacity: 0, transform: 'translateY(8px)' },
      { opacity: 1, transform: 'none' }
    ], { duration: 460, easing: EASE_OUT });
  }

  /* ------------------------------------------------------------- lifecycle */

  function setState(next) {
    state = next;
    root.dataset.state = next;
    document.body.dataset.weekCalendar = next === 'closed' ? 'closed' : 'open';
  }

  function isOpen() { return state !== 'closed' && state !== 'closing'; }

  function takeScreen() {
    var overlays = window.jarvisOverlays;
    if (overlays) {
      overlays.acquire('week-calendar');
      if (typeof overlays.claimScreen === 'function') overlays.claimScreen('week-calendar');
    }
    // One calendar at a time, and an explicit request outranks a reader left open.
    if (window.jarvisCalendar && window.jarvisCalendar.state !== 'closed') window.jarvisCalendar.close('week-calendar');
    if (window.jarvisBriefingReader && window.jarvisBriefingReader.state &&
        window.jarvisBriefingReader.state !== 'closed') window.jarvisBriefingReader.close('week-calendar');
  }

  function materialise() {
    window.clearTimeout(timers.inert);
    if (!root.classList.contains('is-inert') && bars.length) return;
    buildStack();
    // Slats exist before the entrance plays; until it does, nothing shows.
    root.classList.add('is-pre');
    root.classList.remove('is-inert');
    root.removeAttribute('aria-hidden');
    stack.style.transform = '';
    attachListeners();
  }

  function goInert() {
    cancelAnims();
    dropSkinGhost();
    root.classList.remove('is-pre');
    root.classList.add('is-inert');
    root.setAttribute('aria-hidden', 'true');
    stack.replaceChildren();
    stack.style.transform = '';
    stack.style.gridTemplateRows = '';
    flyEl.replaceChildren();
    bars = [];
    detachListeners();
    noteEl.dataset.shown = 'no';
  }

  /* Open — or, if already open, go to the week asked for. `opts`:
     date (any day of the wanted week), focus ({dates, person, title}),
     select (an ISO date to select), reason. */
  function open(opts) {
    opts = opts || {};
    var overlays = window.jarvisOverlays;
    if (overlays && overlays.busy && !opts.forceBusy) {
      // A result card from the turn before is still leaving. Wait for it
      // briefly rather than refusing a request the user just made.
      var waited = opts._waited || 0;
      if (waited < BUSY_WAIT_MS) {
        window.clearTimeout(timers.busy);
        timers.busy = window.setTimeout(function () {
          opts._waited = waited + 100;
          open(opts);
        }, 100);
        return true;
      }
      return false;
    }
    var target = isIso(opts.date) ? mondayOf(opts.date) : mondayOf(todayIso());
    var nextFocus = normaliseFocus(opts.focus);

    if (isOpen()) {
      takeScreen();
      if (target !== weekStart) {
        turnTo(target, target > weekStart ? 1 : -1, function () {
          applyFocus(nextFocus, opts.select);
        });
      } else {
        applyFocus(nextFocus, opts.select);
      }
      armIdle();
      return true;
    }

    window.clearTimeout(timers.inert);
    if (state === 'closing') cancelAnims();
    materialise();
    takeScreen();
    weekStart = target;
    selectedIso = null;
    focusedEventId = null;
    focus = nextFocus;
    if (opts.select && isIso(opts.select) && mondayOf(opts.select) === weekStart) selectedIso = opts.select;
    clearAsk();
    setState('opening');
    stack.style.transform = '';
    console.log('[Week] open (' + (opts.reason || 'api') + ') week=' + weekStart);

    var started = false;
    function start() {
      if (started || state !== 'opening') return;
      started = true;
      renderWeek();
      playEntrance(function () {
        if (state === 'opening') setState('open');
        prefetchNeighbours();
      });
    }
    loadProfiles(function () {
      loadWeek(weekStart, function () {
        if (!started) start();
        else if (isOpen()) renderWeek();
      });
    });
    // Never hold the entrance hostage to the network: the dates are known
    // now, the events arrive into slats that are already there.
    window.setTimeout(start, 260);
    startHeartbeat();
    armIdle();
    pushContext(true);
    // The saved skin is the authority; a missed SSE message cannot leave the
    // week opening in yesterday's skin.
    syncSkin();
    return true;
  }

  function close(reason) {
    if (state === 'closed') return false;
    if (state === 'closing') return true;
    console.log('[Week] close (' + (reason || 'api') + ')');
    window.clearTimeout(timers.busy);
    stopTimers();
    gesture = null;
    releaseBtn();
    selectedIso = null;
    focusedEventId = null;
    focus = null;
    proposal = null;
    mutating = false;
    pendingDiff = null;
    setState('closing');
    window.clearTimeout(timers.note);
    noteEl.dataset.shown = 'no';
    // The context goes first: after this, "here" no longer means anything on
    // this screen even while the slats are still folding away.
    pushContext(true);
    var finish = function () {
      if (state !== 'closing') return;
      setState('closed');
      goInert();
      if (window.jarvisOverlays) window.jarvisOverlays.release('week-calendar');
    };
    if (reason === 'preempted' || reason === 'visual_answer' || reason === 'month') {
      // Something else is taking the screen right now; get out of its way.
      cancelAnims();
      finish();
    } else {
      playExit(finish);
      timers.inert = window.setTimeout(finish, 1200);
    }
    return true;
  }

  function stopTimers() {
    window.clearTimeout(timers.idle);
    window.clearInterval(timers.heartbeat);
    window.clearTimeout(timers.retry);
    window.clearTimeout(timers.result);
    window.clearTimeout(timers.prefetch);
    window.clearTimeout(timers.note);
    window.clearTimeout(refitTimer);
  }

  function prefetchNeighbours() {
    window.clearTimeout(timers.prefetch);
    timers.prefetch = window.setTimeout(function () {
      if (!isOpen()) return;
      loadWeek(isoAdd(weekStart, -7));
      loadWeek(isoAdd(weekStart, 7));
    }, 500);
  }

  function turnTo(monday, dir, after) {
    if (!isOpen() || state === 'turning') return false;
    dropSkinGhost();
    var prevState = state;
    setState('turning');
    // The selection belongs to the week it was made in. Leaving it behind on
    // a week nobody can see would make "here" point off-screen.
    selectedIso = null;
    focusedEventId = null;
    focus = null;
    var dataReady = false;
    var swapped = false;
    weekStart = monday;
    loadWeek(monday, function () {
      dataReady = true;
      if (swapped && isOpen()) renderWeek();
    });
    playTurn(dir, function () {
      swapped = true;
      renderWeek();
    }, function () {
      if (state === 'turning') setState(prevState === 'opening' ? 'open' : 'open');
      if (!dataReady) renderWeek();
      prefetchNeighbours();
      if (after) after();
    });
    pushContext(true);
    armIdle();
    return true;
  }

  function stepWeek(delta) {
    if (!delta || !isOpen()) return false;
    var ok = turnTo(isoAdd(weekStart, 7 * delta), delta > 0 ? 1 : -1);
    if (ok) showNote(weekLabel(weekStart));
    return ok;
  }

  /* Said once, briefly, when the week changes under a finger — there is no
     permanent header to carry it. */
  function weekLabel(monday) {
    var diff = Math.round((utcOfIso(monday) - utcOfIso(mondayOf(todayIso()))) / (7 * DAY_MS));
    var rel = diff === 0 ? 'This week' : diff === 1 ? 'Next week' : diff === -1 ? 'Last week' :
      (diff > 0 ? 'In ' + diff + ' weeks' : -diff + ' weeks ago');
    var sunday = isoAdd(monday, 6);
    var span = monthName(monday) + ' ' + dayNum(monday) + ' – ' +
      (monthNum(sunday) !== monthNum(monday) ? monthName(sunday) + ' ' : '') + dayNum(sunday);
    if (sunday.slice(0, 4) !== todayIso().slice(0, 4)) span = span + ', ' + sunday.slice(0, 4);
    return rel + '  ·  ' + span;
  }

  /* ----------------------------------------------------------- selection */

  function selectDate(iso) {
    if (!isIso(iso) || mondayOf(iso) !== weekStart) return false;
    selectedIso = iso;
    focusedEventId = null;
    refreshSelection();
    pushContext();
    return true;
  }

  function selectEvent(id) {
    var found = findEntry(id);
    if (!found) return false;
    focusedEventId = id;
    selectedIso = found.iso;
    refreshSelection();
    pushContext();
    return true;
  }

  function clearSelection() {
    selectedIso = null;
    focusedEventId = null;
    refreshSelection();
    pushContext();
  }

  function refreshSelection() {
    for (var i = 0; i < bars.length; i++) {
      var b = bars[i];
      b.el.classList.toggle('is-selected', b.iso === selectedIso);
      var kids = b.evs.children;
      for (var j = 0; j < kids.length; j++) {
        if (kids[j].dataset) kids[j].classList.toggle('is-focused', kids[j].dataset.eventId === focusedEventId);
      }
    }
    layoutBars();
  }

  function findEntry(id) {
    var rec = weekRecord();
    if (!rec || !rec.byDate || !id) return null;
    for (var iso in rec.byDate) {
      var list = rec.byDate[iso];
      for (var i = 0; i < list.length; i++) if (list[i].ev.id === id) return { iso: list[i].iso, ev: list[i].ev, entry: list[i] };
    }
    return null;
  }

  function normaliseFocus(f) {
    if (!f || !f.dates) return null;
    var dates = {};
    var any = false;
    (Array.isArray(f.dates) ? f.dates : Object.keys(f.dates)).forEach(function (d) {
      if (isIso(d)) { dates[d] = 1; any = true; }
    });
    if (!any) return null;
    var person = String(f.person || '').trim().toLowerCase();
    return { dates: dates, person: person, title: String(f.title || '').trim() };
  }

  /* A voice answer's spotlight. One date also becomes the selection, so the
     next "here" means the day Jarvis just talked about. */
  function applyFocus(nextFocus, select) {
    focus = nextFocus;
    var dates = focus ? Object.keys(focus.dates).filter(function (d) { return mondayOf(d) === weekStart; }) : [];
    if (isIso(select) && mondayOf(select) === weekStart) {
      selectedIso = select;
      focusedEventId = null;
    } else if (dates.length === 1) {
      selectedIso = dates[0];
      focusedEventId = null;
    }
    renderWeek();
    pushContext();
  }

  function clearFocus() {
    if (!focus) return;
    focus = null;
    root.classList.remove('has-focus');
    for (var i = 0; i < bars.length; i++) {
      bars[i].el.classList.remove('is-focus');
      var kids = bars[i].evs.children;
      for (var j = 0; j < kids.length; j++) kids[j].classList && kids[j].classList.remove('is-focus');
    }
  }

  /* ------------------------------------------------------------- context */

  function contextPayload() {
    if (!isOpen()) return { calendar_open: false };
    var found = focusedEventId ? findEntry(focusedEventId) : null;
    var ev = found ? found.ev : null;
    var who = ev ? whoOf(ev.calendar_id) : null;
    return {
      calendar_open: true,
      view: 'week',
      visible_week_start: weekStart,
      visible_week_end: isoAdd(weekStart, 6),
      // The month the week mostly belongs to, for callers that only know months.
      visible_month: isoAdd(weekStart, 3).slice(0, 7),
      today: todayIso(),
      selected_date: selectedIso,
      focused_event_id: ev ? ev.id : null,
      focused_event: ev ? {
        id: ev.id, title: ev.title, start: ev.start, end: ev.end, all_day: Boolean(ev.all_day),
        calendar_id: ev.calendar_id, owner: who && who.id !== 'other' ? who.id : null,
        writable: Boolean(ev.writable), recurring: Boolean(ev.source_ref && ev.source_ref.recurring)
      } : null,
      last_user_touch_at: new Date().toISOString()
    };
  }

  var contextTimer = 0;
  function pushContext(immediate) {
    window.clearTimeout(contextTimer);
    var send = function () {
      var body = contextPayload();
      // The month overlay owns the shared context while it is on screen.
      if (!body.calendar_open && window.jarvisCalendar && window.jarvisCalendar.state &&
          window.jarvisCalendar.state !== 'closed') return;
      fetch('/api/calendar/context', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      }).catch(function () { /* fail-open: context is a convenience */ });
    };
    if (immediate) send(); else contextTimer = window.setTimeout(send, 120);
  }

  function startHeartbeat() {
    window.clearInterval(timers.heartbeat);
    timers.heartbeat = window.setInterval(function () {
      if (!isOpen()) return;
      pushContext(true);
      // A quiet refresh while somebody is looking: another phone may have
      // changed the week. No animation unless something actually differs.
      var rec = weekRecord();
      if (rec && nowMs() - rec.ts >= DATA_TTL_MS && state === 'open') {
        loadWeek(weekStart, function () { if (state === 'open') renderWeek(); }, true);
      }
    }, HEARTBEAT_MS);
  }

  function armIdle() {
    window.clearTimeout(timers.idle);
    if (!isOpen()) return;
    timers.idle = window.setTimeout(function () {
      var overlays = window.jarvisOverlays;
      if ((overlays && overlays.sessionActive) || proposal || mutating || gesture) { armIdle(); return; }
      close('inactivity');
    }, IDLE_MS);
  }

  function showNote(text, sticky) {
    noteEl.textContent = String(text || '').slice(0, 48);
    noteEl.dataset.shown = 'yes';
    window.clearTimeout(timers.note);
    timers.note = window.setTimeout(function () { noteEl.dataset.shown = 'no'; }, sticky ? NOTE_MS * 2 : NOTE_MS);
  }

  function scheduleRetry() {
    window.clearTimeout(timers.retry);
    timers.retry = window.setTimeout(function () {
      var rec = weekRecord();
      if (!isOpen() || !rec || !rec.error) return;
      loadWeek(weekStart, function (r) {
        if (isOpen()) renderWeek();
        if (r.error) scheduleRetry();
      }, true);
    }, RETRY_MS);
  }

  /* ------------------------------------------------------------- gestures */

  function attachListeners() {
    if (listening) return;
    listening = true;
    window.addEventListener('pointerdown', onDown, { capture: true, passive: true });
    window.addEventListener('pointermove', onMove, { capture: true, passive: false });
    window.addEventListener('pointerup', onUp, { capture: true, passive: true });
    window.addEventListener('pointercancel', onCancel, { capture: true, passive: true });
    window.addEventListener('click', swallow, { capture: true });
  }

  function detachListeners() {
    if (!listening) return;
    listening = false;
    window.removeEventListener('pointerdown', onDown, { capture: true });
    window.removeEventListener('pointermove', onMove, { capture: true });
    window.removeEventListener('pointerup', onUp, { capture: true });
    window.removeEventListener('pointercancel', onCancel, { capture: true });
    window.removeEventListener('click', swallow, { capture: true });
  }

  /* While the week is on screen it owns every touch. Nothing reaches the
     gallery, the Briefing reader or a caption underneath it. */
  function swallow(e) {
    if (state === 'closed') return;
    if (typeof e.stopImmediatePropagation === 'function') e.stopImmediatePropagation();
  }

  function onDown(e) {
    if (state === 'closed') return;
    swallow(e);
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    if (gesture) return;   // a second finger never starts a second gesture
    armIdle();
    var target = e.target && e.target.closest ? e.target : null;
    gesture = {
      id: e.pointerId, x0: e.clientX, y0: e.clientY, t0: e.timeStamp,
      x: e.clientX, y: e.clientY, t: e.timeStamp, axis: null, moved: false,
      target: target
    };
    var btn = target ? target.closest('.wk-btn') : null;
    if (btn && proposal && !mutating) pressBtn(btn);
  }

  function onMove(e) {
    if (!gesture || e.pointerId !== gesture.id) return;
    swallow(e);
    var dx = e.clientX - gesture.x0;
    var dy = e.clientY - gesture.y0;
    gesture.vx = (e.clientX - gesture.x) / Math.max(1, e.timeStamp - gesture.t);
    gesture.vy = (e.clientY - gesture.y) / Math.max(1, e.timeStamp - gesture.t);
    gesture.x = e.clientX; gesture.y = e.clientY; gesture.t = e.timeStamp;
    if (Math.abs(dx) > TAP_SLOP || Math.abs(dy) > TAP_SLOP) gesture.moved = true;
    if (pressedBtn && (Math.abs(dx) > BTN_SLOP || Math.abs(dy) > BTN_SLOP)) releaseBtn();
    if (state !== 'open') return;     // nothing is dragged while the week moves

    if (!gesture.axis) {
      var ax = Math.abs(dx), ay = Math.abs(dy);
      if (ax < AXIS_LOCK && ay < AXIS_LOCK) return;
      if (ax >= ay * AXIS_RATIO) gesture.axis = 'x';
      else if (ay >= ax * AXIS_RATIO) gesture.axis = 'y';
      else return;   // diagonal: wait until it says what it is
      try { root.setPointerCapture(e.pointerId); } catch (err) { /* fail-open */ }
    }
    if (e.cancelable) e.preventDefault();
    var locked = Boolean(proposal || mutating);
    if (gesture.axis === 'x') {
      var shift = dx * (locked ? 0.08 : 0.42);
      for (var i = 0; i < bars.length; i++) {
        var lag = 1 - i * 0.035;
        bars[i].face.style.transform = 'translateX(' + (shift * lag).toFixed(1) + 'px)';
        bars[i].face.style.opacity = locked ? '' : String(Math.max(0.35, 1 - Math.abs(dx) / 620));
      }
    } else {
      var lift = dy < 0 ? dy * (locked ? 0.06 : 0.55) : dy * 0.12;
      stack.style.transform = 'translateY(' + lift.toFixed(1) + 'px)';
    }
  }

  function onUp(e) {
    if (!gesture || e.pointerId !== gesture.id) return;
    swallow(e);
    var g = gesture;
    gesture = null;
    var dx = e.clientX - g.x0;
    var dy = e.clientY - g.y0;
    var dt = Math.max(1, e.timeStamp - g.t0);
    try { root.releasePointerCapture(e.pointerId); } catch (err) { /* fail-open */ }

    if (pressedBtn) {
      var btn = pressedBtn;
      releaseBtn();
      var still = e.target && e.target.closest ? e.target.closest('.wk-btn') : null;
      if (!g.moved && still === btn) activateBtn(btn);
      return;
    }
    if (!g.axis) {
      if (!g.moved && dt < LONG_PRESS_MS && state === 'open') handleTap(g.target);
      return;
    }
    var locked = Boolean(proposal || mutating);
    if (g.axis === 'x') {
      var vx = g.vx || dx / dt;
      var commit = !locked && (Math.abs(dx) >= WEEK_COMMIT_PX ||
        (Math.abs(dx) >= 36 && Math.abs(vx) >= WEEK_FLICK && (vx > 0) === (dx > 0)));
      if (commit && state === 'open') {
        stepWeek(dx < 0 ? 1 : -1);     // swipe left -> next week
      } else {
        settleFaces();
        if (locked) showNote('Confirm or cancel the change first');
      }
      return;
    }
    var vy = g.vy || dy / dt;
    var close_ = !locked && dy < 0 && (-dy >= CLOSE_COMMIT_PX || (-dy >= 44 && vy <= -CLOSE_FLICK));
    if (close_ && state === 'open') {
      close('swipe_up');
    } else {
      settleStack();
      if (locked && dy < -40) showNote('Confirm or cancel the change first');
    }
  }

  function onCancel(e) {
    if (!gesture || e.pointerId !== gesture.id) return;
    gesture = null;
    releaseBtn();
    settleFaces();
    settleStack();
  }

  function settleFaces() {
    for (var i = 0; i < bars.length; i++) {
      var f = bars[i].face;
      var from = f.style.transform;
      var op = f.style.opacity;
      f.style.transform = '';
      f.style.opacity = '';
      if (from) animate(f, [{ transform: from, opacity: op === '' ? 1 : Number(op) }, { transform: 'none', opacity: 1 }],
        { duration: 300, easing: EASE_OUT });
    }
  }

  function settleStack() {
    var from = stack.style.transform;
    stack.style.transform = '';
    if (from) animate(stack, [{ transform: from }, { transform: 'none' }], { duration: 320, easing: EASE_OUT });
  }

  /* One touch is enough. An event wins over the slat it sits on; a date tab
     or the empty part of a slat selects the day. Touching what is already
     selected lets go of it. */
  function handleTap(target) {
    if (!target) return;
    if (proposal || mutating) {
      showNote('Confirm or cancel the change first');
      return;
    }
    var barEl = target.closest('.wk-bar');
    if (!barEl) return;   // the margin or a gap: the gallery shows through, nothing happens
    clearFocus();
    var evEl = target.closest('.wk-ev');
    if (evEl && evEl.dataset.eventId) {
      if (focusedEventId === evEl.dataset.eventId) {
        focusedEventId = null;
        refreshSelection();
        pushContext();
      } else {
        selectEvent(evEl.dataset.eventId);
      }
      return;
    }
    var iso = barEl.dataset.date;
    if (selectedIso === iso && !focusedEventId) clearSelection();
    else selectDate(iso);
  }

  /* ----------------------------------------------------- change questions */

  function pressBtn(btn) {
    releaseBtn();
    pressedBtn = btn;
    btn.classList.add('is-pressed');
  }

  function releaseBtn() {
    if (!pressedBtn) return;
    pressedBtn.classList.remove('is-pressed');
    pressedBtn = null;
  }

  function post(path, body) {
    return fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) { return r.json(); });
  }

  /* Nothing destructive happens on pointerdown: a press must begin and end on
     the same answer. While one is in flight nothing else is accepted. */
  function activateBtn(btn) {
    if (!proposal || mutating) return;
    var opId = proposal.operation_id;
    if (btn.dataset.choice === 'cancel') {
      mutating = true;
      post('/api/calendar/mutation/cancel', { operation_id: opId, source: 'touch' })
        .then(function () { endAsk('cancelled_by_touch'); })
        .catch(function () { endAsk('cancel_failed'); });
      return;
    }
    if (btn.dataset.choice !== 'confirm') return;
    mutating = true;
    setAsk('executing');
    post('/api/calendar/mutation/confirm', { operation_id: opId, source: 'touch' })
      .then(function (res) {
        showResult({
          status: res && res.ok ? 'succeeded' : 'failed',
          summary_line: (res && res.summary_line) || null,
          operation_id: opId
        });
      })
      .catch(function () { showResult({ status: 'failed', summary_line: 'Could not make the change', operation_id: opId }); });
  }

  function askBar() {
    for (var i = 0; i < bars.length; i++) if (bars[i].el.dataset.ask) return bars[i];
    return null;
  }

  function dayText(iso) { return monthName(iso) + ' ' + dayNum(iso); }
  function clockText(s) {
    var ms = parseMs(s);
    if (ms === null) return '';
    var d = kstDate(ms);
    var h = d.getUTCHours();
    return (h % 12 === 0 ? 12 : h % 12) + ':' + pad2(d.getUTCMinutes()) + (h < 12 ? ' AM' : ' PM');
  }
  function whenText(start, allDay) {
    if (!start) return '';
    var iso = allDay ? String(start).slice(0, 10) : isoOfMs(parseMs(start));
    return dayText(iso) + ' (' + WEEKDAYS[weekdayIndex(iso)] + ')' + (allDay ? '' : ' ' + clockText(start));
  }

  function targetIso(p) {
    var t = (p && p.target) || {};
    if (!t.start) return null;
    return t.all_day ? String(t.start).slice(0, 10) : isoOfMs(parseMs(t.start));
  }

  function showAsk() {
    if (!proposal || !isOpen()) return;
    var iso = targetIso(proposal);
    if (!iso) return;
    if (mondayOf(iso) !== weekStart) {
      turnTo(mondayOf(iso), mondayOf(iso) > weekStart ? 1 : -1, showAsk);
      return;
    }
    clearAsk(true);
    selectedIso = iso;
    var t = proposal.target || {};
    focusedEventId = t.id && findEntry(t.id) ? t.id : null;
    var b = bars[weekdayIndex(iso)];
    var action = proposal.action === 'delete' ? 'delete' : 'update';
    b.el.dataset.ask = action;
    b.ask.title.textContent = t.title || 'Event';
    if (action === 'update') {
      var next = (proposal.changes || {}).start;
      var nextTitle = (proposal.changes || {}).title;
      b.ask.kicker.textContent = 'Change it like this?';
      if (next) {
        b.ask.from.textContent = whenText(t.start, t.all_day);
        b.ask.to.textContent = whenText(next, t.all_day);
      } else {
        b.ask.from.textContent = t.title || '';
        b.ask.to.textContent = nextTitle || '';
      }
      b.ask.change.style.display = '';
      b.ask.confirm.textContent = 'Change';
      ghostDestination(next, t);
    } else {
      b.ask.kicker.textContent = 'Delete this event?';
      b.ask.from.textContent = whenText(t.start, t.all_day);
      b.ask.to.textContent = '';
      b.ask.change.style.display = 'none';
      b.ask.confirm.textContent = 'Delete';
    }
    setAsk('confirm');
    refreshSelection();
    pushContext();
  }

  /* For a date move, the day it would land on shows where it would go. */
  function ghostDestination(next, t) {
    if (!next) return;
    var iso = t.all_day ? String(next).slice(0, 10) : isoOfMs(parseMs(next));
    if (!iso || mondayOf(iso) !== weekStart || iso === targetIso(proposal)) return;
    var b = bars[weekdayIndex(iso)];
    var empty = b.evs.querySelector('.wk-empty');
    if (empty) empty.remove();
    var g = el('div', 'wk-ev is-ghost');
    g.dataset.who = whoOf(t.calendar_id).id;
    var when = el('span', 'wk-ev-when');
    when.appendChild(el('i', 'wk-ev-mark'));
    when.appendChild(document.createTextNode(t.all_day ? 'All day · move here' : clockText(next) + ' · move here'));
    g.appendChild(when);
    g.appendChild(el('span', 'wk-ev-title', t.title || 'Event'));
    b.evs.insertBefore(g, b.evs.firstChild);
    fitBar(b);
  }

  function setAsk(mode, result) {
    askMode = mode;
    var b = askBar();
    if (!b) return;
    b.el.dataset.askMode = mode;
    if (result) b.el.dataset.askResult = result; else delete b.el.dataset.askResult;
    if (mode === 'executing') b.ask.status.textContent = 'Applying';
  }

  function clearAsk(keepState) {
    for (var i = 0; i < bars.length; i++) {
      var e = bars[i].el;
      delete e.dataset.ask;
      delete e.dataset.askMode;
      delete e.dataset.askResult;
      var ghosts = bars[i].evs.querySelectorAll ? bars[i].evs.querySelectorAll('.is-ghost') : [];
      for (var j = 0; j < ghosts.length; j++) ghosts[j].remove();
    }
    if (!keepState) askMode = null;
  }

  function endAsk(reason) {
    proposal = null;
    mutating = false;
    releaseBtn();
    clearAsk();
    if (isOpen()) refreshSelection();
    if (reason) console.log('[Week] question cleared: ' + reason);
    armIdle();
  }

  function showResult(msg) {
    mutating = false;
    releaseBtn();
    var failed = msg.status !== 'succeeded';
    var b = askBar();
    if (failed) {
      if (b) {
        setAsk('result', 'failed');
        b.ask.status.textContent = msg.summary_line || 'Could not make the change';
      } else if (isOpen()) {
        showNote(msg.summary_line || 'Could not make the change');
      }
      proposal = null;
      window.clearTimeout(timers.result);
      timers.result = window.setTimeout(function () { endAsk('failed'); }, FAILED_MS);
      armIdle();
      return;
    }
    // The provider said yes. The screen only moves the event once a fresh
    // read of the calendar shows it moved.
    if (isOpen()) pendingDiff = { snapshot: snapshotEntries(), until: nowMs() + DIFF_WINDOW_MS };
    if (b) {
      setAsk('result', 'succeeded');
      b.ask.status.textContent = '✓ ' + (msg.summary_line || 'Done');
    } else if (isOpen() && msg.summary_line) {
      showNote('✓ ' + msg.summary_line);
    }
    proposal = null;
    window.clearTimeout(timers.result);
    timers.result = window.setTimeout(function () { endAsk('succeeded'); }, RESULT_MS);
    dropCache();
    armIdle();
  }

  function refreshAfterMutation() {
    dropCache();
    if (!isOpen() || !weekStart) return;
    loadWeek(weekStart, function () {
      if (!isOpen()) return;
      renderWeek();
      if (askMode !== 'confirm' && askMode !== 'executing') applyDiff();
    }, true);
  }

  /* The proposal lifecycle arrives on the same channel as everything else,
     so voice and touch converge on one operation_id and one screen. */
  function handleMutation(msg) {
    var event = msg.event;
    if (event === 'proposal') {
      var p = msg.proposal || msg;
      if (!p || !p.operation_id) return;
      proposal = p;
      mutating = false;
      window.clearTimeout(timers.result);
      var iso = targetIso(p) || todayIso();
      if (!isOpen()) {
        open({ date: iso, reason: 'mutation' });
        // The entrance renders before the ask; ask once the slats exist.
        window.setTimeout(showAsk, 300);
      } else {
        showAsk();
      }
      armIdle();
      return;
    }
    if (event === 'proposal_cleared') {
      if (proposal && (!msg.operation_id || proposal.operation_id === msg.operation_id)) endAsk(msg.status || 'cleared');
      return;
    }
    if (event === 'executing') {
      if (proposal && proposal.operation_id === msg.operation_id) { mutating = true; setAsk('executing'); armIdle(); }
      return;
    }
    if (event === 'working') {
      // A voice "add" under way. Shown only if the week is already up and the
      // day is on it: an add nobody is watching does not open anything.
      if (!isOpen()) return;
      if (msg.date && isIso(msg.date) && mondayOf(msg.date) === weekStart) {
        showNote((msg.title ? msg.title + ' · ' : '') + 'Adding');
      }
      if (isOpen()) pendingDiff = { snapshot: snapshotEntries(), until: nowMs() + DIFF_WINDOW_MS + 4000 };
      armIdle();
      return;
    }
    if (event === 'result') {
      if (proposal && msg.operation_id && proposal.operation_id !== msg.operation_id && !askBar()) return;
      if (!isOpen()) { dropCache(); return; }
      if (askBar() || (proposal && proposal.operation_id === msg.operation_id)) {
        showResult(msg);
      } else if (msg.status === 'succeeded') {
        if (!pendingDiff) pendingDiff = { snapshot: snapshotEntries(), until: nowMs() + DIFF_WINDOW_MS };
        if (msg.summary_line) showNote('✓ ' + msg.summary_line);
        dropCache();
      } else {
        pendingDiff = null;
        showNote(msg.summary_line || 'Could not make the change');
      }
      return;
    }
    if (event === 'refreshed') {
      refreshAfterMutation();
    }
  }


  /* -------------------------------------------------------------- skins */

  function loadSkinFonts(name) {
    var specs = SKIN_FONTS[name] || [];
    if (!document.fonts || !document.fonts.load || !specs.length) return Promise.resolve();
    var all = Promise.all(specs.map(function (f) {
      return document.fonts.load(f, '0123456789MonTueWedThuFriSatSun').catch(function () { /* fail-open */ });
    }));
    var timeout = new Promise(function (res) { window.setTimeout(res, SKIN_FONT_WAIT_MS); });
    return Promise.race([all, timeout]);
  }

  function setSkinAttr(name) {
    skin = name;
    root.dataset.skin = name;
    stack.dataset.skin = name;
  }

  function dropSkinGhost() {
    if (skinGhost && skinGhost.parentNode) skinGhost.parentNode.removeChild(skinGhost);
    skinGhost = null;
  }

  function reportRendered(name) {
    fetch('/api/calendar/week-skin/rendered', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ skin: name })
    }).catch(function () { /* fail-open */ });
  }

  /* Change the skin in place. On an open, settled week the old print is
     copied over the slats and peeled away from Monday to Sunday — the
     signature's own rhythm — while the new type settles in underneath. The
     week, the selection and every position stay exactly where they were. */
  function setSkin(name, opts) {
    opts = opts || {};
    if (SKINS.indexOf(name) < 0) return Promise.resolve(false);
    var seq = ++skinSeq;
    if (name === skin && root.dataset.skin === name) {
      reportRendered(name);
      return Promise.resolve(true);
    }
    return loadSkinFonts(name).then(function () {
      if (seq !== skinSeq) return false;      // a newer request won
      var prev = skin;
      var animateIt = !opts.instant && !reduceMotion && state === 'open' && bars.length === 7;
      dropSkinGhost();
      if (animateIt) {
        var ghost = stack.cloneNode(true);
        ghost.classList.add('wk-ghost');
        ghost.setAttribute('aria-hidden', 'true');
        ghost.dataset.skin = prev;
        stack.parentNode.insertBefore(ghost, stack.nextSibling);
        skinGhost = ghost;
        setSkinAttr(name);
        layoutBars();
        var olds = ghost.children;
        for (var i = 0; i < olds.length; i++) {
          // The old print is peeled off left to right — the direction the
          // slats first arrived in — so two palettes never blend into a
          // muddy middle. The new type follows just behind the edge.
          animate(olds[i], [
            { clipPath: 'inset(0 0 0 0)' },
            { clipPath: 'inset(0 0 0 100%)' }
          ], { duration: SKIN_OUT_MS, delay: i * SKIN_STAGGER, easing: 'cubic-bezier(0.65, 0, 0.35, 1)', fill: 'forwards' });
          animate(bars[i].face, [
            { opacity: 0, transform: 'translateX(-14px)' },
            { opacity: 1, transform: 'none' }
          ], { duration: SKIN_IN_MS, delay: i * SKIN_STAGGER + 140, easing: EASE_OUT, fill: 'backwards' });
        }
        window.setTimeout(function () {
          if (skinGhost === ghost) dropSkinGhost();
        }, (olds.length - 1) * SKIN_STAGGER + Math.max(SKIN_OUT_MS, SKIN_IN_MS + 90) + 40);
      } else {
        setSkinAttr(name);
        if (isOpen() && bars.length) layoutBars();
      }
      console.log('[Week] skin ' + prev + ' -> ' + name + (animateIt ? ' (in place)' : ''));
      reportRendered(name);
      return true;
    });
  }

  /* Read the saved skin and wear it. Missing or unreadable -> the default. */
  function syncSkin() {
    return fetch('/api/calendar/week-skin')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var name = data && SKINS.indexOf(data.skin) >= 0 ? data.skin : DEFAULT_SKIN;
        return setSkin(name, { instant: state !== 'open' });
      })
      .catch(function () { return setSkin(skin, { instant: true }); });
  }

  /* ----------------------------------------------------------------- voice */

  function handle(msg) {
    if (!msg) return;
    if (msg.action === 'mutation') { handleMutation(msg); return; }
    if (msg.action === 'close') { close('voice'); return; }
    var date = isIso(msg.date) ? msg.date : null;
    if (!date && msg.month && /^\d{4}-\d{2}$/.test(msg.month)) date = msg.month + '-01';
    if (msg.action === 'open' || msg.action === 'month') {
      open({ date: date, focus: msg.focus, reason: 'voice' });
      return;
    }
    if (msg.action === 'select') {
      open({ date: date, focus: msg.focus, select: date, reason: 'voice' });
    }
  }

  /* --------------------------------------------------------------- public */

  window.jarvisWeekCalendar = {
    open: function (opts) { return open(Object.assign({ reason: 'api' }, opts || {})); },
    close: function (reason) { return close(reason || 'api'); },
    handle: handle,
    stepWeek: function (d) { return stepWeek(Number(d) || 0); },
    selectDate: selectDate,
    selectEvent: selectEvent,
    clearSelection: clearSelection,
    setSkin: function (name, opts) { return setSkin(String(name || '').toLowerCase(), opts); },
    get skin() { return skin; },
    get skinChanging() { return Boolean(skinGhost); },
    get state() { return state; },
    get isOpen() { return isOpen(); },
    get isInert() { return root.classList.contains('is-inert'); },
    get weekStart() { return weekStart; },
    get selectedDate() { return selectedIso; },
    get focusedEventId() { return focusedEventId; },
    get proposal() { return proposal; },
    get askMode() { return askMode; },
    get listening() { return listening; },
    get liveAnimations() { return openAnims.length; },
    context: contextPayload,
    _test: {
      isoOfMs: isoOfMs, isoAdd: isoAdd, weekdayIndex: weekdayIndex, mondayOf: mondayOf, weekLabel: weekLabel, skins: SKINS, syncSkin: syncSkin,
      dayRange: dayRange, indexWeek: indexWeek, whenLabel: whenLabel, stableKey: stableKey,
      setProfiles: function (map, meta) { whoByCalendar = map; calMeta = meta || calMeta; },
      timers: timers
    }
  };

  if (window.jarvisOverlays && window.jarvisOverlays.onPreempt) {
    window.jarvisOverlays.onPreempt(function (reason) { close(reason || 'preempted'); });
  }

  setSkinAttr(skin);
  syncSkin();
  console.log('[Week] ready (inert)');
})();
