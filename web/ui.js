export const $ = (s, el = document) => el.querySelector(s);
// Everything that comes from Firestore (city names, event titles) goes through esc() before it touches HTML.
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
export const icon = id => `<svg class="ic" aria-hidden="true"><use href="#i-${id}"/></svg>`;

export const money = n => (n == null || isNaN(n) ? '' : '$' + Math.round(n).toLocaleString('en-US'));
export const dur = m => (m > 0 ? `${Math.floor(m / 60)}h ${String(Math.round(m % 60)).padStart(2, '0')}m` : '');
// Date-only strings are local days (new Date('2026-11-06') would be UTC and slip back a day in Chicago).
export const toDate = s => (/^\d{4}-\d\d-\d\d$/.test(s) ? new Date(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8)) : new Date(s));
export const day = s => (s ? toDate(s).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }) : '');
// Links from the database only open if they are plain https.
export const safeUrl = u => (/^https:\/\//i.test(u) ? u : '#');
