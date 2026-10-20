import { $, esc, money, dur, day, toDate, safeUrl } from './ui.js';
import { auth, db, onAuthStateChanged, signInWithPopup, signInWithCredential, GoogleAuthProvider, signOut,
  doc, getDoc, getDocs, collection, query, where, writeBatch, setDoc, updateDoc, deleteDoc, webPushToken } from './fb.js';
import { TIMES_URL } from './firebase-config.js';
import { VERSION } from './version.js';

const cap = window.Capacitor;
const native = cap?.isNativePlatform?.();
const KINDS = { weekend: 'Weekend', '3day': '3-day weekend', long: 'Longer trip' };
const AIRLINES = { AA: 'American', DL: 'Delta', UA: 'United', WN: 'Southwest', B6: 'JetBlue', AS: 'Alaska', NK: 'Spirit', F9: 'Frontier', G4: 'Allegiant', HA: 'Hawaiian' };
// Mirrors config.yaml: what a new space starts with, so its owner can open Setup -> Basics right away.
const DEFAULT_SETTINGS = { home: 'ORD',
  trips: { weekend: { enabled: true, weeks: [2, 10] }, '3day': { enabled: true, weeks: [2, 12] }, long: { enabled: true, weeks: [3, 17], nights: [7] } },
  cities: [], search: { cap: 230, adults: 2, stops: 1, long_areas: [null, '/m/02j9z', '/m/0j0k'], confirm_per_run: 2 },
  alerts: { deal_ratio: 0.8, max_instant_per_week: 2, repeat_drop: 0.9 },
  score: { hour_penalty: 2, wish_bonus: 10, holiday_bonus: 5, weather_bonus: 10, airline_bonus: 8 },
  airlines: { prefer: [], avoid: [] }, weather: { min_f: 65, max_f: 85 } };
const AIRPORT = /^[A-Z]{3}$/, IATA = /^[A-Z0-9]{2}$/, EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Session state: who is signed in, which spaces they are in, and the one they are looking at.
let me = '', isAdmin = false, spaces = [], S = null, tab = 'trips', sugg = null, tripKey = '', armed = '';
const sref = (...p) => doc(db, 'spaces', S.sid, ...p);
const settingsRef = () => sref('settings', 'main');
const keysRef = () => sref('private', 'keys');

