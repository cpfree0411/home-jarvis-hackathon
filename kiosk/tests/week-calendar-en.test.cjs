// Unit contracts for the Weekly Calendar Visual Reaction, ported from the
// production suite with fictional data and the English labels of this public
// build: Korea-time week arithmetic (Monday start, month/year boundaries,
// independent of the device zone), event-to-day expansion (all-day exclusive
// ends, midnight ends, overnight events, holiday annotation, dedupe), labels,
// stable identity, skins and the renderer routing contract.
//
//   node kiosk/tests/week-calendar-en.test.cjs        (run from the repo root)
//   TZ=America/Los_Angeles node kiosk/tests/week-calendar-en.test.cjs

const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

function stubEl() {
  return {
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    dataset: {}, style: {}, children: [],
    querySelector() { return stubEl(); }, querySelectorAll() { return []; },
    replaceChildren() {}, appendChild() {}, setAttribute() {}, removeAttribute() {},
    getBoundingClientRect() { return { left: 0, top: 0, width: 0, height: 0, right: 0 }; },
  };
}
const root = stubEl();
root.dataset.skin = 'riso';
const fetched = [];
let savedSkin = 'moonlight';
function fakeFetch(url, opts) {
  fetched.push([String(url), opts && opts.body]);
  const body = String(url).endsWith('/week-skin') ? { ok: true, skin: savedSkin } : { ok: true };
  return Promise.resolve({ json: () => Promise.resolve(body) });
}
const sandbox = {
  console: { log() {}, error: console.error, warn() {} },
  document: { getElementById: (id) => (id === 'week-calendar' ? root : null), body: { dataset: {} } },
  window: {}, Date, Math, JSON, Object, Array, String, Number, isNaN, parseInt,
  setTimeout, clearTimeout, setInterval, clearInterval, Promise, fetch: fakeFetch,
};
sandbox.window = sandbox;
sandbox.window.matchMedia = () => ({ matches: false });
sandbox.window.addEventListener = () => {};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('kiosk/web/week-calendar.js', 'utf8'), sandbox);
const W = sandbox.jarvisWeekCalendar;
assert.ok(W, 'module exposes window.jarvisWeekCalendar');
const T = W._test;
// Values made inside the vm context are a different realm; compare as data.
const plain = (v) => JSON.parse(JSON.stringify(v));

// ---------------------------------------------------------------- weeks
assert.equal(T.mondayOf('2026-10-15'), '2026-10-12', 'Thursday -> its Monday');
assert.equal(T.mondayOf('2026-10-12'), '2026-10-12', 'Monday is its own week start');
assert.equal(T.mondayOf('2026-10-18'), '2026-10-12', 'Sunday ends the week (Monday-first)');
assert.equal(T.mondayOf('2026-11-01'), '2026-10-26', 'month boundary');
assert.equal(T.mondayOf('2027-01-01'), '2026-12-28', 'year boundary');
assert.equal(T.isoAdd('2026-12-28', 7), '2027-01-04');
assert.equal(T.isoAdd('2028-02-28', 1), '2028-02-29', 'leap day');
assert.equal(T.weekdayIndex('2026-10-18'), 6);
// 2026-10-15T15:30Z is 00:30 on the 16th in Korea, whatever the device zone.
assert.equal(T.isoOfMs(Date.parse('2026-10-15T15:30:00Z')), '2026-10-16');
assert.equal(T.isoOfMs(Date.parse('2026-10-15T14:59:00Z')), '2026-10-15');

// ------------------------------------------------------------ day ranges
const ev = (o) => Object.assign({ id: 'c:u::' + o.start, calendar_id: 'c', title: 't', writable: true }, o);
assert.deepEqual(plain(T.dayRange(ev({ all_day: true, start: '2026-10-14', end: '2026-10-17' }))),
  ['2026-10-14', '2026-10-16'], 'all-day end date is exclusive');
assert.deepEqual(plain(T.dayRange(ev({ all_day: true, start: '2026-10-14', end: '2026-10-14' }))),
  ['2026-10-14', '2026-10-14'], 'degenerate all-day stays one day');
assert.deepEqual(plain(T.dayRange(ev({ start: '2026-10-13T00:00:00+09:00', end: '2026-10-14T00:00:00+09:00' }))),
  ['2026-10-13', '2026-10-13'], 'a timed end on midnight belongs to the day before');
