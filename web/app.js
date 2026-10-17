import { $, esc, icon, money, dur, day, toDate, safeUrl } from './ui.js';
import { auth, db, onAuthStateChanged, signInWithPopup, signInWithCredential, GoogleAuthProvider, signOut,
  doc, getDoc, getDocs, collection, setDoc, updateDoc, deleteDoc, webPushToken } from './fb.js';

const cap = window.Capacitor;
const native = cap?.isNativePlatform?.();
const KINDS = { weekend: 'Weekend', '3day': '3-day weekend', long: 'Longer trip' };
const sref = () => doc(db, 'settings', 'main');
const guard = (el, fn) => fn().catch(e => { el.innerHTML = `<div class="empty"><h2>Couldn’t load</h2><p class="err">${esc(e.message)}</p></div>`; });
const store = { get: k => { try { return localStorage.getItem(k); } catch { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode: the toggle just isn't remembered */ } } };

let toastTimer;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 3500);
}

// Read-modify-write on settings/main, so an edit never clobbers a field the other phone just changed.
async function mutate(fn) {
  const snap = await getDoc(sref());
  if (!snap.exists()) throw new Error('No settings yet. The daily run creates them the first time it runs.');
  await updateDoc(sref(), fn(snap.data()));
}

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
  for (const s of document.querySelectorAll('main > [data-tab]')) s.hidden = s.dataset.tab !== 'gate';
  $('#dock').hidden = true;
  $('#gate').innerHTML = html;
}
const gateSignIn = err => showGate(`<div class="head"><h1>Flybye</h1></div>
  <div class="empty"><p>Cheap getaways on the days we’re both free.</p>
  <button class="pill" data-act="signin">Sign in with Google</button>
  <p class="err">${esc(err)}</p></div>`);
const gateDenied = email => showGate(`<div class="head"><h1>Flybye</h1></div>
  <div class="empty"><h2>This Google account isn’t on Flybye.</h2><p>${esc(email)}</p>
  <button class="pill quiet" data-act="signout">Sign out</button></div>`);

$('#gate').addEventListener('click', async ev => {
  const act = ev.target.closest('[data-act]')?.dataset.act;
  if (act === 'signout') return logOut();
  if (act !== 'signin') return;
  try { await signIn(); } catch (e) {
    if (!/cancel|closed-by-user|popup-closed/i.test(`${e.code} ${e.message}`)) gateSignIn(e.message);
  }
});

// --- Tabs
const views = { trips: renderTrips, wish: renderWish, settings: renderSettings, cal: renderCal };
async function go(tab) {
  for (const s of document.querySelectorAll('main > [data-tab]')) s.hidden = s.dataset.tab !== tab;
  for (const b of document.querySelectorAll('#tabs button')) b.setAttribute('aria-selected', b.dataset.go === tab);
  $('#dock').hidden = false;
  await guard($('#' + tab), views[tab]);
  scrollTo(0, 0);
}
$('#tabs').addEventListener('click', ev => { const b = ev.target.closest('[data-go]'); if (b) go(b.dataset.go); });

// --- Trips
const stopsText = n => (n ? `${n} stop${n > 1 ? 's' : ''}` : 'Nonstop');
function pickCard(p, w, tag = '') {
  const pct = p.usual > 0 ? Math.round((1 - p.price / p.usual) * 100) : 0;
  return `<article class="group card" data-trip="${esc(w.id)}|${esc(p.code)}">
    <div class="card-top"><span class="city">${esc(p.name)}</span><span class="price">${esc(money(p.price))} <small>for 2</small></span></div>
    <p class="meta">${esc(day(w.out))} → ${esc(day(w.ret))}${w.holiday ? ' · ' + esc(w.holiday) : ''}</p>
    <p class="meta">${[dur(p.minutes), stopsText(p.stops), p.airline, p.hotel != null ? 'hotel ' + money(p.hotel) : ''].filter(Boolean).map(esc).join(' · ')}</p>
    ${pct > 0 ? `<p class="meta deal">${pct}% under usual (${esc(money(p.usual))})</p>` : ''}
    <div class="tags">${p.wish ? '<span class="tag on">Wish list</span>' : ''}${tag ? `<span class="tag">${esc(tag)}</span>` : ''}</div>
    <a class="pill small" href="${esc(safeUrl(p.link))}" target="_blank" rel="noopener noreferrer">Google Flights</a>
  </article>`;
}