const guard = (el, fn) => fn().catch(e => { el.innerHTML = `<div class="empty"><h2>Couldn’t load</h2><p class="err">${esc(e.message)}</p></div>`; });
const store = { get: k => { try { return localStorage.getItem(k); } catch { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode: the toggle just isn't remembered */ } } };

let toastTimer;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 3500);
}

// Read-modify-write, so an edit never clobbers a field the other phone just changed. fn gets the doc's data and returns the fields to change.
async function mut(ref, fn, missing = 'Nothing saved there yet.') {
  const snap = await getDoc(ref);
  if (!snap.exists()) throw new Error(missing);
  await updateDoc(ref, fn(snap.data()));
}
const mutate = fn => mut(settingsRef(), fn, 'No settings yet. The daily run creates them the first time it runs.');
// Keys doc: created on first save.
async function writeKeys(fn) {
  const snap = await getDoc(keysRef());
  const patch = fn(snap.exists() ? snap.data() : {});
  if (snap.exists()) await updateDoc(keysRef(), patch); else await setDoc(keysRef(), { serpapi: '', gemini: '', calendars: [], ...patch });
}
const getKeys = async () => { const s = await getDoc(keysRef()); return s.exists() ? s.data() : {}; };

// --- Sign in. Android: native Google sign-in (Google blocks it inside WebViews), then the web SDK takes the idToken so Firestore sees the same user.
// Known risk: the web popup inside an iPhone home-screen app on github.io. If it fails on Laura's phone, move to Firebase Hosting (same-site authDomain).
async function signIn() {
  if (native) {
    const r = await cap.Plugins.FirebaseAuthentication.signInWithGoogle();
    await signInWithCredential(auth, GoogleAuthProvider.credential(r.credential.idToken));
  } else {
    await signInWithPopup(auth, new GoogleAuthProvider());
  }
}
async function logOut() {
  if (native) await cap.Plugins.FirebaseAuthentication.signOut().catch(() => {});
  await signOut(auth);
}

function showGate(html) {
  for (const s of document.querySelectorAll('main > [data-tab]')) { s.hidden = s.dataset.tab !== 'gate'; if (s.id !== 'gate') s.innerHTML = ''; }
  $('#dock').hidden = true;
  $('#gate').innerHTML = html;
  scrollTo(0, 0);
}
const gateSignIn = err => showGate(`<div class="head"><h1>Flybye</h1></div>
  <div class="empty"><p>Cheap getaways on the days we’re both free.</p>
  <button class="pill" data-act="signin">Sign in with Google</button>
  <p class="err">${esc(err)}</p></div>`);
const gateNoSpace = () => showGate(`<div class="head"><h1>Flybye</h1></div>
  <div class="empty"><h2>No Flybye space for this account yet.</h2><p>Ask the person who invited you.</p><p>${esc(me)}</p>
  ${isAdmin ? '<button class="pill" data-act="admin">Admin</button>' : ''}
  <button class="pill quiet" data-act="signout">Sign out</button></div>`);
const gateError = msg => showGate(`<div class="head"><h1>Flybye</h1></div>
  <div class="empty"><h2>Couldn’t load your spaces</h2><p class="err">${esc(msg)}</p>
  <button class="pill" data-act="boot">Try again</button><button class="pill quiet" data-act="signout">Sign out</button></div>`);
const gatePicker = () => showGate(`<div class="head"><h1>Pick a space</h1><p class="sub">${esc(me)}</p></div>
  ${spaces.map(s => `<button class="group card pick" data-act="pick" data-sid="${esc(s.sid)}"><span class="city">${esc(s.name)}</span></button>`).join('')}
  ${isAdmin ? '<div class="pad"><button class="pill quiet" data-act="admin">Admin</button></div>' : ''}`);

// --- Tabs. Setup, Admin and Trip are screens, not tabs: no dock button, reached from elsewhere.
const views = { trips: renderTrips, wish: renderWish, settings: renderSettings, cal: renderCal, activity: renderActivity, setup: renderSetup, admin: renderAdmin, trip: renderTrip };
const refresh = () => guard($('#' + tab), views[tab]);
async function go(t) {
  tab = t;
  for (const s of document.querySelectorAll('main > [data-tab]')) { s.hidden = s.dataset.tab !== t; if (s.hidden && s.id !== 'gate') s.innerHTML = ''; }
  for (const b of document.querySelectorAll('#tabs button')) b.setAttribute('aria-selected', b.dataset.go === (t === 'trip' ? 'trips' : t));
  $('#dock').hidden = false;
  await refresh();
  scrollTo(0, 0);
}

// Pull down from the top of a tab to reload it (phones have no reload button in a home-screen app).
// Android's WebView can end the gesture with touchcancel instead of touchend, so the distance comes from touchmove.
let pullY = null, pullTo = null;
addEventListener('touchstart', e => { pullY = pullTo = scrollY <= 0 && e.touches.length === 1 ? e.touches[0].clientY : null; }, { passive: true });
addEventListener('touchmove', e => { if (pullY !== null) pullTo = e.touches[0].clientY; }, { passive: true });
const pullEnd = async () => {
  const pulled = pullY !== null && pullTo - pullY > 80 && !$('#gate:not([hidden])');
  pullY = pullTo = null;
  if (!pulled) return;
  toast('Refreshing…');
  await refresh();
  toast('Up to date');
};
addEventListener('touchend', pullEnd, { passive: true });
addEventListener('touchcancel', pullEnd, { passive: true });

// The APK checks GitHub for a newer release when it opens and shows a banner that downloads it.
async function checkUpdate() {
  if (!VERSION) return;
  const r = await fetch('https://api.github.com/repos/statman15/Flybye/releases/latest').then(r => r.ok ? r.json() : null).catch(() => null);
  const latest = /^v?([\d.]+)$/.exec(r?.tag_name || '')?.[1], apk = (r?.assets || []).find(a => a.name.endsWith('.apk'));
  if (!latest || !apk || !newer(latest, VERSION)) return;
  const b = $('#update');
  b.href = safeUrl(apk.browser_download_url);
  b.textContent = `Flybye ${latest} is out. Tap to update.`;
  b.hidden = false;
}
const newer = (a, b) => { const x = a.split('.').map(Number), y = b.split('.').map(Number); for (let i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0); return false; };

// One click handler for every button that does something, one submit handler for every form.
const acts = {
  signin: async () => { try { await signIn(); } catch (e) { if (!/cancel|closed-by-user|popup-closed/i.test(`${e.code} ${e.message}`)) gateSignIn(e.message); } },
  signout: () => logOut(),
  boot: () => boot(),
  admin: () => go('admin'),
  switch: () => gatePicker(),
  pick: el => startSpace(el.dataset.sid),
  alerts: async () => { try { await enableAlerts(); $('#alertMsg').textContent = 'Alerts are on for this phone.'; toast('Alerts on'); } catch (e) { toast(e.message); } },
  'setup-done': () => go('trips'),
  'air-del': el => act(() => mutate(s => {
    const a = { prefer: [], avoid: [], ...s.airlines };
    a[el.dataset.list] = a[el.dataset.list].filter(c => c !== el.dataset.code);
    return { airlines: a };
  })),
  'mem-del': el => act(async () => {
    await mut(doc(db, 'spaces', S.sid), sp => ({ members: sp.members.filter(m => m !== el.dataset.email || m === sp.owner) }), 'Space not found.');
  }),
  'cal-del': el => act(() => writeKeys(k => ({ calendars: (k.calendars || []).filter((_, i) => i !== +el.dataset.i) }))),
  'admin-del': async el => {
    if (armed !== el.dataset.sid) { armed = el.dataset.sid; el.textContent = 'Tap again to remove'; return; }
    armed = '';
    await act(async () => {
      await deleteDoc(doc(db, 'spaces', el.dataset.sid, 'private', 'keys')); // keys first: the rules refuse the space delete while they exist
      await deleteDoc(doc(db, 'spaces', el.dataset.sid));
    });
  },
  rank: el => { const p = el.nextElementSibling; p.hidden = !p.hidden; el.setAttribute('aria-expanded', !p.hidden); },
};
async function act(fn) { try { await fn(); await refresh(); } catch (e) { toast(e.message); } }

document.addEventListener('click', async ev => {
  const nav = ev.target.closest('[data-go]');
  if (nav) return void go(nav.dataset.go);
  const el = ev.target.closest('[data-act]');
  if (el && acts[el.dataset.act]) await acts[el.dataset.act](el);
});

const forms = {
  addCity: async f => {
    const name = f.name.value.trim(), airports = f.airports.value.toUpperCase().split(/[\s,]+/).filter(Boolean);
    if (!name) throw new Error('Give the city a name.');
    if (!airports.length || !airports.every(a => AIRPORT.test(a))) throw new Error('Airport codes are 3 letters, like MIA, FLL.');
    await mutate(s => {
      const cities = s.cities || [];
      if (cities.some(c => c.name.toLowerCase() === name.toLowerCase())) throw new Error(`${name} is already on the list.`);
      return { cities: [...cities, { name, airports, trips: Object.keys(KINDS) }] };
    });
    await renderWish();
  },
  setForm: async f => {
    const trips = {}, basics = readBasics(f);
    for (const k of Object.keys(KINDS)) {
      const min = +f[`${k}-min`].value, max = +f[`${k}-max`].value;
      if (![min, max].every(n => Number.isInteger(n) && n >= 1 && n <= 52) || min >= max) throw new Error(`${KINDS[k]}: weeks need two whole numbers, the first smaller than the second.`);
      trips[k] = { enabled: f[`${k}-on`].checked, weeks: [min, max] };
    }
    const nights = f.nights.value.split(/[\s,]+/).filter(Boolean).map(Number);
    if (!nights.length || !nights.every(n => Number.isInteger(n) && n >= 1 && n <= 30)) throw new Error('Nights are whole numbers from 1 to 30.');
    trips.long.nights = nights;
    await mutate(s => ({ ...basics(s), trips: Object.fromEntries(Object.entries(trips).map(([k, t]) => [k, { ...(s.trips || {})[k], ...t }])) }));
    toast('Saved');
  },
  basicForm: async f => { await mutate(readBasics(f)); toast('Saved'); },
  airForm: async f => {
    const list = f.list.value, code = f.code.value.trim().toUpperCase();
    if (!IATA.test(code)) throw new Error('Airline codes are 2 letters or digits, like UA or B6.');
    await mutate(s => {
      const a = { prefer: [], avoid: [], ...s.airlines }, other = list === 'prefer' ? 'avoid' : 'prefer';
      if (a[other].includes(code)) throw new Error(`${code} is already on the ${other} list.`);
      if (!a[list].includes(code)) a[list] = [...a[list], code];
      return { airlines: a };
    });
    await renderSettings();
  },
  memberForm: async f => {
    const email = f.email.value.trim().toLowerCase();
    if (!EMAIL.test(email)) throw new Error('That doesn’t look like an email address.');
    await mut(doc(db, 'spaces', S.sid), sp => { if (sp.members.includes(email)) throw new Error(`${email} is already in this space.`); return { members: [...sp.members, email] }; }, 'Space not found.');
    await renderSettings();
  },
  calForm: async f => {
    const name = f.name.value.trim(), url = f.url.value.trim();
    if (!name) throw new Error('Give the calendar a name.');
    let ok = /^https:\/\//i.test(url);
    try { new URL(url); } catch { ok = false; }
    if (!ok) throw new Error('Calendar links start with https://.');
    await writeKeys(k => ({ calendars: [...(k.calendars || []), { name, url }] }));
    await refresh();
  },
  keyForm: async f => {
    const patch = {};
    for (const n of ['serpapi', 'gemini']) if (f[n].value.trim()) patch[n] = f[n].value.trim();
    if (!Object.keys(patch).length) throw new Error('Type a key to save.');
    await writeKeys(() => patch);
    toast('Saved');
    await refresh();
  },
  adminForm: async f => {
    const name = f.name.value.trim(), owner = f.owner.value.trim().toLowerCase();
    if (!name) throw new Error('Give the space a name.');
    if (!EMAIL.test(owner)) throw new Error('The owner needs a Google email address.');
    const sid = crypto.randomUUID().replace(/-/g, '').slice(0, 20), b = writeBatch(db);
    b.set(doc(db, 'spaces', sid), { name, owner, members: [owner], created: new Date().toISOString() });
    b.set(doc(db, 'spaces', sid, 'settings', 'main'), structuredClone(DEFAULT_SETTINGS));
    await b.commit();
    await renderAdmin();
  },
};
document.addEventListener('submit', async ev => {
  const f = ev.target, fn = forms[f.id];
  if (!fn) return;
  ev.preventDefault();
  const err = f.querySelector('.err');
  if (err) err.textContent = '';
  try { await fn(f); } catch (e) { if (err) err.textContent = e.message; else toast(e.message); }
});

// Home airport + the weather range, shared by the Settings form and the setup form.
function readBasics(f) {
  const home = f.home.value.trim().toUpperCase(), min = +f.min_f.value, max = +f.max_f.value;
  if (!AIRPORT.test(home)) throw new Error('Home airport is 3 letters, like ORD.');
  if (![min, max].every(n => Number.isInteger(n) && n >= -20 && n <= 120) || min >= max) throw new Error('Weather range: two whole °F numbers, the first lower than the second.');
  const cap = +f.cap.value;
  if (!Number.isInteger(cap) || cap < 0 || cap > 100000) throw new Error('Searches per month: a whole number (SerpApi’s free plan has 250).');
  return s => ({ home, weather: { min_f: min, max_f: max }, search: { ...s.search, cap } });
}
const basicsFields = s => `<label>Home airport<input name="home" maxlength="3" autocapitalize="characters" value="${esc(s.home)}"></label>
  <div class="two"><label>Ideal high, from (°F)<input type="number" inputmode="numeric" name="min_f" value="${esc(s.weather?.min_f ?? 65)}"></label>
  <label>to (°F)<input type="number" inputmode="numeric" name="max_f" value="${esc(s.weather?.max_f ?? 85)}"></label></div>
  <label>Searches per month<input type="number" inputmode="numeric" min="0" name="cap" value="${esc(s.search?.cap ?? 230)}"></label>
  <p class="hint">The daily run spreads these over the month, and tapping a trip uses 2. SerpApi’s free plan has 250.</p>`;

// --- Trips
const stopsText = n => (n ? `${n} stop${n > 1 ? 's' : ''}` : 'Nonstop');
const deg = n => Math.round(n) + '°';
function wxLine(w) {
  if (!Number.isFinite(w?.hi_f) || !Number.isFinite(w?.lo_f)) return '';
  return `${w.kind === 'forecast' ? 'Forecast' : 'Typically'} ${deg(w.hi_f)}/${deg(w.lo_f)} · ${Math.round(Number.isFinite(w.rain_pct) ? w.rain_pct : 0)}% rain`;
}
const pts = n => (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(Math.round(n * 10) / 10);
function rankHtml(sc) {
  if (!sc || !Number.isFinite(sc.total)) return '';
  // Every part is already signed points from the job (hours = -hour_penalty x flight hours), so the rows add up to the score.
  const rows = [['Price vs usual', sc.under_pct], ['Flight time', sc.hours],
    ['Wish list', sc.wish], ['Holiday', sc.holiday], ['Weather', sc.weather], ['Preferred airline', sc.airline]]
    .filter(([, v]) => Number.isFinite(v) && v !== 0);
  return `<div class="rank" hidden>${rows.map(([l, v]) => `<p><span>${esc(l)}</span><b>${esc(pts(v))}</b></p>`).join('')}<p class="total"><span>Score</span><b>${esc(Math.round(sc.total * 10) / 10)}</b></p></div>`;
}
function pickCard(p, w) {
  const pct = p.usual > 0 ? Math.round((1 - p.price / p.usual) * 100) : 0, wx = wxLine(p.weather);
  return `<article class="group card${p.wish ? '' : ' look'}" data-trip="${esc(w.id)}|${esc(p.code)}">
    <div class="card-top"><span class="city">${esc(p.name)}</span><span class="price">${esc(money(p.price))} <small>per person</small></span></div>
    <p class="meta">${esc(day(w.out))} → ${esc(day(w.ret))}${w.holiday ? ' · ' + esc(w.holiday) : ''}</p>
    <p class="meta">${[dur(p.minutes), stopsText(p.stops), p.airline, p.hotel != null ? 'hotel ' + money(p.hotel) : ''].filter(Boolean).map(esc).join(' · ')}</p>
    ${wx ? `<p class="meta wx">${esc(wx)}</p>` : ''}
    ${pct > 0 ? `<p class="meta deal">${pct}% under usual (${esc(money(p.usual))})</p>` : ''}
    <div class="tags">${p.wish ? '<span class="tag on">Wish list</span>' : '<span class="tag look">Worth a look</span>'}${p.flex ? '<span class="tag" title="Google picked these dates as the cheapest week">Flexible dates</span>' : ''}</div>
    <div class="row"><a class="pill small" href="${esc(safeUrl(p.link))}" target="_blank" rel="noopener noreferrer">Google Flights</a>
    ${p.score ? '<button class="pill small quiet" data-act="rank" aria-expanded="false">Why this rank</button>' + rankHtml(p.score) : ''}</div>
  </article>`;
}

async function renderTrips() {
  const el = $('#trips');
  const snap = await getDoc(sref('suggestions', 'current'));
  if (!snap.exists()) {
    sugg = null;
    el.innerHTML = `<div class="head"><h1>Trips</h1><p class="sub">${esc(S.name)}</p></div><div class="empty"><h2>No suggestions yet</h2><p>The daily search writes them every morning.</p></div>`;
    return;
  }
  const s = sugg = snap.data();
  const top = (s.top || []).map(p => pickCard(p, windowOf(s, p.window_id) || { id: p.window_id }));
  // Sections by trip type (native <details>, closed until tapped); longer trips split at the border.
  const abroad = p => (p.country || '') !== 'United States';
  const sections = [['weekend', 'Weekends', () => true], ['3day', '3-day weekends', () => true],
    ['long', 'Longer trips', p => !abroad(p)], ['long', 'Longer trips · International', abroad]];
  const body = sections.map(([kind, title, keep], i) => {
    const wins = (s.windows || []).filter(w => w.kind === kind)
      .map(w => ({ w, picks: (w.picks || []).filter(keep) })).filter(x => x.picks.length);
    if (!wins.length) return '';
    const html = wins.map(({ w, picks }) => {
      const mine = picks.filter(p => p.wish), others = picks.filter(p => !p.wish);
      return `<h2 class="sec">${esc(day(w.out))} → ${esc(day(w.ret))}${w.holiday ? `<small>${esc(w.holiday)}</small>` : ''}</h2>
        ${mine.map(p => pickCard(p, w)).join('') || '<p class="pad muted">No wish-list city flies nonstop on these dates.</p>'}
        ${others.length ? `<details class="more"><summary>Worth a look (${others.length})<small>Not on your wish list, but good options for these dates</small></summary>${others.map(p => pickCard(p, w)).join('')}</details>` : ''}`;
    }).join('');
    return `<details class="kind" data-sec="${i}"${openSecs.has(i) ? ' open' : ''}><summary>${esc(title)} <small>${wins.length} date${wins.length > 1 ? 's' : ''}</small></summary>${html}</details>`;
  }).join('');
  el.innerHTML = `<div class="head"><h1>Trips</h1><p class="sub">${esc(S.name)} · updated ${esc(s.updated ? toDate(s.updated).toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' }) : 'never')}</p></div>
    ${top.length ? `<h2 class="sec">Top picks</h2>${top.join('')}` : ''}${body || '<div class="empty"><p>No priced trips fit your free dates yet.</p></div>'}`;
  highlight();
}
const windowOf = (s, id) => (s?.windows || []).find(w => w.id === id);
const openSecs = new Set(); // which sections stay open across refreshes
$('#trips').addEventListener('toggle', ev => { const i = Number(ev.target.dataset?.sec); if (!Number.isNaN(i)) ev.target.open ? openSecs.add(i) : openSecs.delete(i); }, true);
$('#trips').addEventListener('click', ev => {
  if (ev.target.closest('a, [data-act]')) return;
  const card = ev.target.closest('[data-trip]');
  if (card) { tripKey = card.dataset.trip; go('trip'); }
});

// #trip=<window_id>|<code>&space=<sid> (from a push) opens that space and scrolls to the card.
const hashParams = () => new URLSearchParams(location.hash.slice(1));
function highlight() {
  const want = hashParams().get('trip');
  if (!want) return;
  const hits = [...document.querySelectorAll('[data-trip]')].filter(c => c.dataset.trip === want);
  document.querySelectorAll('.card.hit').forEach(c => c.classList.remove('hit'));
  hits.forEach(c => { c.classList.add('hit'); for (let d = c.closest('details'); d; d = d.parentElement.closest('details')) d.open = true; });
  hits[0]?.scrollIntoView({ block: 'center' });
}
async function route() {
  if (!auth.currentUser || !hashParams().get('trip')) return;
  const sid = hashParams().get('space');
  if (sid && S?.sid !== sid && spaces.some(s => s.sid === sid)) return startSpace(sid);
  await go('trips');
}
addEventListener('hashchange', route);

// --- Trip details: flight times from the Worker, or the Google Flights link when it isn't there.
const timesUrl = () => {
  const u = String(TIMES_URL || '');
  return /^(https:\/\/|http:\/\/localhost[:/])/.test(u) ? u.replace(/\/+$/, '').replace(/\/times$/, '') + '/times' : null;
};
async function loadTimes(wid, code) {
  const key = `times:${S.sid}:${wid}|${code}`;
  try { const c = JSON.parse(store.get(key)); if (c && Date.now() - c.at < 6 * 3600e3) return c.data; } catch { /* no usable cache */ }
  const url = timesUrl();
  if (!url) throw new Error('unset');
  const r = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json', authorization: 'Bearer ' + await auth.currentUser.getIdToken() },
    body: JSON.stringify({ sid: S.sid, window_id: wid, code }) });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  const data = await r.json();
  if (!Array.isArray(data.outbound) || !Array.isArray(data.return)) throw new Error('bad reply');
  store.set(key, JSON.stringify({ at: Date.now(), data }));
  return data;
}
const when = s => {
  const m = /^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/.exec(s);
  return m ? new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5]).toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' }) : String(s ?? '');
};
const legsHtml = (title, legs) => `<h2 class="sec">${title}</h2>${legs.length ? `<ul class="legs group">${legs.map(l => `<li>
  <b>${esc([l.airline, l.flight_number].filter(Boolean).join(' '))}</b>
  <span>${esc(when(l.dep))} ${esc(l.from)} → ${esc(when(l.arr))} ${esc(l.to)}</span>
  <span class="muted">${esc(typeof l.duration === 'number' ? dur(l.duration) : l.duration)}</span></li>`).join('')}</ul>` : '<p class="pad muted">No flights listed.</p>'}`;

