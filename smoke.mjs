// "Does the app start?" gate: serves web/, replaces Firebase with an in-memory fake, drives the four screens in headless Chrome,
// and fails on any JS or console error. Works offline. Usage: node smoke.mjs [dir]. Chrome: $CHROME_PATH or a standard install.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { extname, join, normalize } from 'node:path';
import puppeteer from 'puppeteer-core';

const root = join(process.cwd(), process.argv[2] || 'web');
const types = { '.js': 'text/javascript', '.json': 'application/json', '.html': 'text/html', '.png': 'image/png', '.webmanifest': 'application/manifest+json', '.css': 'text/css', '.svg': 'image/svg+xml' };
const chrome = [process.env.CHROME_PATH, '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'].find(p => p && existsSync(p));
if (!chrome) { console.error('FAIL: no Chrome found. Set CHROME_PATH.'); process.exit(1); }

const server = http.createServer(async (req, res) => {
  const path = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  const file = normalize(join(root, path.endsWith('/') ? path + 'index.html' : path));
  if (!file.startsWith(root)) { res.writeHead(403).end(); return; }
  let body;
  try { body = await readFile(file); } catch { res.writeHead(404).end(); return; }
  // The real Worker is never called: point the app at the local fake, or at nothing for the "not set up" case.
  if (file.endsWith('version.js') && apkVersion) body = `export const VERSION = '${apkVersion}';`;
  if (file.endsWith('firebase-config.js')) body = body.toString().replace(/TIMES_URL = '[^']*'/, `TIMES_URL = '${configured ? origin + '/times' : ''}'`);
  res.writeHead(200, { 'content-type': types[extname(file)] || 'application/octet-stream' }).end(body);
}).listen(0);
await new Promise(r => server.once('listening', r));
const origin = `http://localhost:${server.address().port}`;

// The fake Firebase: same exports app code uses, state in window.__fake (docs by path, signed-in user, write log).
const stubs = {
  'firebase-app.js': `export const initializeApp = () => ({});`,
  'firebase-auth.js': `
    const F = () => window.__fake, subs = [];
    export const getAuth = () => ({ get currentUser() { const u = F().user; return u && { ...u, getIdToken: async () => 'fake-id-token' }; } });
    export const onAuthStateChanged = (a, cb) => { subs.push(cb); setTimeout(() => cb(F().user), 0); return () => {}; };
    export const signInWithPopup = async () => { F().user = { email: F().popupEmail }; subs.forEach(cb => cb(F().user)); };
    export const signInWithCredential = signInWithPopup;
    export const signOut = async () => { F().user = null; subs.forEach(cb => cb(null)); };
    export class GoogleAuthProvider { static credential() { return {}; } }`,
  'firebase-firestore.js': `
    const D = () => window.__fake.docs, ref = (p) => ({ path: p.join('/'), n: p.length });
    export const getFirestore = () => ({});
    export const doc = (db, ...p) => ref(p), collection = (db, ...p) => ref(p);
    export const where = (f, op, v) => ({ f, op, v });
    export const query = (r, ...c) => ({ ...r, c });
    export const writeBatch = () => { const ops = []; return { set: (r, d) => ops.push(['set', r, d]), commit: async () => { for (const [, r, d] of ops) { log('set', r, d); D()[r.path] = d; } } }; };
    export const getDoc = async r => ({ exists: () => r.path in D(), data: () => structuredClone(D()[r.path]) });
    export const getDocs = async r => ({ docs: Object.keys(D()).filter(k => k.startsWith(r.path + '/') && k.split('/').length === r.n + 1)
      .filter(k => (r.c || []).every(c => (D()[k][c.f] || []).includes(c.v)))
      .map(k => ({ id: k.split('/').pop(), data: () => structuredClone(D()[k]) })) });
    const log = (op, r, d) => window.__fake.writes.push({ op, path: r.path, data: structuredClone(d) });
    export const setDoc = async (r, d) => { log('set', r, d); D()[r.path] = d; };
    export const updateDoc = async (r, d) => { log('update', r, d); D()[r.path] = { ...D()[r.path], ...d }; };
    export const deleteDoc = async r => { log('delete', r); delete D()[r.path]; };`,
  'firebase-messaging.js': `export const isSupported = async () => false; export const getMessaging = () => ({}); export const getToken = async () => 't';`,
};

