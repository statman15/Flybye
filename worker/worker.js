// Flybye times Worker: an authenticated CORS proxy to SerpApi google_flights. Holds no secrets; no dependencies.
// The caller's Firebase ID token is verified, then used to read the space's SerpApi key from Firestore (so the rules decide access).
const JWKS_URL = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com";
const ORIGINS = ["https://statman15.github.io", "capacitor://localhost", "https://localhost", "http://localhost"];

class HttpError extends Error {
  constructor(status, msg) { super(msg); this.status = status; }
}

const b64u = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
const json = (o) => JSON.parse(new TextDecoder().decode(b64u(o)));

let jwksCache = null; // {keys, until}
export function resetJwksCache() { jwksCache = null; }

async function getKeys(fetchFn) {
  if (jwksCache && jwksCache.until > Date.now()) return jwksCache.keys;
  const r = await fetchFn(JWKS_URL);
  if (!r.ok) throw new HttpError(401, "cannot load signing keys");
  const maxAge = +(/max-age=(\d+)/.exec(r.headers.get("cache-control") || "") || [])[1] || 0;
  const keys = (await r.json()).keys;
  jwksCache = { keys, until: Date.now() + maxAge * 1000 };
  return keys;
}

// Returns the token's claims or throws HttpError(401).
export async function verifyToken(token, projectId, fetchFn = fetch, now = Date.now() / 1000) {
  const bad = () => new HttpError(401, "bad token");
  try {
    const [h, p, s] = token.split(".");
    const head = json(h), c = json(p);
    if (head.alg !== "RS256") throw bad();
    const jwk = (await getKeys(fetchFn)).find((k) => k.kid === head.kid);
    if (!jwk) throw bad();
    const key = await crypto.subtle.importKey("jwk", { ...jwk, alg: "RS256", ext: true }, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
    const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, b64u(s), new TextEncoder().encode(h + "." + p));
    if (!ok || c.aud !== projectId || c.iss !== "https://securetoken.google.com/" + projectId || !(c.exp > now) || !(c.iat <= now + 60) || c.email_verified !== true) throw bad();
    return c;
  } catch (e) {
    throw e instanceof HttpError ? e : bad();
  }
}

// "weekend:2026-11-13:2026-11-15" -> {out, ret}
export function parseWindow(id) {
  const m = /^[a-z0-9_]+:(\d{4}-\d\d-\d\d):(\d{4}-\d\d-\d\d)$/.exec(id || "");
  const real = (d) => !isNaN(Date.parse(d + "T00:00:00Z")) && new Date(d + "T00:00:00Z").toISOString().slice(0, 10) === d;
  if (!m || !real(m[1]) || !real(m[2])) throw new HttpError(400, "bad window_id");
  return { out: m[1], ret: m[2] };
}

