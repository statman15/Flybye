// node worker/test.mjs
import assert from "node:assert/strict";
import { webcrypto as crypto } from "node:crypto";
import worker, { verifyToken, parseWindow, corsHeaders, resetJwksCache, startMorningSearch } from "./worker.js";

const P = "flybye-6e46b", NOW = 1_800_000_000;
const enc = (o) => Buffer.from(typeof o === "string" ? o : JSON.stringify(o)).toString("base64url");
const gen = () => crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
const good = await gen(), other = await gen();
const jwk = { ...(await crypto.subtle.exportKey("jwk", good.publicKey)), kid: "k1" };

async function sign(over = {}, priv = good.privateKey) {
  const h = enc({ alg: "RS256", kid: "k1" });
  const p = enc({ aud: P, iss: "https://securetoken.google.com/" + P, exp: NOW + 3600, iat: NOW - 10, email_verified: true, email: "a@b.c", ...over });
  const s = Buffer.from(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", priv, Buffer.from(h + "." + p))).toString("base64url");
  return `${h}.${p}.${s}`;
}
const jwksFetch = async () => new Response(JSON.stringify({ keys: [jwk] }), { headers: { "cache-control": "public, max-age=0" } });
const rejects = async (tok) => { resetJwksCache(); await assert.rejects(verifyToken(tok, P, jwksFetch, NOW), { status: 401 }); };

// JWT
resetJwksCache();
assert.equal((await verifyToken(await sign(), P, jwksFetch, NOW)).email, "a@b.c");
await rejects(await sign({ exp: NOW - 1 }));
await rejects(await sign({ aud: "other" }));
await rejects(await sign({ iss: "https://securetoken.google.com/other" }));
await rejects(await sign({ email_verified: false }));
await rejects(await sign({}, other.privateKey));
await rejects("garbage");

// window_id
assert.deepEqual(parseWindow("weekend:2026-11-13:2026-11-15"), { out: "2026-11-13", ret: "2026-11-15" });
assert.throws(() => parseWindow("nope"), { status: 400 });

// CORS
assert.ok(corsHeaders("https://statman15.github.io"));
assert.ok(corsHeaders("capacitor://localhost"));
assert.equal(corsHeaders("https://evil.example"), null);
assert.equal(corsHeaders(null), null);

// full handler with fake fetch
const fs = (o) => ({ fields: Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v])) });
const settings = fs({ home: { stringValue: "ORD" }, search: { mapValue: { fields: { adults: { integerValue: "2" }, stops: { integerValue: "1" } } } },
  cities: { arrayValue: { values: [{ mapValue: { fields: { airports: { arrayValue: { values: [{ stringValue: "OPO" }] } }, stops: { integerValue: "2" } } } }] } } });
const keys = fs({ serpapi: { stringValue: "SECRETKEY" } });
const L = (id, t, n) => ({ airline: "United", flight_number: n, duration: 100, departure_airport: { id, time: t }, arrival_airport: { id: "X", time: t } });

function mk({ deny = false, serpErr = null, empty = false, budget = null } = {}) {
  const calls = [];
  const f = async (url, init = {}) => {
    url = String(url); calls.push({ url, init });
    if (url.includes("securetoken@system")) return jwksFetch();
    if (url.includes("firestore.googleapis.com") && url.endsWith(":commit")) return new Response("{}");
    if (url.includes("firestore.googleapis.com")) {
      if (deny) return new Response("{}", { status: 403 });
      if (url.endsWith("/meta/budget")) return budget ? new Response(JSON.stringify(fs({ month: { stringValue: budget.month }, used: { integerValue: String(budget.used) } })))
        : new Response("{}", { status: 404 });
      return new Response(JSON.stringify(url.endsWith("/settings/main") ? settings : keys));
    }
    if (url.startsWith("https://serpapi.com/")) {
      if (serpErr) return new Response(JSON.stringify({ error: serpErr }));
      if (empty) return new Response(JSON.stringify({ error: "Google Flights hasn't returned any results for this query." }));
      const u = new URL(url);
      if (u.searchParams.get("departure_token")) return new Response(JSON.stringify({ best_flights: [{ price: 300, flights: [L("MIA", "r1", "UA9")] }] }));
      return new Response(JSON.stringify({ search_metadata: { google_flights_url: "https://g/x" }, best_flights: [
        { price: 500, departure_token: "no", flights: [L("ORD", "x", "AA1")] }, { price: 300, departure_token: "tok", flights: [L("ORD", "o1", "UA1"), L("DEN", "o2", "UA2")] }] }));
    }
    throw new Error("unexpected " + url);
  };
  return { f, calls };
}
const req = (o = {}, origin = "https://statman15.github.io", tok) =>
  new Request("https://w.dev/times", { method: "POST", headers: { origin, authorization: "Bearer " + tok, "content-type": "application/json" },
    body: JSON.stringify({ sid: "s1", window_id: "weekend:2026-11-13:2026-11-15", code: "OPO", ...o }) });