async function renderTrips() {
  const el = $('#trips');
  const snap = await getDoc(doc(db, 'suggestions', 'current'));
  if (!snap.exists()) {
    el.innerHTML = `<div class="head"><h1>Trips</h1></div><div class="empty"><h2>No suggestions yet</h2><p>The daily search writes them every morning.</p></div>`;
    return;
  }
  const s = snap.data();
  const top = (s.top || []).map(p => pickCard(p, windowOf(s, p.window_id) || { id: p.window_id }, p.wish ? '' : 'Surprise'));
  const wins = (s.windows || []).map(w => `<h2 class="sec">${esc(KINDS[w.kind] || w.kind)}<small>${esc(day(w.out))} → ${esc(day(w.ret))}${w.holiday ? ' · ' + esc(w.holiday) : ''}</small></h2>
    ${(w.picks || []).map(p => pickCard(p, w)).join('') || '<p class="pad muted">No fares found for these dates yet.</p>'}`);
  el.innerHTML = `<div class="head"><h1>Trips</h1><p class="sub">Updated ${esc(s.updated ? toDate(s.updated).toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' }) : 'never')}</p></div>
    ${top.length ? `<h2 class="sec">Top picks</h2>${top.join('')}` : ''}${wins.join('')}`;
  highlight();
}
const windowOf = (s, id) => (s.windows || []).find(w => w.id === id);

// #trip=<window_id>|<code> (from a push) scrolls to that card.
function highlight() {
  const m = /^#trip=(.+)$/.exec(decodeURIComponent(location.hash));
  if (!m) return;
  const hits = [...document.querySelectorAll('[data-trip]')].filter(c => c.dataset.trip === m[1]);
  document.querySelectorAll('.card.hit').forEach(c => c.classList.remove('hit'));
  hits.forEach(c => c.classList.add('hit'));
  hits[0]?.scrollIntoView({ block: 'center' });
}
async function route() {
  if (!auth.currentUser || !location.hash.startsWith('#trip=')) return;
  await go('trips');
  highlight();
}
addEventListener('hashchange', route);