const KEYS = { serpapi: 'sk-secret', gemini: 'gk-secret', calendars: [{ name: 'Chris <i>', url: 'https://calendar.google.com/calendar/ical/secret-token/basic.ics' }] };
const pick = (extra = {}) => ({ code: 'DEN', name: 'Denver <b>', price: 240, usual: 400, minutes: 165, stops: 0, hotel: 130, airline: 'United', airline_code: 'UA', wish: true, link: 'https://www.google.com/travel/flights?q=x',
  weather: { kind: 'forecast', hi_f: 78.4, lo_f: 64, rain_pct: 20 }, score: { total: 65.5, under_pct: 40, hours: -5.5, wish: 15, holiday: 0, weather: 8, airline: 8 }, ...extra });
const seed = () => ({
  'admins/admin@example.test': {},
  'spaces/s1': { name: 'Home <u>', owner: 'test@example.test', members: ['test@example.test', 'laura@example.test'], created: '2026-10-18T00:00:00Z' },
  'spaces/s1/private/keys': structuredClone(KEYS),
  'spaces/s1/settings/main': { home: 'ORD', trips: { weekend: { enabled: true, weeks: [2, 10] }, '3day': { enabled: true, weeks: [2, 12] }, long: { enabled: true, weeks: [3, 17], nights: [7] } },
    cities: [{ name: 'Denver <b>', airports: ['DEN'], trips: ['weekend'] }], score: { hour_penalty: 2 }, airlines: { prefer: ['UA'], avoid: [] }, weather: { min_f: 65, max_f: 85 } },
  'spaces/s1/suggestions/current': { updated: '2026-10-17T12:00:00', windows: [{ id: 'w1', kind: 'weekend', out: '2026-11-06', ret: '2026-11-08', holiday: null, picks: [pick()] }],
    top: [pick({ window_id: 'w1', link: 'javascript:alert(1)', weather: { kind: 'typical', hi_f: 45, lo_f: 18, rain_pct: 30 } })] },
  'spaces/s1/labels/a': { title: 'Dentist <img src=x onerror=alert(1)>', start: '2999-01-02', all_day: true, block: true, why: 'Appointment', override: null },
  'spaces/s1/meta/activity': { last_run: '2026-10-18T10:00:00Z', next_run: '2026-10-19T10:00:00Z', month: '2026-10', used: 30, cap: 100,
    windows: [{ id: 'w1', searched_at: '2026-10-18T10:01:00Z', picks: 3 }, { id: 'w2 <b>', searched_at: null, picks: 0 }], labelled: 12, blocking: 4, errors: ['Calendar <img src=x onerror=alert(1)> failed'] },
  'spaces/s2': { name: 'Brother', owner: 'multi@example.test', members: ['multi@example.test'] },
  'spaces/s3': { name: 'Fresh', owner: 'fresh@example.test', members: ['fresh@example.test'] },
  'spaces/s3/settings/main': { home: 'MDW', trips: {}, cities: [] },
});

let workerMode = 'ok', workerHits = 0, configured = true, apkVersion = '';
const TIMES = { outbound: [{ airline: 'United <b>', flight_number: 'UA 123', dep: '2026-11-06 07:30', arr: '2026-11-06 09:15', from: 'ORD', to: 'DEN', duration: 165 }],
  return: [{ airline: 'United', flight_number: 'UA 456', dep: '2026-11-08 18:00', arr: '2026-11-08 21:40', from: 'DEN', to: 'ORD', duration: '2h 40m' }], price: 240, booking_link: 'https://www.google.com/travel/flights?q=book' };