assert.deepEqual(plain(T.dayRange(ev({ start: '2026-10-18T22:30:00+09:00', end: '2026-10-19T01:00:00+09:00' }))),
  ['2026-10-18', '2026-10-19'], 'overnight event touches both days');

// ------------------------------------------------------------- indexing
T.setProfiles({ alex: { id: 'alex', label: 'Alex' }, sam: { id: 'sam', label: 'Sam' } },
  { alex: { writable: true }, sam: { writable: true },
    holiday: { writable: false }, birthdays: { writable: true } });
const events = [
  ev({ calendar_id: 'alex', title: 'Lisbon trip', all_day: true, start: '2026-10-10', end: '2026-10-14' }),
  ev({ calendar_id: 'sam', title: 'Day off', start: '2026-10-13T00:00:00+09:00', end: '2026-10-14T00:00:00+09:00' }),
  ev({ calendar_id: 'alex', title: 'Late movie', start: '2026-10-18T22:30:00+09:00', end: '2026-10-19T01:00:00+09:00' }),
  ev({ calendar_id: 'holiday', title: 'Sample holiday', all_day: true, start: '2026-10-09', end: '2026-10-10', writable: false }),
  ev({ calendar_id: 'holiday', title: 'Test holiday', all_day: true, start: '2026-10-16', end: '2026-10-17', writable: false }),
  ev({ calendar_id: 'alex', title: 'Meeting', start: '2026-10-15T09:00:00+09:00', end: '2026-10-15T10:00:00+09:00' }),
  ev({ id: 'dup', calendar_id: 'alex', title: 'Meeting', start: '2026-10-15T09:00:00+09:00', end: '2026-10-15T10:00:00+09:00' }),
  ev({ calendar_id: 'sam', title: 'Meeting', start: '2026-10-15T09:00:00+09:00', end: '2026-10-15T10:00:00+09:00' }),
];
const ix = T.indexWeek(events, '2026-10-12');
assert.deepEqual(plain(Object.keys(ix.byDate)), ['2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16', '2026-10-17', '2026-10-18'],
  'seven days, Monday first, empty days kept');
assert.equal(ix.byDate['2026-10-12'][0].ev.title, 'Lisbon trip', 'a trip that began last week shows from Monday');
assert.equal(ix.byDate['2026-10-14'].length, 0, 'the trip ends on the exclusive end date');
assert.equal(ix.byDate['2026-10-13'].length, 2);
assert.equal(ix.byDate['2026-10-18'][0].ev.title, 'Late movie', 'overnight event clipped to the visible week');
assert.equal(ix.labels['2026-10-16'], 'Test holiday', 'a holiday annotates the date');
assert.equal(ix.byDate['2026-10-16'].length, 0, 'and is not an event line');
assert.equal(ix.byDate['2026-10-15'].length, 2, 'same title+time on one person is one line; another person keeps theirs');

// --------------------------------------------------------------- labels
const day13 = ix.byDate['2026-10-13'];
const off = day13.find((e) => e.ev.title === 'Day off');
assert.equal(T.whenLabel(off), 'All day', '00:00–24:00 reads as all day');
assert.equal(T.whenLabel(day13.find((e) => e.ev.title === 'Lisbon trip')), 'All day · continues');
assert.equal(T.whenLabel(ix.byDate['2026-10-12'][0]), 'All day · continues', 'a trip continuing from last week');
assert.equal(T.whenLabel(ix.byDate['2026-10-18'][0]), 'from 22:30');
assert.equal(T.whenLabel(ix.byDate['2026-10-15'][0]), '09:00–10:00');
const next = T.indexWeek(events, '2026-10-19');
assert.equal(T.whenLabel(next.byDate['2026-10-19'][0]), '~ 01:00');

// ------------------------------------------------------------- identity
assert.equal(T.stableKey({ id: 'alex:event-1::2026-10-17T11:00:00+09:00', start: '2026-10-17T11:00:00+09:00' }),
  'alex:event-1:', 'identity survives a date move');
assert.equal(T.stableKey({ id: 'x', start: 'y' }), 'x');

// ----------------------------------------------------------- week label
assert.match(T.weekLabel(T.mondayOf(T.isoOfMs(Date.now()))), /^This week  ·  [A-Z][a-z]{2} \d{1,2} – /);