async function renderTrip() {
  const el = $('#trip'), key = tripKey, i = key.lastIndexOf('|'), wid = key.slice(0, i), code = key.slice(i + 1);
  const w = windowOf(sugg, wid) || { id: wid };
  const p = [...(sugg?.top || []), ...(w.picks || [])].find(x => x.window_id === wid && x.code === code) || (w.picks || []).find(x => x.code === code);
  if (!p) return go('trips');
  el.innerHTML = `<div class="head"><button class="back" data-go="trips">‹ Trips</button><h1>${esc(p.name)}</h1>
    <p class="sub">${esc(day(w.out))} → ${esc(day(w.ret))}${w.holiday ? ' · ' + esc(w.holiday) : ''}</p></div>
    <div class="pad"><p class="meta">${[money(p.price) + ' per person', dur(p.minutes), stopsText(p.stops), p.airline].filter(Boolean).map(esc).join(' · ')}</p>
    ${wxLine(p.weather) ? `<p class="meta wx">${esc(wxLine(p.weather))}</p>` : ''}</div>
    <div id="times"><p class="pad muted"><span class="spin" aria-hidden="true"></span> Looking up flight times…</p></div>`;
  let html;
  try {
    const d = await loadTimes(wid, code);
    html = legsHtml('Outbound', d.outbound) + legsHtml('Return', d.return) +
      `<div class="pad">${d.booking_link ? `<a class="pill small" href="${esc(safeUrl(d.booking_link))}" target="_blank" rel="noopener noreferrer">Book</a>` : ''}</div>`;
  } catch (e) {
    html = `<p class="pad muted">${e.message === 'unset' ? 'Flight times aren’t set up yet.' : 'Couldn’t get flight times right now.'} Google Flights has them.</p>
      <div class="pad"><a class="pill small" href="${esc(safeUrl(p.link))}" target="_blank" rel="noopener noreferrer">Google Flights</a></div>`;
  }
  if (tab === 'trip' && tripKey === key) $('#times').innerHTML = html;
}