export function corsHeaders(origin) {
  return ORIGINS.includes(origin)
    ? { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Headers": "authorization, content-type", "Access-Control-Allow-Methods": "POST, OPTIONS", "Vary": "Origin" }
    : null;
}

// Firestore REST value -> plain JS
function fromValue(v) {
  if ("stringValue" in v) return v.stringValue;
  if ("integerValue" in v) return +v.integerValue;
  if ("doubleValue" in v) return v.doubleValue;
  if ("booleanValue" in v) return v.booleanValue;
  if ("arrayValue" in v) return (v.arrayValue.values || []).map(fromValue);
  if ("mapValue" in v) return fromFields(v.mapValue.fields);
  return null;
}
const fromFields = (f = {}) => Object.fromEntries(Object.entries(f).map(([k, v]) => [k, fromValue(v)]));

async function readDoc(base, path, token, fetchFn) {
  const r = await fetchFn(`${base}/${path}`, { headers: { authorization: "Bearer " + token } });
  if (r.status === 403 || r.status === 401 || r.status === 404) throw new HttpError(403, "not allowed");
  if (!r.ok) throw new HttpError(502, "Firestore error");
  return fromFields((await r.json()).fields);
}

const leg = (f) => ({ airline: f.airline, flight_number: f.flight_number, dep: f.departure_airport?.time, arr: f.arrival_airport?.time,
  from: f.departure_airport?.id, to: f.arrival_airport?.id, duration: f.duration });
const itins = (d) => [...(d.best_flights || []), ...(d.other_flights || [])];
const cheapest = (d) => itins(d).sort((a, b) => a.price - b.price)[0];

async function serp(params, key, fetchFn) {
  let d;
  try {
    const r = await fetchFn("https://serpapi.com/search.json?" + new URLSearchParams({ ...params, api_key: key }));
    d = await r.json();
  } catch {
    throw new HttpError(502, "SerpApi unreachable");
  }
  if (d.error) {
    if (/hasn't returned any results|^Empty results/i.test(d.error)) return {};
    throw new HttpError(502, "SerpApi: " + String(d.error).replaceAll(key, "***").slice(0, 120));
  }
  return d;
}

export async function times(req, env, fetchFn = fetch) {
  const token = (req.headers.get("authorization") || "").replace(/^Bearer /i, "");
  if (!token) throw new HttpError(401, "missing token");
  await verifyToken(token, env.PROJECT_ID, fetchFn);
  let body;
  try { body = await req.json(); } catch { throw new HttpError(400, "bad json"); }
  const { sid, window_id, code } = body || {};
  if (!/^[A-Za-z0-9_-]+$/.test(sid || "") || !/^[A-Za-z]{3}$/.test(code || "")) throw new HttpError(400, "bad request");
  const { out, ret } = parseWindow(window_id);

  const root = `projects/${env.PROJECT_ID}/databases/(default)/documents`;
  const base = "https://firestore.googleapis.com/v1/" + root;
  const settings = await readDoc(base, `spaces/${sid}/settings/main`, token, fetchFn);
  const key = (await readDoc(base, `spaces/${sid}/private/keys`, token, fetchFn)).serpapi;
  if (!key) throw new HttpError(404, "no SerpApi key in this space");

  // Two searches per lookup come out of the space's monthly cap, the same one the daily job respects.
  const r = await fetchFn(`${base}/spaces/${sid}/meta/budget`, { headers: { authorization: "Bearer " + token } });
  const budget = r.ok ? fromFields((await r.json()).fields) : {};
  const used = budget.month === new Date().toISOString().slice(0, 7) ? Number(budget.used) || 0 : 0;
  if (used + 2 > (settings.search?.cap ?? 230)) throw new HttpError(429, "this month's searches are used up");

  const to = code.toUpperCase();
  const city = (settings.cities || []).find((c) => (c.airports || []).includes(to));
  const p = { engine: "google_flights", departure_id: settings.home || "ORD", arrival_id: to, outbound_date: out, return_date: ret,
    type: 1, adults: settings.search?.adults ?? 2, stops: city?.stops ?? settings.search?.stops ?? 1, currency: "USD", hl: "en", gl: "us" };
  const d1 = await serp(p, key, fetchFn);
  const best = cheapest(d1);
  if (!best) throw new HttpError(404, "no flights");
  let back = [];
  if (best.departure_token) {
    const d2 = await serp({ ...p, departure_token: best.departure_token }, key, fetchFn);
    back = (cheapest(d2)?.flights || []).map(leg);
  }

  // +2 searches in the space's budget, as the user (the rules allow exactly this increment). Best effort.
  await fetchFn(`https://firestore.googleapis.com/v1/${root}:commit`, {
    method: "POST", headers: { authorization: "Bearer " + token, "content-type": "application/json" },
    body: JSON.stringify({ writes: [{ transform: { document: `${root}/spaces/${sid}/meta/budget`, fieldTransforms: [{ fieldPath: "used", increment: { integerValue: "2" } }] } }] }),
  }).catch(() => {});

  return { outbound: best.flights.map(leg), return: back, price: best.price, booking_link: d1.search_metadata?.google_flights_url || null };
}

// The morning search runs in GitHub Actions, but GitHub's own schedule fires hours late or not at all.
// Cloudflare's cron is on time, so it starts the workflow (a fine-grained token that can only run this repo's Actions).
export async function startMorningSearch(env, fetchFn = fetch) {
  if (!env.GH_DISPATCH_TOKEN) return;
  const r = await fetchFn("https://api.github.com/repos/statman15/Flybye/actions/workflows/daily.yml/dispatches", {
    method: "POST", body: JSON.stringify({ ref: "main" }),
    headers: { authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`, accept: "application/vnd.github+json", "user-agent": "flybye-worker" } });
  if (r.status !== 204) throw new Error(`GitHub dispatch failed: ${r.status}`); // shows in the Worker's logs
}

// Cron is UTC only, so it fires at 11:50 and 12:50 UTC and only the one that is 6:50 in Chicago (summer or winter) counts:
// the search is done by about 7.
export const isMorning = (ms) => Number(new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", hour: "numeric", hourCycle: "h23" }).format(ms)) === 6;

export default {
  async scheduled(event, env, ctx) { if (isMorning(event.scheduledTime)) ctx.waitUntil(startMorningSearch(env)); },
  async fetch(req, env, _ctx, fetchFn = fetch) {
    const cors = corsHeaders(req.headers.get("origin"));
    const reply = (status, obj) => new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json", ...cors } });
    if (!cors) return new Response("forbidden origin", { status: 403 });
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (req.method !== "POST" || new URL(req.url).pathname !== "/times") return reply(404, { error: "not found" });
    try {
      return reply(200, await times(req, env, fetchFn));
    } catch (e) {
      return e instanceof HttpError ? reply(e.status, { error: e.message }) : reply(500, { error: "internal error" });
    }
  },
};