// --------------------------------------------------------------- inert
assert.equal(W.state, 'closed');
assert.equal(W.listening, false, 'a closed week registers no input listeners');
assert.deepEqual(JSON.parse(JSON.stringify(W.context())), { calendar_open: false });

// ------------------------------------------------- routing contract (app.js)
const app = fs.readFileSync('kiosk/web/app.js', 'utf8');
assert.match(app, /function routeCalendarMessage\(msg\)/);
assert.match(app, /msg\.view \|\| \(weekOpen \? 'week' : 'month'\)/, 'no view keeps the month meaning unless the week is up');
assert.match(app, /msg\.event === 'proposal'/, 'a new question goes to one calendar');

// ---------------------------------------------------------------- skins
assert.deepEqual(plain(T.skins), ['riso', 'linen', 'moonlight', 'tape', 'ribbon'], 'exactly the five approved skins');
{
  // Every skin is a self-contained, scoped stylesheet: it is linked once, it
  // declares how its slats travel, it names the faces it waits for, and no
  // rule can reach outside its own data-skin (so adding one never touches
  // another).
  const html = fs.readFileSync('kiosk/web/index.html', 'utf8');
  const js = fs.readFileSync('kiosk/web/week-calendar.js', 'utf8');
  for (const name of plain(T.skins)) {
    const file = 'kiosk/web/week-skin-' + name + '.css';
    assert.ok(fs.existsSync(file), file + ' exists');
    assert.equal(html.split('href="week-skin-' + name + '.css"').length, 2, name + ' linked exactly once');
    assert.match(js, new RegExp('\\n\\s+' + name + ": \\['"), name + ' lists the faces it needs');
    const css = fs.readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
    assert.match(css, /--wk-sweep:\s*(slide|scale)/, name + ' declares its sweep');
    const blocks = css.replace(/@font-face\s*\{[^}]*\}/g, '').replace(/@property[^{]*\{[^}]*\}/g, '');
    for (const rule of blocks.split('}')) {
      const sel = rule.split('{')[0].trim();
      if (!sel) continue;
      for (const part of sel.split(',')) {
        assert.ok(part.trim().startsWith('#week-calendar[data-skin="' + name + '"]') ||
                  part.trim().startsWith('#week-calendar .wk-skin[data-skin="' + name + '"]'),
          name + ': rule outside its skin scope: ' + part.trim());
      }
    }
    for (const m of css.matchAll(/url\("(fonts\/[^"]+)"\)/g)) assert.ok(fs.existsSync('kiosk/web/' + m[1]), m[1] + ' ships');
  }
}
assert.match(app, /msg\.type === 'week_skin'/, 'the renderer listens for skin changes');
(async () => {
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(W.skin, 'moonlight', 'on load the saved skin is worn');
  assert.ok(fetched.some(([u, b]) => u.endsWith('/week-skin/rendered') && JSON.parse(b).skin === 'moonlight'),
    'and the renderer reports what it wears');
  assert.equal(await W.setSkin('ink'), false, 'a skin outside the list is refused');
  assert.equal(await W.setSkin('<style>'), false);
  assert.equal(W.skin, 'moonlight', 'and nothing changes');
  assert.equal(await W.setSkin('LINEN'), true);
  assert.equal(W.skin, 'linen');
  assert.equal(root.dataset.skin, 'linen', 'root wears it');
  for (const name of ['tape', 'ribbon']) {
    assert.equal(await W.setSkin(name.toUpperCase()), true, name + ' can be chosen');
    assert.equal(W.skin, name);
    assert.equal(root.dataset.skin, name, 'root wears ' + name);
    assert.ok(fetched.some(([u, b]) => u.endsWith('/week-skin/rendered') && JSON.parse(b).skin === name), name + ' reported');
  }
  savedSkin = 'garbage';
  await T.syncSkin();
  assert.equal(W.skin, 'riso', 'an unknown saved value falls back to Riso');
    // English labels in this public build.
  assert.equal(T.weekLabel('2026-10-26').replace(/^[^·]*·\s*/, ''), 'Oct 26 – Nov 1' + (new Date().getFullYear() === 2026 ? '' : ', 2026'));
  console.log('week-calendar-en.test.cjs: all assertions passed');
})().catch((e) => { console.error(e); process.exit(1); });