// --- Wish list
async function renderWish() {
  const el = $('#wish');
  const snap = await getDoc(settingsRef());
  const cities = snap.exists() ? snap.data().cities || [] : [];
  el.innerHTML = `<div class="head"><h1>Wish list</h1><p class="sub">These cities get a score boost and can trigger instant alerts.</p></div>
    ${cities.map((c, i) => `<div class="group card" data-i="${i}">
      <div class="card-top"><span class="city">${esc(c.name)}</span><span class="muted">${esc((c.airports || []).join(', '))}</span></div>
      <div class="tags">${Object.entries(KINDS).map(([k, label]) => `<button class="tag${(c.trips || []).includes(k) ? ' on' : ''}" data-kind="${esc(k)}" aria-pressed="${(c.trips || []).includes(k)}">${esc(label)}</button>`).join('')}</div>
      <div class="seg" role="group" aria-label="Stops"><button data-stops="1" aria-pressed="${c.stops !== 2}">Nonstop</button><button data-stops="2" aria-pressed="${c.stops === 2}">1 stop OK</button></div>
      <button class="remove" data-remove>Remove ${esc(c.name)}</button>
    </div>`).join('') || '<div class="empty"><p>No cities yet.</p></div>'}
    <h2 class="sec">Add a city</h2>
    <form class="group form" id="addCity" novalidate>
      <label>City<input name="name" maxlength="40" autocomplete="off" required></label>
      <label>Airport codes<input name="airports" placeholder="MIA, FLL" autocapitalize="characters" autocomplete="off" required></label>
      <p class="err" id="addErr"></p>
      <button class="pill" type="submit">Add</button>
    </form>`;
}
$('#wish').addEventListener('click', async ev => {
  const card = ev.target.closest('[data-i]');
  if (!card) return;
  const i = +card.dataset.i, name = card.querySelector('.city').textContent;
  const kind = ev.target.closest('[data-kind]')?.dataset.kind, stops = ev.target.closest('[data-stops]')?.dataset.stops;
  if (!kind && !stops && !ev.target.closest('[data-remove]')) return;
  try {
    await mutate(s => {
      const cities = s.cities || [];
      if (cities[i]?.name !== name) throw new Error('The list changed on the other phone. Reopen this tab.');
      const c = cities[i];
      if (kind) c.trips = (c.trips || []).includes(kind) ? c.trips.filter(k => k !== kind) : [...(c.trips || []), kind];
      else if (stops) { if (stops === '2') c.stops = 2; else delete c.stops; }
      else cities.splice(i, 1);
      return { cities };
    });
    await renderWish();
  } catch (e) { toast(e.message); }
});