const env = { PROJECT_ID: P };
// tokens must be valid "now": sign with real-time claims for handler tests
const live = () => sign({ exp: Math.floor(Date.now() / 1000) + 3600, iat: Math.floor(Date.now() / 1000) - 10 });
const call = (r, m) => { resetJwksCache(); return worker.fetch(r, env, null, m.f); };

let m = mk(), r = await call(req({}, undefined, await live()), m);
assert.equal(r.status, 200);
assert.equal(r.headers.get("access-control-allow-origin"), "https://statman15.github.io");
const body = await r.json();
assert.equal(body.price, 300);
assert.equal(body.booking_link, "https://g/x");
assert.deepEqual(body.outbound.map((l) => l.flight_number), ["UA1", "UA2"]);
assert.deepEqual(body.return.map((l) => l.flight_number), ["UA9"]);
assert.deepEqual(Object.keys(body.outbound[0]), ["airline", "flight_number", "dep", "arr", "from", "to", "duration"]);
const serpUrls = m.calls.filter((c) => c.url.startsWith("https://serpapi")).map((c) => new URL(c.url).searchParams);
assert.equal(serpUrls.length, 2);
assert.equal(serpUrls[0].get("stops"), "2"); // wish city's own stops
assert.equal(serpUrls[0].get("departure_id"), "ORD");
assert.equal(serpUrls[0].get("outbound_date"), "2026-11-13");
assert.equal(serpUrls[1].get("departure_token"), "tok");
assert.ok(m.calls.at(-1).init.body.includes('"integerValue":"2"'));

// errors
assert.equal((await call(req({}, undefined, "bad"), mk())).status, 401);
assert.equal((await call(new Request("https://w.dev/times", { method: "POST", headers: { origin: "https://statman15.github.io" } }), mk())).status, 401);
assert.equal((await call(req({}, undefined, await live()), mk({ deny: true }))).status, 403);
assert.equal((await call(req({}, undefined, await live()), mk({ empty: true }))).status, 404);
r = await call(req({}, undefined, await live()), mk({ serpErr: "Invalid API key. Your API key SECRETKEY is wrong" }));
assert.equal(r.status, 502);
assert.ok(!(await r.text()).includes("SECRETKEY"));
assert.equal((await call(req({ window_id: "x" }, undefined, await live()), mk())).status, 400);

// the space's monthly search cap (settings.search.cap, default 230) is checked before spending 2 searches
const month = new Date().toISOString().slice(0, 7);
const capped = mk({ budget: { month, used: 229 } });
assert.equal((await call(req({}, undefined, await live()), capped)).status, 429);
assert.ok(!capped.calls.some((c) => c.url.startsWith("https://serpapi.com/")));
assert.equal((await call(req({}, undefined, await live()), mk({ budget: { month, used: 228 } }))).status, 200);
assert.equal((await call(req({}, undefined, await live()), mk({ budget: { month: "2000-01", used: 999 } }))).status, 200); // last month's count
assert.equal((await call(req({}, undefined, await live()), mk())).status, 200); // no budget doc yet
assert.equal((await call(req({ window_id: "weekend:2026-99-99:2026-11-15" }, undefined, await live()), mk())).status, 400);

// CORS at the handler
assert.equal((await call(req({}, "https://evil.example", await live()), mk())).status, 403);
r = await call(new Request("https://w.dev/times", { method: "OPTIONS", headers: { origin: "capacitor://localhost" } }), mk());
assert.equal(r.status, 204);
assert.equal(r.headers.get("access-control-allow-origin"), "capacitor://localhost");

// Morning cron: dispatches daily.yml on main with the token; no token, no call
let sent;
await startMorningSearch({ GH_DISPATCH_TOKEN: "t" }, async (url, init) => { sent = { url, init }; return new Response(null, { status: 204 }); });
assert.match(sent.url, /\/repos\/statman15\/Flybye\/actions\/workflows\/daily\.yml\/dispatches$/);
assert.equal(sent.init.headers.authorization, "Bearer t");
assert.deepEqual(JSON.parse(sent.init.body), { ref: "main" });
sent = null;
await startMorningSearch({}, async () => { sent = 1; });
assert.equal(sent, null);
await assert.rejects(startMorningSearch({ GH_DISPATCH_TOKEN: "t" }, async () => new Response("no", { status: 403 })), /403/);

console.log("worker tests passed");