const errors = [];
const browser = await puppeteer.launch({ executablePath: chrome, args: ['--no-sandbox'] });
let step = 'launch';
try {
  const open = async (user, hash = '', tweak = d => d) => {
    const page = await browser.newPage();
    await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
    page.setDefaultTimeout(5000);
    await page.setRequestInterception(true);
    page.on('request', r => {
      const m = /^https:\/\/www\.gstatic\.com\/firebasejs\/[\d.]+\/(firebase-[a-z]+\.js)$/.exec(r.url());
      if (m && stubs[m[1]]) return r.respond({ status: 200, contentType: 'text/javascript', headers: { 'access-control-allow-origin': '*' }, body: stubs[m[1]] });
      if (r.url() === origin + '/times') { // the faked Worker (same origin, so no CORS preflight)
        workerHits++;
        if (r.headers().authorization !== 'Bearer fake-id-token' || JSON.parse(r.postData()).sid !== 's1') errors.push('Worker call missing token or space id');
        return workerMode === 'ok' ? r.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(TIMES) }) : r.respond({ status: 500, body: 'nope' });
      }
      if (r.url() === 'https://api.github.com/repos/statman15/Flybye/releases/latest' && apkVersion) // only the APK asks
        return r.respond({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' },
          body: JSON.stringify({ tag_name: 'v1.0.10', assets: [{ name: 'Flybye-1.0.10.apk', browser_download_url: 'https://github.com/statman15/Flybye/releases/download/v1.0.10/Flybye-1.0.10.apk' }] }) });
      if (r.url().startsWith(origin) || r.url().startsWith('data:')) return r.continue();
      errors.push(`unexpected outside request: ${r.url()}`); // offline means offline
      r.abort();
    });
    page.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
    page.on('console', m => m.type() === 'error' && !/Failed to load resource/.test(m.text()) && errors.push(`console.error: ${m.text()}`));
    page.on('requestfailed', r => r.url().startsWith(origin) && errors.push(`failed request: ${r.url()}`));
    page.on('response', r => r.url().startsWith(origin) && r.url() !== origin + '/times' && r.status() >= 400 && errors.push(`HTTP ${r.status()}: ${r.url()}`));
    page.on('dialog', d => { errors.push(`dialog (XSS?): ${d.message()}`); d.dismiss(); });
    await page.evaluateOnNewDocument(() => { delete Navigator.prototype.serviceWorker; }); // a SW would fetch the real SDK behind our interception (sw.js is syntax-checked separately)
    await page.evaluateOnNewDocument(() => { try { localStorage.clear(); } catch { /* fresh phone */ } });
    await page.evaluateOnNewDocument((user, docs) => { window.__fake = { user, popupEmail: 'test@example.test', docs, writes: [] }; }, user, tweak(seed()));
    await page.goto(origin + '/' + hash);
    return page;
  };
  const run = async (name, fn) => { step = name; await fn(); };
  const text = (page, sel, s) => page.waitForFunction((sel, s) => document.querySelector(sel)?.textContent.includes(s), {}, sel, s);
  const click = (page, sel) => page.waitForSelector(sel, { visible: true }).then(() => page.$eval(sel, el => el.click())); // el.click(): the floating dock can cover a real tap target in a 390px-tall scroll
  const writes = page => page.evaluate(() => window.__fake.writes);

  const set = (page, sel, v) => page.$eval(sel, (el, v) => { el.value = v; }, v);
  const dockTab = (page, t) => click(page, `#tabs [data-go=${t}]`);
  const doc = (page, path) => page.evaluate(p => window.__fake.docs[p], path);
  const asTest = () => open({ email: 'test@example.test' });
  let page;
  await run('sign-in screen', async () => {
    page = await open(null);
    await text(page, '#gate', 'Sign in with Google');
    await click(page, '[data-act=signin]');
    await text(page, '#trips', 'Top picks');
  });

  await run('trips: weather, airline, rank, escaping', async () => {
    const html = await page.$eval('#trips', el => el.innerHTML);
    if (html.includes('Denver <b>') || !html.includes('Denver &lt;b&gt;')) throw new Error('city name was not escaped');
    if (!html.includes('2h 45m')) throw new Error('flight time missing');
    if (!html.includes('40% under usual')) throw new Error('% under usual missing');
    if (html.includes('javascript:')) throw new Error('unsafe link rendered');
    if (!html.includes('Forecast 78°/64° · 20% rain')) throw new Error('forecast line missing');
    if (!html.includes('Typically 45°/18° · 30% rain')) throw new Error('typical line missing');
    if (!html.includes('United')) throw new Error('airline missing');
    if (!(await page.$eval('#trips .rank', el => el.hidden))) throw new Error('rank panel should start closed');
    await click(page, '#trips [data-act=rank]');
    await page.waitForFunction(() => !document.querySelector('#trips .rank').hidden);
    const r = await page.$eval('#trips .rank', el => el.textContent);
    if (!/Price vs usual\s*\+40/.test(r) || !/Flight time\s*−5\.5/.test(r) || !/Weather\s*\+8/.test(r) || !/Score\s*65\.5/.test(r)) throw new Error('rank breakdown: ' + r);
  });

  await run('trip details: Worker times, cached 6h', async () => {
    workerMode = 'ok'; workerHits = 0;
    await click(page, '#trips [data-trip] .city');
    await text(page, '#trip', 'UA 456');
    const html = await page.$eval('#trip', el => el.innerHTML);
    if (!html.includes('UA 123') || !html.includes('2h 40m') || !html.includes('2h 45m') || !html.includes('Book')) throw new Error('flight legs missing');
    if (html.includes('United <b>')) throw new Error('Worker text was not escaped');
    await click(page, '#trip .back');
    await text(page, '#trips', 'Top picks');
    await click(page, '#trips [data-trip] .city');
    await text(page, '#trip', 'UA 456');
    if (workerHits !== 1) throw new Error(`expected 1 Worker call (cached), got ${workerHits}`);
    const cached = await page.evaluate(() => Object.keys(localStorage).filter(k => k.startsWith('times:')));
    if (cached.length !== 1) throw new Error('times not cached');
  });

  await run('trip details: Worker failure falls back', async () => {
    workerMode = 'fail';
    page = await asTest();
    await text(page, '#trips', 'Top picks');
    await click(page, '#trips [data-trip] .city');
    await text(page, '#trip', 'Couldn’t get flight times');
    await text(page, '#trip', 'Google Flights');
    workerMode = 'ok';
  });

  await run('trip details: Worker not configured falls back', async () => {
    configured = false;
    page = await asTest();
    await text(page, '#trips', 'Top picks');
    configured = true;
    const hits = workerHits;
    await click(page, '#trips [data-trip] .city');
    await text(page, '#trip', 'aren’t set up');
    if (workerHits !== hits) throw new Error('called the Worker without a URL');
  });

  await run('wish list', async () => {
    page = await asTest();
    await text(page, '#trips', 'Top picks');
    await dockTab(page, 'wish');
    await text(page, '#wish', 'Remove');
    await click(page, '#wish [data-kind=long]');
    await page.waitForFunction(() => document.querySelector('#wish [data-kind=long]')?.classList.contains('on'));
    await click(page, '#wish [data-stops="2"]');
    await page.waitForFunction(() => document.querySelector('#wish [data-stops="2"]')?.getAttribute('aria-pressed') === 'true');
    await page.type('#addCity [name=name]', 'Lisbon');
    await page.type('#addCity [name=airports]', 'lis, x');
    await click(page, '#addCity button');
    await text(page, '#addErr', '3 letters');
    await set(page, '#addCity [name=airports]', 'lis');
    await click(page, '#addCity button');
    await page.waitForFunction(() => document.querySelectorAll('#wish [data-i]').length === 2);
    const cities = (await doc(page, 'spaces/s1/settings/main')).cities;
    if (cities[1].airports[0] !== 'LIS' || cities[0].stops !== 2 || !cities[0].trips.includes('long')) throw new Error('wish list not saved: ' + JSON.stringify(cities));
  });

  await run('settings: trips, weather range, home', async () => {
    await dockTab(page, 'settings');
    await text(page, '#settings', 'Turn on alerts');
    await set(page, '[name="weekend-min"]', '12');
    await click(page, '#setForm button');
    await text(page, '#setErr', 'first smaller');
    await set(page, '[name="weekend-min"]', '3');
    await set(page, '#setForm [name=min_f]', '90');
    await click(page, '#setForm button');
    await text(page, '#setErr', 'first lower');
    await set(page, '#setForm [name=min_f]', '60');
    await set(page, '#setForm [name=max_f]', '80');
    await set(page, '#setForm [name=cap]', '120');
    await click(page, '#setForm button');
    await page.waitForFunction(() => window.__fake.writes.some(w => w.path === 'spaces/s1/settings/main' && w.data.trips?.weekend.weeks[0] === 3 && w.data.weather.min_f === 60 && w.data.weather.max_f === 80
      && w.data.search.cap === 120));
  });

  await run('settings: airlines', async () => {
    await set(page, '#airForm [name=code]', 'u');
    await click(page, '#airForm button');
    await text(page, '#airForm .err', '2 letters or digits');
    await set(page, '#airForm [name=list]', 'avoid');
    await set(page, '#airForm [name=code]', 'nk');
    await click(page, '#airForm button');
    await text(page, '#settings', 'NK Spirit');
    await set(page, '#airForm [name=list]', 'avoid');
    await set(page, '#airForm [name=code]', 'ua');
    await click(page, '#airForm button');
    await text(page, '#airForm .err', 'already on the prefer list');
    await click(page, '#settings [data-act=air-del][data-code=UA]');
    await page.waitForFunction(() => window.__fake.docs['spaces/s1/settings/main'].airlines.prefer.length === 0);
    const a = (await doc(page, 'spaces/s1/settings/main')).airlines;
    if (a.avoid.join() !== 'NK') throw new Error('airlines: ' + JSON.stringify(a));
  });

  await run('settings: members (owner)', async () => {
    await page.waitForSelector('#memberForm');
    await set(page, '#memberForm [name=email]', 'nope');
    await click(page, '#memberForm button');
    await text(page, '#memberForm .err', 'email address');
    await set(page, '#memberForm [name=email]', 'mom@example.test');
    await click(page, '#memberForm button');
    await text(page, '#settings', 'mom@example.test');
    await click(page, '#settings [data-act=mem-del][data-email="mom@example.test"]');
    await page.waitForFunction(() => !document.querySelector('#settings').textContent.includes('mom@example.test'));
    const m = (await doc(page, 'spaces/s1')).members;
    if (m.join() !== 'test@example.test,laura@example.test') throw new Error('members: ' + m);
    if (await page.$('#settings [data-act=mem-del][data-email="test@example.test"]')) throw new Error('owner could be removed');
  });

  await run('settings: keys and calendars (secrets stay out of the page)', async () => {
    if (await page.$eval('#keyForm [name=serpapi]', el => el.type) !== 'password') throw new Error('key field is not a password field');
    if (await page.$eval('#calForm [name=url]', el => el.type) !== 'password') throw new Error('calendar link field is not a password field');
    const html = await page.$eval('#settings', el => el.innerHTML);
    if (html.includes('sk-secret') || html.includes('gk-secret') || html.includes('secret-token')) throw new Error('a secret was rendered');
    if (html.includes('<i>')) throw new Error('calendar name was not escaped');
    await set(page, '#calForm [name=name]', 'Laura');
    await set(page, '#calForm [name=url]', 'http://insecure.example/x.ics');
    await click(page, '#calForm button');
    await text(page, '#calForm .err', 'start with https://');
    await set(page, '#calForm [name=url]', 'https://calendar.google.com/calendar/ical/laura-secret/basic.ics');
    await click(page, '#calForm button');
    await page.waitForFunction(() => window.__fake.docs['spaces/s1/private/keys'].calendars.length === 2);
    await click(page, '#settings [data-act=cal-del][data-i="0"]');
    await page.waitForFunction(() => window.__fake.docs['spaces/s1/private/keys'].calendars.length === 1);
    await click(page, '#keyForm button');
    await text(page, '#keyForm .err', 'Type a key');
    await set(page, '#keyForm [name=gemini]', 'gk-new');
    await click(page, '#keyForm button');
    await page.waitForFunction(() => window.__fake.docs['spaces/s1/private/keys'].gemini === 'gk-new');
    const k = await doc(page, 'spaces/s1/private/keys');
    if (k.serpapi !== 'sk-secret' || k.calendars[0].name !== 'Laura') throw new Error('keys: ' + JSON.stringify(k));
  });

  await run('calendar', async () => {
    await dockTab(page, 'cal');
    await text(page, '#cal', 'Blocks');
    const html = await page.$eval('#cal', el => el.innerHTML);
    if (html.includes('<img')) throw new Error('event title was not escaped');
    await click(page, '#cal [data-id=a]');
    await text(page, '#cal', 'Free');
    await text(page, '#cal', 'your call');
    await click(page, '#cal [data-id=a]'); // back to the AI's answer clears the override
    await text(page, '#cal', 'Blocks');
    const ov = (await writes(page)).filter(w => w.path === 'spaces/s1/labels/a').map(w => w.data.override);
    if (JSON.stringify(ov) !== '[false,null]') throw new Error('override writes: ' + JSON.stringify(ov));
  });

  await run('activity', async () => {
    await dockTab(page, 'activity');
    await text(page, '#activity', 'Searches this month');
    const html = await page.$eval('#activity', el => el.innerHTML), t = await page.$eval('#activity', el => el.textContent);
    if (!/30 of 100, 70 left/.test(t) || !html.includes('width:30%')) throw new Error('searches bar: ' + t);
    if (!/12 events and 4 block/.test(t) || !t.includes('not searched') || !t.includes('3 picks')) throw new Error('activity content: ' + t);
    if (html.includes('<img') || html.includes('w2 <b>')) throw new Error('activity text was not escaped');
    await click(page, '#activity [data-go=cal]');
    await text(page, '#cal', 'Dentist');
  });

  await run('trips: sections by trip type, international split, other cities tucked away', async () => {
    await page.evaluate(() => {
      const s = window.__fake.docs['spaces/s1/suggestions/current'];
      s.windows.push({ id: 'long:2027-01-16:2027-01-23', kind: 'long', out: '2027-01-16', ret: '2027-01-23', holiday: null, picks: [
        { ...s.windows[0].picks[0], code: 'MIA', name: 'Miami', country: 'United States' },
        { ...s.windows[0].picks[0], code: 'CDG', name: 'Paris', country: 'France' },
        { ...s.windows[0].picks[0], code: 'ATL', name: 'Atlanta', country: 'United States', wish: false }] });
    });
    await dockTab(page, 'wish'); await dockTab(page, 'trips');
    await text(page, '#trips', 'Longer trips · International');
    const secs = await page.$$eval('#trips details.kind', ds => ds.map(d => ({ t: d.querySelector('summary').textContent, open: d.open, cities: [...d.querySelectorAll(':scope > .card .city, :scope > .group .city')].map(c => c.textContent), more: [...d.querySelectorAll('details.more .city')].map(c => c.textContent) })));
    const by = t => secs.find(s => s.t.startsWith(t));
    if (secs.some(s => s.open)) throw new Error('sections should start closed');
    if (by('Weekends')?.t.includes('1 date') !== true) throw new Error('weekend section: ' + JSON.stringify(secs));
    const dom = secs.find(s => s.t.startsWith('Longer trips') && !s.t.includes('International')), intl = by('Longer trips · International');
    if (!dom.cities.includes('Miami') || dom.cities.includes('Paris') || !dom.more.includes('Atlanta') || dom.cities.includes('Atlanta')) throw new Error('domestic long: ' + JSON.stringify(dom));
    if (!intl.cities.includes('Paris') || intl.cities.includes('Miami')) throw new Error('international: ' + JSON.stringify(intl));
  });

  await run('pull down to refresh', async () => {
    await dockTab(page, 'trips');
    await text(page, '#trips', 'Top picks');
    await page.evaluate(() => { window.__fake.docs['spaces/s1/suggestions/current'].updated = '2026-10-18T06:00:00-05:00'; window.__fake.docs['spaces/s1/suggestions/current'].top[0].name = 'Pulled City'; });
    await page.evaluate(() => scrollTo(0, 0));
    await page.touchscreen.touchStart(180, 150);
    for (const y of [190, 240, 290]) await page.touchscreen.touchMove(180, y);
    await page.touchscreen.touchEnd();
    await text(page, '#trips', 'Pulled City');
    // Android's WebView may end the pull with touchcancel
    await page.evaluate(() => { window.__fake.docs['spaces/s1/suggestions/current'].top[0].name = 'Cancelled City'; });
    const cdp = await page.createCDPSession();
    const touch = (type, y) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: y == null ? [] : [{ x: 180, y }] });
    await touch('touchStart', 150);
    for (const y of [190, 240, 290]) await touch('touchMove', y);
    await touch('touchCancel');
    await text(page, '#trips', 'Cancelled City');
  });

  await run('APK: update banner when a newer release is out', async () => {
    if (await page.$eval('#update', el => !el.hidden)) throw new Error('web app showed an update banner');
    apkVersion = '1.0.9';
    const p = await asTest();
    await text(p, '#update', '1.0.10 is out');
    if (!(await p.$eval('#update', a => a.href)).endsWith('Flybye-1.0.10.apk')) throw new Error('banner link');
    apkVersion = '1.0.10';
    const q = await asTest();
    await text(q, '#trips', 'Top picks');
    await new Promise(r => setTimeout(r, 300));
    if (await q.$eval('#update', el => !el.hidden)) throw new Error('banner shown for the current version');
    apkVersion = '';
    await p.close(); await q.close();
  });

  await run('no sideways scroll at phone width', async () => {
    await page.setViewport({ width: 360, height: 780, isMobile: true, hasTouch: true }); // a narrow Android phone
    await page.addStyleTag({ content: 'input, select, button, p, span, label, h2, h3 { font-size: 130% !important; }' }); // Android 'larger text'
    await page.evaluate(() => { const k = window.__fake.docs['spaces/s1/private/keys']; k.calendars.push({ name: 'Work calendar with a long name', url: 'https://calendar.google.com/calendar/ical/' + 'x'.repeat(60) + '%40group.calendar.google.com/private-' + 'a'.repeat(32) + '/basic.ics' });
      const s = window.__fake.docs['spaces/s1']; s.members.push('someone.with.a.very.long.address@example-domain.test'); });
    for (const tab of ['trips', 'wish', 'settings', 'cal', 'activity']) {
      await dockTab(page, tab);
      await page.waitForFunction(t => !document.querySelector('#' + t)?.hidden, {}, tab);
      const wide = await page.evaluate(() => {
        // 360, not innerWidth: a phone zooms out to fit overflow, so innerWidth grows with the bug
        const out = [...document.querySelectorAll('body *')].filter(e => e.offsetParent && e.getBoundingClientRect().right > 361);
        return !out.length ? null : out
          .slice(0, 5).map(e => `${e.tagName.toLowerCase()}${e.id ? '#' + e.id : ''}.${[...e.classList].join('.')} (${Math.round(e.getBoundingClientRect().right)}px)`);
      });
      if (wide) throw new Error(`${tab} scrolls sideways: ${wide.join(', ')}`);
      if (process.env.SHOT && tab === 'settings') await page.screenshot({ path: process.env.SHOT, fullPage: true });
    }
  });

  await run('push link (opens the right space)', async () => {
    page = await open({ email: 'multi@example.test' }, '#trip=w1|DEN&space=s1', d => { d['spaces/s1'].members.push('multi@example.test'); return d; });
    await page.waitForFunction(() => document.querySelector('.card.hit')).catch(async e => { throw new Error(e.message + ' ' + (await page.evaluate(() => document.body.innerText.slice(0, 200)))); });
  });

  await run('no space', async () => {
    page = await open({ email: 'stranger@example.test' });
    await text(page, '#gate', 'No Flybye space for this account yet');
    if (await page.$('#gate [data-act=admin]')) throw new Error('non-admin sees Admin');
  });

  await run('space picker', async () => {
    page = await open({ email: 'multi@example.test' }, '', d => { d['spaces/s1'].members.push('multi@example.test'); d['spaces/s2/private/keys'] = structuredClone(KEYS); return d; });
    await text(page, '#gate', 'Pick a space');
    const html = await page.$eval('#gate', el => el.innerHTML);
    if (html.includes('<u>')) throw new Error('space name was not escaped');
    await click(page, '#gate [data-sid=s2]');
    await text(page, '#trips', 'Brother');
    await text(page, '#trips', 'No suggestions yet');
    await dockTab(page, 'settings');
    await click(page, '#settings [data-act=switch]');
    await text(page, '#gate', 'Pick a space');
  });

  await run('setup flow', async () => {
    page = await open({ email: 'fresh@example.test' });
    await text(page, '#setup', 'Set up Fresh');
    await set(page, '#calForm [name=name]', 'Fresh cal');
    await set(page, '#calForm [name=url]', 'https://calendar.google.com/calendar/ical/fresh/basic.ics');
    await click(page, '#calForm button');
    await text(page, '#setup', 'Fresh cal');
    await set(page, '#keyForm [name=serpapi]', 'sk-fresh');
    await click(page, '#keyForm button');
    await text(page, '#setup', 'SerpApi key (saved)');
    await set(page, '#basicForm [name=min_f]', '70');
    await set(page, '#basicForm [name=max_f]', '60');
    await click(page, '#basicForm button');
    await text(page, '#basicForm .err', 'first lower');
    await set(page, '#basicForm [name=home]', 'ord');
    await set(page, '#basicForm [name=max_f]', '88');
    await click(page, '#basicForm button');
    await page.waitForFunction(() => window.__fake.docs['spaces/s3/settings/main'].home === 'ORD' && window.__fake.docs['spaces/s3/settings/main'].weather?.max_f === 88);
    const k = await doc(page, 'spaces/s3/private/keys');
    if (k.serpapi !== 'sk-fresh' || k.calendars.length !== 1) throw new Error('setup keys: ' + JSON.stringify(k));
    await click(page, '#setup [data-act=setup-done]');
    await text(page, '#trips', 'Fresh');
    await dockTab(page, 'wish'); // the rest of the app stays reachable
    await text(page, '#wish', 'No cities yet');
  });

  await run('admin: create and remove a space', async () => {
    page = await open({ email: 'admin@example.test' });
    await text(page, '#gate', 'No Flybye space for this account yet');
    await click(page, '#gate [data-act=admin]');
    await text(page, '#admin', 'Home');
    await set(page, '#adminForm [name=name]', 'Bro <i>');
    await set(page, '#adminForm [name=owner]', 'nope');
    await click(page, '#adminForm button');
    await text(page, '#adminForm .err', 'Google email');
    await set(page, '#adminForm [name=owner]', 'Bro@Example.Test');
    await click(page, '#adminForm button');
    await text(page, '#admin', 'bro@example.test');
    if ((await page.$eval('#admin', el => el.innerHTML)).includes('<i>')) throw new Error('space name was not escaped');
    const made = (await writes(page)).find(w => w.op === 'set' && /^spaces\/[0-9a-f]{20}$/.test(w.path));
    if (!made || made.data.owner !== 'bro@example.test' || made.data.members.join() !== 'bro@example.test') throw new Error('create: ' + JSON.stringify(made));
    const nsid = made.path.split('/')[1], st = await doc(page, `spaces/${nsid}/settings/main`);
    if (!st || st.home !== 'ORD' || st.search.cap !== 230 || st.weather.max_f !== 85 || st.score.airline_bonus !== 8 || st.airlines.prefer.length !== 0 || st.trips.long.nights[0] !== 7) throw new Error('default settings: ' + JSON.stringify(st));
    const sel = `#admin [data-sid="${nsid}"]`;
    await click(page, sel);
    await text(page, '#admin', 'Tap again');
    await click(page, sel);
    await page.waitForFunction(() => !document.querySelector('#admin').textContent.includes('bro@example.test'));
    await click(page, '#admin .back');
    await text(page, '#gate', 'No Flybye space for this account yet');
  });
} catch (e) {
  errors.push(`step "${step}" failed: ${e.message}`);
  try { errors.push("writes: " + JSON.stringify(await (await browser.pages()).at(-1).evaluate(() => window.__fake.writes.slice(-3)))); } catch { /* none */ }
  try { errors.push("page said: " + (await browser.pages()).at(-1).evaluate(() => document.body.innerText.slice(0, 1500)).then ? await (await browser.pages()).at(-1).evaluate(() => document.body.innerText.slice(0, 1500)) : ""); } catch { /* page gone */ }
} finally {
  await browser.close();
  server.close();
}

if (errors.length) { console.error(`FAIL (${errors.length}):\n  ${[...new Set(errors)].join('\n  ')}`); process.exit(1); }
console.log('PASS smoke: sign-in, trips (weather, airline, rank), trip details (Worker, cache, fallbacks), wish list, settings (weather, airlines, members, keys, calendars), calendar, activity, push link, no space, picker, setup, admin, no console errors');