// --- Calendars + keys blocks (Settings and Setup both show them). Keys are never put back into the page: the fields stay empty and blank means "keep".
const host = u => { try { return new URL(u).host; } catch { return ''; } };
const calBlock = k => `<h2 class="sec">Calendars<small>A trip is free only if every calendar here is free.</small></h2>
  ${(k.calendars || []).map((c, i) => `<div class="group card card-top"><span><span class="city">${esc(c.name)}</span><br><span class="muted">${esc(host(c.url))}</span></span>
    <button class="tag" data-act="cal-del" data-i="${i}" aria-label="Remove ${esc(c.name)}">Remove</button></div>`).join('') || '<p class="pad muted">No calendars yet.</p>'}
  <form class="group form" id="calForm" novalidate>
    <label>Name<input name="name" maxlength="40" autocomplete="off" placeholder="Chris, Laura, Work…"></label>
    <label>Secret iCal link<input name="url" type="password" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="https://calendar.google.com/…"></label>
    <p class="hint">Google Calendar on a computer → Settings → pick the calendar → Integrate calendar → “Secret address in iCal format”. Anyone with this link can read the calendar, so don’t share it.</p>
    <p class="err"></p><button class="pill" type="submit">Add calendar</button></form>`;
const keysBlock = k => `<h2 class="sec">Keys<small>Used only for this space’s searches.</small></h2>
  <form class="group form" id="keyForm" novalidate>
    <label>SerpApi key${k.serpapi ? ' (saved)' : ''}<input name="serpapi" type="password" autocomplete="off" spellcheck="false" placeholder="${k.serpapi ? 'Leave blank to keep' : 'Paste key'}"></label>
    <p class="hint"><a href="https://serpapi.com/manage-api-key" target="_blank" rel="noopener noreferrer">Where to get it</a> (finds the flights)</p>
    <label>Gemini key${k.gemini ? ' (saved)' : ''}<input name="gemini" type="password" autocomplete="off" spellcheck="false" placeholder="${k.gemini ? 'Leave blank to keep' : 'Paste key'}"></label>
    <p class="hint"><a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer">Where to get it</a> (reads which events block a trip)</p>
    <p class="err"></p><button class="pill" type="submit">Save keys</button></form>`;

