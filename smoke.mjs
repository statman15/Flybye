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
  res.writeHead(200, { 'content-type': types[extname(file)] || 'application/octet-stream' }).end(body);
}).listen(0);
await new Promise(r => server.once('listening', r));
const origin = `http://localhost:${server.address().port}`;

// The fake Firebase: same exports app code uses, state in window.__fake (docs by path, signed-in user, write log).
const stubs = {
  'firebase-app.js': `export const initializeApp = () => ({});`,
  'firebase-auth.js': `
    const F = () => window.__fake, subs = [];
    export const getAuth = () => ({ get currentUser() { return F().user; } });
    export const onAuthStateChanged = (a, cb) => { subs.push(cb); setTimeout(() => cb(F().user), 0); return () => {}; };
    export const signInWithPopup = async () => { F().user = { email: F().popupEmail }; subs.forEach(cb => cb(F().user)); };
    export const signInWithCredential = signInWithPopup;
    export const signOut = async () => { F().user = null; subs.forEach(cb => cb(null)); };
    export class GoogleAuthProvider { static credential() { return {}; } }`,
  'firebase-firestore.js': `
    const D = () => window.__fake.docs, ref = (p) => ({ path: p.join('/') });
    export const getFirestore = () => ({});
    export const doc = (db, ...p) => ref(p), collection = (db, ...p) => ref(p);
    export const getDoc = async r => ({ exists: () => r.path in D(), data: () => structuredClone(D()[r.path]) });
    export const getDocs = async r => ({ docs: Object.keys(D()).filter(k => k.startsWith(r.path + '/')).map(k => ({ id: k.split('/')[1], data: () => structuredClone(D()[k]) })) });
    const log = (op, r, d) => window.__fake.writes.push({ op, path: r.path, data: structuredClone(d) });
    export const setDoc = async (r, d) => { log('set', r, d); D()[r.path] = d; };
    export const updateDoc = async (r, d) => { log('update', r, d); D()[r.path] = { ...D()[r.path], ...d }; };
    export const deleteDoc = async r => { log('delete', r); delete D()[r.path]; };`,
  'firebase-messaging.js': `export const isSupported = async () => false; export const getMessaging = () => ({}); export const getToken = async () => 't';`,
};

const seed = () => ({
  'allow/test@example.test': {},
  'settings/main': { home: 'ORD', trips: { weekend: { enabled: true, weeks: [2, 10] }, '3day': { enabled: true, weeks: [2, 12] }, long: { enabled: true, weeks: [3, 17], nights: [7] } },
    cities: [{ name: 'Denver <b>', airports: ['DEN'], trips: ['weekend'] }] },
  'suggestions/current': { updated: '2026-10-17T12:00:00', windows: [{ id: 'w1', kind: 'weekend', out: '2026-11-06', ret: '2026-11-08', holiday: null,
    picks: [{ code: 'DEN', name: 'Denver <b>', price: 240, usual: 400, minutes: 165, stops: 0, hotel: 130, airline: 'United', wish: true, link: 'https://www.google.com/travel/flights?q=x' }] }],
    top: [{ window_id: 'w1', code: 'DEN', name: 'Denver <b>', price: 240, usual: 400, minutes: 165, stops: 0, hotel: 130, airline: 'United', wish: true, link: 'javascript:alert(1)' }] },
  'labels/a': { title: 'Dentist <img src=x onerror=alert(1)>', start: '2999-01-02', all_day: true, block: true, why: 'Appointment', override: null },
});