// --- Wish list
const AIRPORT = /^[A-Z]{3}$/;
async function renderWish() {
  const el = $('#wish');
  const snap = await getDoc(sref());
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
$('#wish').addEventListener('submit', async ev => {
  ev.preventDefault();
  const f = ev.target, err = $('#addErr');
  const name = f.name.value.trim(), airports = f.airports.value.toUpperCase().split(/[\s,]+/).filter(Boolean);
  if (!name) return void (err.textContent = 'Give the city a name.');
  if (!airports.length || !airports.every(a => AIRPORT.test(a))) return void (err.textContent = 'Airport codes are 3 letters, like MIA, FLL.');
  try {
    await mutate(s => {
      const cities = s.cities || [];
      if (cities.some(c => c.name.toLowerCase() === name.toLowerCase())) throw new Error(`${name} is already on the list.`);
      return { cities: [...cities, { name, airports, trips: Object.keys(KINDS) }] };
    });
    await renderWish();
  } catch (e) { err.textContent = e.message; }
});

// --- Settings
async function renderSettings() {
  const el = $('#settings');
  const snap = await getDoc(sref());
  const s = snap.exists() ? snap.data() : null;
  const kinds = s ? Object.entries(KINDS).map(([k, label]) => {
    const t = (s.trips || {})[k] || {};
    return `<div class="kind"><label class="check"><input type="checkbox" name="${k}-on"${t.enabled ? ' checked' : ''}>${esc(label)}</label>
      <div class="two"><label>Weeks ahead, from<input type="number" inputmode="numeric" min="1" max="52" name="${k}-min" value="${esc(t.weeks?.[0])}"></label>
      <label>to<input type="number" inputmode="numeric" min="1" max="52" name="${k}-max" value="${esc(t.weeks?.[1])}"></label></div>
      ${k === 'long' ? `<label style="margin-top:12px">Nights (e.g. 7 or 5, 9)<input name="nights" value="${esc((t.nights || []).join(', '))}"></label>` : ''}</div>`;
  }).join('') : '';
  el.innerHTML = `<div class="head"><h1>Settings</h1><p class="sub">${esc(auth.currentUser?.email)}</p></div>
    ${s ? `<form class="group form" id="setForm" novalidate>${kinds}
      <label>Home airport<input name="home" maxlength="3" autocapitalize="characters" value="${esc(s.home)}"></label>
      <p class="err" id="setErr"></p><button class="pill" type="submit">Save</button></form>`
      : '<div class="empty"><p>No settings yet. The daily run creates them the first time it runs.</p></div>'}
    <h2 class="sec">Alerts</h2>
    <div class="group card"><p class="meta" style="margin:0 0 10px" id="alertMsg">${store.get('alerts') ? 'Alerts are on for this phone.' : 'Get a push when a wish-list fare drops, and the Sunday top picks.'}</p>
      <button class="pill" id="alertBtn">Turn on alerts</button></div>
    <div class="pad" style="margin-top:20px"><button class="pill quiet" id="outBtn">Sign out</button></div>`;
}
$('#settings').addEventListener('submit', async ev => {
  ev.preventDefault();
  const f = ev.target, err = $('#setErr'), trips = {};
  const home = f.home.value.trim().toUpperCase();
  if (!AIRPORT.test(home)) return void (err.textContent = 'Home airport is 3 letters, like ORD.');
  let nights;
  for (const k of Object.keys(KINDS)) {
    const min = +f[`${k}-min`].value, max = +f[`${k}-max`].value;
    if (![min, max].every(n => Number.isInteger(n) && n >= 1 && n <= 52) || min >= max) return void (err.textContent = `${KINDS[k]}: weeks need two whole numbers, the first smaller than the second.`);
    trips[k] = { enabled: f[`${k}-on`].checked, weeks: [min, max] };
  }
  nights = f.nights.value.split(/[\s,]+/).filter(Boolean).map(Number);
  if (!nights.length || !nights.every(n => Number.isInteger(n) && n >= 1 && n <= 30)) return void (err.textContent = 'Nights are whole numbers from 1 to 30.');
  trips.long.nights = nights;
  err.textContent = '';
  try {
    await mutate(s => ({ home, trips: Object.fromEntries(Object.entries(trips).map(([k, t]) => [k, { ...(s.trips || {})[k], ...t }])) }));
    toast('Saved');
  } catch (e) { err.textContent = e.message; }
});
$('#settings').addEventListener('click', async ev => {
  if (ev.target.id === 'outBtn') return logOut();
  if (ev.target.id !== 'alertBtn') return;
  try { await enableAlerts(); $('#alertMsg').textContent = 'Alerts are on for this phone.'; toast('Alerts on'); } catch (e) { toast(e.message); }
});

// --- Push. Android: Capacitor FirebaseMessaging. iPhone home-screen web app: FCM web token through sw.js (which also draws the notification).
async function registerDevice(token, platform) {
  await setDoc(doc(db, 'devices', token), { platform, email: auth.currentUser.email, at: new Date().toISOString() });
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
    if (d?.window_id) location.hash = `#trip=${d.window_id}|${d.code}`;
  });
}
// The service worker tells an open app which trip a tapped notification wants.
navigator.serviceWorker?.addEventListener('message', ev => { if (ev.data?.hash) location.hash = ev.data.hash; });

// --- Calendar: the AI's blocker labels, one tap to overrule.
let labels = [];
const effective = l => l.override ?? l.block;
async function renderCal() {
  const el = $('#cal');
  const snap = await getDocs(collection(db, 'labels'));
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
    await updateDoc(doc(db, 'labels', l.id), { override });
    l.override = override;
    paintCal();
  } catch (e) { toast(e.message); }
});

// --- Start
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {}); // offline shell + web push; optional
onAuthStateChanged(auth, async user => {
  if (!user) return gateSignIn('');
  try {
    const ok = await getDoc(doc(db, 'allow', user.email));
    if (!ok.exists()) return gateDenied(user.email);
  } catch { return gateDenied(user.email); } // the rules answer "no" with an error
  if (store.get('alerts')) enableAlerts().catch(() => {}); // refresh this phone's token quietly
  if (location.hash.startsWith('#trip=')) await route(); else await go('trips');
});