// --- Setup: a space with no keys or calendars lands here. The rest of the app stays reachable from the dock.
async function renderSetup() {
  const el = $('#setup');
  const [k, snap] = await Promise.all([getKeys(), getDoc(settingsRef())]);
  const s = snap.exists() ? snap.data() : null;
  el.innerHTML = `<div class="head"><h1>Set up ${esc(S.name)}</h1><p class="sub">Add your calendars and keys, then the daily search can start.</p></div>
    ${calBlock(k)}${keysBlock(k)}
    <h2 class="sec">Basics</h2>
    ${s ? `<form class="group form" id="basicForm" novalidate>${basicsFields(s)}<p class="err"></p><button class="pill" type="submit">Save</button></form>`
      : '<p class="pad muted">Home airport and weather range appear here after the first daily run creates your settings.</p>'}
    <div class="pad"><button class="pill quiet" data-go="wish">Wish list</button> <button class="pill" data-act="setup-done">Done</button></div>`;
}

// --- Settings
const chips = (list, name) => (list || []).map(c => `<button class="tag on" data-act="air-del" data-list="${name}" data-code="${esc(c)}" aria-label="Remove ${esc(c)}">${esc(c)}${AIRLINES[c] ? ' ' + esc(AIRLINES[c]) : ''} ×</button>`).join('') || '<span class="muted">None</span>';
async function renderSettings() {
  const el = $('#settings');
  const [snap, k, sp] = await Promise.all([getDoc(settingsRef()), getKeys(), getDoc(doc(db, 'spaces', S.sid))]);
  if (sp.exists()) S = { sid: S.sid, ...sp.data() };
  const s = snap.exists() ? snap.data() : null, owner = me === S.owner;
  const kinds = s ? Object.entries(KINDS).map(([k, label]) => {
    const t = (s.trips || {})[k] || {};
    return `<div class="kind"><label class="check"><input type="checkbox" name="${k}-on"${t.enabled ? ' checked' : ''}>${esc(label)}</label>
      <div class="two"><label>Weeks ahead, from<input type="number" inputmode="numeric" min="1" max="52" name="${k}-min" value="${esc(t.weeks?.[0])}"></label>
      <label>to<input type="number" inputmode="numeric" min="1" max="52" name="${k}-max" value="${esc(t.weeks?.[1])}"></label></div>
      ${k === 'long' ? `<label style="margin-top:12px">Nights (e.g. 7 or 5, 9)<input name="nights" value="${esc((t.nights || []).join(', '))}"></label>` : ''}</div>`;
  }).join('') : '';
  const air = { prefer: [], avoid: [], ...s?.airlines };
  el.innerHTML = `<div class="head"><h1>Settings</h1><p class="sub">${esc(me)} · ${esc(S.name)}</p></div>
    ${s ? `<form class="group form" id="setForm" novalidate>${kinds}${basicsFields(s)}
      <p class="err" id="setErr"></p><button class="pill" type="submit">Save</button></form>
      <h2 class="sec">Airlines<small>Preferred airlines rank higher. Avoided ones are hidden.</small></h2>
      <div class="group card"><p class="meta" style="margin:0 0 6px">Prefer</p><div class="tags">${chips(air.prefer, 'prefer')}</div>
        <p class="meta" style="margin:12px 0 6px">Avoid</p><div class="tags">${chips(air.avoid, 'avoid')}</div></div>
      <form class="group form" id="airForm" novalidate>
        <div class="two"><label>List<select name="list"><option value="prefer">Prefer</option><option value="avoid">Avoid</option></select></label>
        <label>Airline code<input name="code" maxlength="2" autocapitalize="characters" autocomplete="off" placeholder="UA"></label></div>
        <p class="hint">${Object.entries(AIRLINES).map(([c, n]) => esc(`${c} ${n}`)).join(' · ')}</p>
        <p class="err"></p><button class="pill" type="submit">Add airline</button></form>`
      : '<div class="empty"><p>No settings yet. The daily run creates them the first time it runs.</p></div>'}
    ${calBlock(k)}${keysBlock(k)}
    <h2 class="sec">Members<small>${owner ? 'People who share this space see the same trips and get the same alerts.' : 'Only the owner can change this.'}</small></h2>
    <ul class="group legs">${(S.members || []).map(m => `<li><span>${esc(m)}${m === S.owner ? ' <span class="muted">owner</span>' : ''}</span>
      ${owner && m !== S.owner ? `<button class="tag" data-act="mem-del" data-email="${esc(m)}">Remove</button>` : ''}</li>`).join('')}</ul>
    ${owner ? `<form class="group form" id="memberForm" novalidate><label>Add a member’s Google email<input name="email" type="email" autocapitalize="none" autocomplete="off"></label>
      <p class="err"></p><button class="pill" type="submit">Add member</button></form>` : ''}
    <h2 class="sec">Alerts</h2>
    <div class="group card"><p class="meta" style="margin:0 0 10px" id="alertMsg">${store.get('alerts') ? 'Alerts are on for this phone.' : 'Get a push when a wish-list fare drops, and the Sunday top picks.'}</p>
      <button class="pill" data-act="alerts">Turn on alerts</button></div>
    <div class="pad" style="margin-top:20px;display:flex;gap:8px;flex-wrap:wrap">
      ${spaces.length > 1 ? '<button class="pill quiet" data-act="switch">Switch space</button>' : ''}
      ${isAdmin ? '<button class="pill quiet" data-act="admin">Admin</button>' : ''}
      <button class="pill quiet" data-act="signout">Sign out</button></div>`;
}