const errors = [];
const browser = await puppeteer.launch({ executablePath: chrome, args: ['--no-sandbox'] });
let step = 'launch';
try {
  const open = async (user, hash = '') => {
    const page = await browser.newPage();
    await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
    page.setDefaultTimeout(5000);
    await page.setRequestInterception(true);
    page.on('request', r => {
      const m = /^https:\/\/www\.gstatic\.com\/firebasejs\/[\d.]+\/(firebase-[a-z]+\.js)$/.exec(r.url());
      if (m && stubs[m[1]]) return r.respond({ status: 200, contentType: 'text/javascript', headers: { 'access-control-allow-origin': '*' }, body: stubs[m[1]] });
      if (r.url().startsWith(origin) || r.url().startsWith('data:')) return r.continue();
      errors.push(`unexpected outside request: ${r.url()}`); // offline means offline
      r.abort();
    });
    page.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
    page.on('console', m => m.type() === 'error' && !/Failed to load resource/.test(m.text()) && errors.push(`console.error: ${m.text()}`));
    page.on('requestfailed', r => r.url().startsWith(origin) && errors.push(`failed request: ${r.url()}`));
    page.on('response', r => r.url().startsWith(origin) && r.status() >= 400 && errors.push(`HTTP ${r.status()}: ${r.url()}`));
    page.on('dialog', d => { errors.push(`dialog (XSS?): ${d.message()}`); d.dismiss(); });
    await page.evaluateOnNewDocument(() => { delete Navigator.prototype.serviceWorker; }); // a SW would fetch the real SDK behind our interception (sw.js is syntax-checked separately)
    await page.evaluateOnNewDocument((user, docs) => { window.__fake = { user, popupEmail: 'test@example.test', docs, writes: [] }; }, user, seed());
    await page.goto(origin + '/' + hash);
    return page;
  };
  const run = async (name, fn) => { step = name; await fn(); };
  const text = (page, sel, s) => page.waitForFunction((sel, s) => document.querySelector(sel)?.textContent.includes(s), {}, sel, s);
  const click = (page, sel) => page.waitForSelector(sel, { visible: true }).then(() => page.click(sel));
  const writes = page => page.evaluate(() => window.__fake.writes);

  let page;
  await run('sign-in screen', async () => {
    page = await open(null);
    await text(page, '#gate', 'Sign in with Google');
    await click(page, '[data-act=signin]');
    await text(page, '#trips', 'Top picks');
  });

  await run('trips', async () => {
    const html = await page.$eval('#trips', el => el.innerHTML);
    if (html.includes('<b>') && !html.includes('&#60;b&#62;')) throw new Error('city name was not escaped');
    if (!html.includes('165') && !html.includes('2h 45m')) throw new Error('flight time missing');
    if (!html.includes('40% under usual')) throw new Error('% under usual missing');
    if (html.includes('javascript:')) throw new Error('unsafe link rendered');
  });

  await run('wish list', async () => {
    await click(page, '[data-go=wish]');
    await text(page, '#wish', 'Remove');
    await click(page, '#wish [data-kind=long]');
    await page.waitForFunction(() => document.querySelector('#wish [data-kind=long]')?.classList.contains('on'));
    await click(page, '#wish [data-stops="2"]');
    await page.waitForFunction(() => document.querySelector('#wish [data-stops="2"]')?.getAttribute('aria-pressed') === 'true');
    await page.type('#addCity [name=name]', 'Lisbon');
    await page.type('#addCity [name=airports]', 'lis, x');
    await click(page, '#addCity button');
    await text(page, '#addErr', '3 letters');
    await page.$eval('#addCity [name=airports]', el => { el.value = 'lis'; });
    await click(page, '#addCity button');
    await page.waitForFunction(() => document.querySelectorAll('#wish [data-i]').length === 2);
    const cities = (await page.evaluate(() => window.__fake.docs['settings/main'])).cities;
    if (cities[1].airports[0] !== 'LIS' || cities[0].stops !== 2 || !cities[0].trips.includes('long')) throw new Error('wish list not saved: ' + JSON.stringify(cities));
  });

  await run('settings', async () => {
    await click(page, '[data-go=settings]');
    await text(page, '#settings', 'Turn on alerts');
    await page.$eval('[name="weekend-min"]', el => { el.value = '12'; });
    await click(page, '#setForm button');
    await text(page, '#setErr', 'first smaller');
    await page.$eval('[name="weekend-min"]', el => { el.value = '3'; });
    await click(page, '#setForm button');
    await page.waitForFunction(() => window.__fake.writes.some(w => w.path === 'settings/main' && w.data.trips?.weekend.weeks[0] === 3));
  });

  await run('calendar', async () => {
    await click(page, '[data-go=cal]');
    await text(page, '#cal', 'Blocks');
    const html = await page.$eval('#cal', el => el.innerHTML);
    if (html.includes('<img')) throw new Error('event title was not escaped');
    await click(page, '#cal [data-id=a]');
    await text(page, '#cal', 'Free');
    await text(page, '#cal', 'your call');
    await click(page, '#cal [data-id=a]'); // back to the AI's answer clears the override
    await text(page, '#cal', 'Blocks');
    const ov = (await writes(page)).filter(w => w.path === 'labels/a').map(w => w.data.override);
    if (JSON.stringify(ov) !== '[false,null]') throw new Error('override writes: ' + JSON.stringify(ov));
  });

  await run('push link', async () => {
    page = await open({ email: 'test@example.test' }, '#trip=w1|DEN');
    await page.waitForFunction(() => document.querySelector('.card.hit')).catch(async e => { throw new Error(e.message + ' ' + (await page.evaluate(() => document.body.innerText.slice(0, 200)))); });
  });

  await run('not allowed', async () => {
    page = await open({ email: 'stranger@example.test' });
    await text(page, '#gate', 'isn\u2019t on Flybye');
  });
} catch (e) {
  errors.push(`step "${step}" failed: ${e.message}`);
} finally {
  await browser.close();
  server.close();
}

if (errors.length) { console.error(`FAIL (${errors.length}):\n  ${[...new Set(errors)].join('\n  ')}`); process.exit(1); }
console.log('PASS smoke: sign-in, trips, wish list edits, settings validation + save, calendar override, push deep link, not-allowed screen, no console errors');