// --- Admin: every space, create one, remove one.
async function renderAdmin() {
  const el = $('#admin');
  const all = (await getDocs(collection(db, 'spaces'))).docs.map(d => ({ sid: d.id, ...d.data() }));
  armed = '';
  el.innerHTML = `<div class="head"><button class="back" data-act="boot">‹ Back</button><h1>Admin</h1><p class="sub">Spaces</p></div>
    ${all.map(s => `<div class="group card card-top"><span><span class="city">${esc(s.name)}</span><br><span class="muted">${esc(s.owner)} · ${esc((s.members || []).length)} member${(s.members || []).length === 1 ? '' : 's'}</span></span>
      <button class="tag" data-act="admin-del" data-sid="${esc(s.sid)}">Remove</button></div>`).join('') || '<div class="empty"><p>No spaces yet.</p></div>'}
    <h2 class="sec">New space</h2>
    <form class="group form" id="adminForm" novalidate>
      <label>Name<input name="name" maxlength="40" autocomplete="off"></label>
      <label>Owner’s Google email<input name="owner" type="email" autocapitalize="none" autocomplete="off"></label>
      <p class="err"></p><button class="pill" type="submit">Create space</button></form>`;
}

// --- Activity: what the daily run did.
const stamp = s => { const d = s ? new Date(s) : null; return d && !isNaN(d) ? d.toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '—'; };
async function renderActivity() {
  const el = $('#activity');
  const snap = await getDoc(sref('meta', 'activity'));
  if (!snap.exists()) {
    el.innerHTML = `<div class="head"><h1>Activity</h1></div><div class="empty"><h2>Nothing yet</h2><p>This fills in after the first daily run.</p></div>`;
    return;
  }
  const a = snap.data(), used = Number(a.used) || 0, capN = Number(a.cap) || 0, pct = capN > 0 ? Math.min(100, Math.round(used / capN * 100)) : 0;
  el.innerHTML = `<div class="head"><h1>Activity</h1><p class="sub">${esc(S.name)}</p></div>
    <div class="group card"><p class="meta" style="margin:0">Last run <b>${esc(stamp(a.last_run))}</b></p><p class="meta">Next run <b>${esc(stamp(a.next_run))}</b></p></div>
    <div class="group card"><p class="meta" style="margin:0">Searches this month${a.month ? ' (' + esc(a.month) + ')' : ''}: <b>${esc(used)}</b> of ${esc(capN)}, ${esc(Math.max(0, capN - used))} left</p>
      <div class="bar" role="img" aria-label="${pct}% of searches used"><i style="width:${pct}%"></i></div></div>
    <div class="group card"><p class="meta" style="margin:0">The AI labelled <b>${esc(a.labelled ?? 0)}</b> events and <b>${esc(a.blocking ?? 0)}</b> block trips.</p>
      <button class="pill small quiet" data-go="cal">See them on Calendar</button></div>
    <h2 class="sec">Windows checked</h2>
    <ul class="legs group">${(a.windows || []).map(w => `<li><span>${esc(w.id)}</span><span class="muted">${w.searched_at ? esc(stamp(w.searched_at)) + ' · ' + esc(w.picks ?? 0) + ' picks' : 'not searched'}</span></li>`).join('') || '<li class="muted">None</li>'}</ul>
    <h2 class="sec">Errors</h2>
    ${(a.errors || []).length ? `<ul class="legs group errs">${a.errors.map(e => `<li class="err">${esc(e)}</li>`).join('')}</ul>` : '<p class="pad muted">None. All good.</p>'}`;
}

// --- Push. Android: Capacitor FirebaseMessaging. iPhone home-screen web app: FCM web token through sw.js (which also draws the notification).
async function registerDevice(token, platform) {
  await setDoc(sref('devices', token), { platform, email: me, at: new Date().toISOString() });
  store.set('alerts', '1');
}
async function enableAlerts() {
  if (native) {
    const M = cap.Plugins.FirebaseMessaging;
    if ((await M.requestPermissions()).receive !== 'granted') throw new Error('Notifications are blocked for Flybye in Android settings.');
    return registerDevice((await M.getToken()).token, 'android');
  }
  const homeScreen = new Error('On iPhone, add Flybye to the Home Screen first.');
  if (!('Notification' in window) || !('serviceWorker' in navigator)) throw homeScreen;
  const perm = await Notification.requestPermission(); // first await, so Safari still counts it as the tap's doing
  if (perm !== 'granted') throw new Error('Notifications are blocked for Flybye in this phone’s settings.');
  await navigator.serviceWorker.register('sw.js');
  const token = await webPushToken(await navigator.serviceWorker.ready);
  if (!token) throw homeScreen;
  return registerDevice(token, 'web');
}
if (native) {
  cap.Plugins.FirebaseMessaging.addListener('notificationActionPerformed', ev => {
    const d = ev.notification?.data;
    if (d?.window_id) location.hash = `#trip=${d.window_id}|${d.code}${d.space ? '&space=' + d.space : ''}`;
  });
}
// The service worker tells an open app which trip a tapped notification wants.
navigator.serviceWorker?.addEventListener('message', ev => { if (ev.data?.hash) location.hash = ev.data.hash; });

// --- Calendar: the AI's blocker labels, one tap to overrule.
let labels = [];
const effective = l => l.override ?? l.block;
async function renderCal() {
  const snap = await getDocs(collection(db, 'spaces', S.sid, 'labels'));
  const today = new Date(); today.setHours(0, 0, 0, 0);
  labels = snap.docs.map(d => ({ id: d.id, ...d.data() })).filter(l => l.start && toDate(l.start) >= today).sort((a, b) => toDate(a.start) - toDate(b.start));
  paintCal();
}
function paintCal() {
  $('#cal').innerHTML = `<div class="head"><h1>Calendar</h1><p class="sub">Tap an event to flip whether it blocks a trip.</p></div>
    <ul class="rows">${labels.map(l => `<li><button data-id="${esc(l.id)}">
      <span class="t">${esc(l.title)}</span><span class="chip ${effective(l) ? 'blocks' : ''}">${effective(l) ? 'Blocks' : 'Free'}</span>
      <span class="why">${esc(day(l.start))}${l.all_day ? ' · all day' : ''}${l.override != null ? ' · your call' : ''}${l.why ? ' · ' + esc(l.why) : ''}</span></button></li>`).join('')}</ul>
    ${labels.length ? '' : '<div class="empty"><h2>Nothing upcoming</h2><p>Events appear after the daily search reads the calendar.</p></div>'}`;
}
$('#cal').addEventListener('click', async ev => {
  const l = labels.find(x => x.id === ev.target.closest('[data-id]')?.dataset.id);
  if (!l) return;
  const next = !effective(l), override = next === l.block ? null : next; // back to the AI's answer clears the override
  try {
    await updateDoc(sref('labels', l.id), { override });
    l.override = override;
    paintCal();
  } catch (e) { toast(e.message); }
});

// --- Start: sign in, find this person's spaces, open one.
async function startSpace(sid) {
  S = spaces.find(s => s.sid === sid);
  store.set('space', sid);
  const k = await getKeys().catch(() => ({}));
  if (store.get('alerts')) enableAlerts().catch(() => {}); // refresh this phone's token quietly
  if (hashParams().get('trip')) await go('trips');
  else await go((k.calendars || []).length ? 'trips' : 'setup');
}
async function boot() {
  me = auth.currentUser.email.toLowerCase();
  isAdmin = await getDoc(doc(db, 'admins', me)).then(d => d.exists(), () => false);
  try { spaces = (await getDocs(query(collection(db, 'spaces'), where('members', 'array-contains', me)))).docs.map(d => ({ ...d.data(), sid: d.id })); } catch (e) { return gateError(e.message); }
  const wanted = [hashParams().get('space'), store.get('space')];
  const pick = spaces.find(s => wanted.includes(s.sid));
  if (spaces.length === 1) await startSpace(spaces[0].sid);
  else if (pick) await startSpace(pick.sid);
  else if (spaces.length) gatePicker();
  else gateNoSpace();
}
checkUpdate();
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {}); // offline shell + web push; optional
onAuthStateChanged(auth, user => (user ? boot() : (S = null, gateSignIn(''))));
