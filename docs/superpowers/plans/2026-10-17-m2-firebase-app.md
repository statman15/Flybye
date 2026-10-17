# M2: Firebase + the app (implementation plan)

Spec: `PLAN.md` (Repo, Backend, Data, Sign-in, Push and Apps rows; Milestone 2). The repo will be public, so **no keys, emails or personal data in git**.

## Firestore documents (shared contract)

The job writes everything except `settings/main`, `labels.*.override` and `devices`, which the app writes. The job uses the Admin SDK, so it isn't bound by the rules.

```
settings/main   same shape as config.yaml minus `db` and `ai`:
                {home, trips:{weekend|3day|long:{enabled, weeks:[min,max], nights?}},
                 cities:[{name, airports:[...], trips:[...], stops?}], search:{...}, alerts:{...}, score:{...}}
                The job seeds it from config.yaml the first time it's missing, and reads it on every run after that.
labels/{id}     id = sha1(key)[:20], where key = "<uid>|<title>"
                {key, title, start: ISO of the next occurrence, all_day, block: bool (AI), why, src, at,
                 override: null|true|false}
                The block that counts is `override ?? block`. The AI never changes `override`.
suggestions/current
                {updated: ISO, windows: [{id, kind, out, ret, holiday, picks: [Pick...] (best first, max 8)}],
                 top: [Pick + {window_id}] (the 3 best wish-list picks + 1 surprise)}
                Pick = {code, name, price, usual: number|null, minutes, stops, hotel: number|null, airline,
                        wish: bool, link: Google Flights URL}
latest/{window_id}  {seen, rows: [price row...]}  (the newest sweep of that window)
routes/{code}_{kind} {prices: [{seen, window_id, price}]}  newest 60 only, used for pick.baseline
meta/budget     {month: "YYYY-MM", used: int, last: {window_id: ISO}}   (used resets when the month changes)
meta/alerts     {sent: [{at, code, out, ret, price, kind}]}  (newest 100)
meta/summary    {last: ISO}
devices/{token} {platform: "android"|"web", email, at}
allow/{email}   {}   Chris creates these two by hand in the console. They are never in git.
```

**Push message (FCM):**
- `notification: {title, body}`
- `data: {window_id, code}`
- web: `webpush.fcm_options.link = APP_URL + "#trip=<window_id>|<code>"`
- If a send returns an unregistered or invalid token, delete that `devices` doc.

## Task A: backend on Firestore + FCM (one agent)

Files: `backend/`, `config.yaml` and `.github/workflows/daily.yml`. Don't touch `web/`, `android/` or the root `package.json`.

1. Add `backend/flybye/store.py`, which replaces `db.py`. Every Firestore read and write goes through it, so `__main__.py` and `ai.py` stop using SQL.
   - Functions: `settings()`, `labels_get(keys)`, `labels_put(...)`, `budget()`, `log_search(window_id, engine)`, `route_prices(code, kind)`, `add_prices(rows, seen)`, `latest_rows(window_ids, since)`, `alerts()`, `add_alert(a)`, `summary_last()`, `set_summary_last()`, `write_suggestions(doc)`, `device_tokens()`, `drop_token(t)`.
   - Build it over an injected client. Production uses `firebase_admin.firestore.client()`, with credentials from the `FIREBASE_SA` env var (JSON text).
   - Tests use a small in-memory fake with the same few calls: `collection(name).document(id).get()/set()/update()` and `.stream()`. Put it in `tests/fakefs.py`.
2. `ai.label_events`:
   - Overrides now come from the `override` field on label docs. Drop the config `overrides`.
   - Store `start` and `all_day` for the app.
   - AI failure still blocks and isn't cached.
3. `serp._call` logs searches through `store.log_search`. The cap logic, the `Fatal` handling and the `"<window>|<code>"` confirm ids stay as they are.
4. Push:
   - `push.py` has `send(title, body, data, link)`, which fans out to `device_tokens()` with `firebase_admin.messaging`.
   - Prune dead tokens.
   - Delete ntfy, including the `NTFY_TOPIC` env var.
5. Suggestions:
   - Every `daily` run writes `suggestions/current` from the latest rows (21-day freshness) of the windows that are still free. Reuse `pick.score`, `pick.fmt_row` and `pick.summary` logic.
   - The Sunday push is the summary text.
6. Workflow:
   - Remove the "Save the database" step, `contents: write` and the `data/` handling.
   - The env gets `FIREBASE_SA`, and drops `NTFY_TOPIC`.
   - Add `APP_URL: https://statman15.github.io/Flybye/` as a plain env var.
   - Remove `data/` from `.gitignore` handling.
7. Keep all 49 existing behaviours tested by porting the tests to the fake store. Add tests for: settings seeding, override precedence, suggestions doc shape, dead-token pruning, and that budget `used` resets on a new month.

Done when: `backend/.venv/Scripts/python -m pytest -q backend/tests` is green, there's no `sqlite3` import left, and there's no ntfy.

## Task B: web app + Android shell (one agent)

Files: `web/`, `android/`, root `package.json`, `capacitor.config.json`, `copy-web.js`, `smoke.mjs`, `.github/workflows/app.yml`, and `firestore.rules`.

Follow HypertroPhy (`C:\Users\ressl\Claude Code\Weightlifting_App`): read its `CLAUDE.md`, `index.html`, `ui.js`, `sw.js`, `manifest.webmanifest`, `copy-web.js`, `smoke.mjs`, `package.json`, `capacitor.config.json` and `.github/workflows/android.yml`, and copy their patterns and look.

- **Stack:**
  - Plain HTML/JS ES modules, no build step.
  - The Firebase JS SDK v12 modular ESM from `https://www.gstatic.com/firebasejs/<pinned version>/...`.
  - `web/firebase-config.js` exports the public web config, with `REPLACE_ME` placeholders, plus `VAPID_KEY`. Chris fills it in. These values are public by design.
- **Sign-in:**
  - Web: Google with `signInWithPopup`.
  - Android: `@capacitor-firebase/authentication`, version-matched to Capacitor 8. Native Google sign-in gives an idToken, then the web SDK calls `signInWithCredential(GoogleAuthProvider.credential(idToken))`, so Firestore uses the same user.
  - Signed out, the app shows one "Sign in with Google" screen.
  - If Firestore denies access (the email isn't allowed), show "This Google account isn't on Flybye."
- **Screens (tab bar):**
  1. **Trips:** `suggestions/current`. The top picks come first, then each free window with its picks. Each card shows the city, dates, price for 2, "% under usual", flight time, nonstop or stops, the hotel price, a "Google Flights" button that opens `link`, and the holiday name if there is one. A `#trip=<window>|<code>` hash scrolls to that card and highlights it. Show "Updated <time>".
  2. **Wish list:** edit `settings/main.cities`. Add a city (name plus airport codes, uppercase 3-letter, validated), remove it, toggle trip types per city, and set nonstop or 1 stop (`stops: 2`). It saves to Firestore.
  3. **Settings:** trip types (enabled, weeks min–max as number inputs with min < max checked, long nights). Home airport (3 letters). Sign out. "Turn on alerts" (below).
  4. **Calendar:** `labels`, sorted by `start`, upcoming only. Each row shows the title, the date, and a Blocks / Free chip using `override ?? block`, plus the AI's `why`. Tapping toggles `override`. If the override equals the AI's value, set it to `null`. Mark the overridden rows.
- **Push:**
  - Android: `@capacitor-firebase/messaging`. Request permission on "Turn on alerts", get the token, write `devices/{token}` with platform android. A notification tap opens `#trip=...`.
  - Web (iPhone home-screen app, iOS 16.4+): `isSupported()`, then a user tap, then `Notification.requestPermission()`, then `getToken` with `VAPID_KEY` and the registration of `web/firebase-messaging-sw.js` (scope = the app's path on Pages, `/Flybye/`). Write `devices/{token}` with platform web.
  - When `isSupported()` is false, say "On iPhone, add Flybye to the Home Screen first."
- **Offline shell:** `sw.js` caches the app shell like HypertroPhy's. Keep it separate from, and not conflicting with, the messaging service worker; one combined SW is fine if simpler.
- **Capacitor:**
  - appId `com.statman15.flybye`, appName Flybye, `webDir: www`. `copy-web.js` copies `web/` into `www/`.
  - Generate `android/` with `npx cap add android`, and add the two firebase plugins.
  - `google-services.json` comes from the `GOOGLE_SERVICES_JSON` secret in CI and is git-ignored locally.
- **Workflow `app.yml`:**
  - Runs on pushes to `main` that touch `web/`, `android/` or the package files.
  - A `check` job runs `npm ci` and `npm run smoke` (headless Chrome loads `web/index.html` with Firebase stubbed and fails on any console error, as in HypertroPhy).
  - The `pages` job deploys `web/`.
  - The `android` job builds a signed APK with `KEYSTORE_B64` and `KEYSTORE_PASSWORD` (generate the keystore the HypertroPhy way, never committed) and publishes a GitHub Release.
  - Pin actions by SHA as HypertroPhy does.
- **`firestore.rules`:**
  - `ok()` = signed in, `email_verified`, and `exists(/databases/$(database)/documents/allow/$(request.auth.token.email))`.
  - `settings`: read/write if ok.
  - `suggestions`, `labels`: read if ok. For labels, the update is only allowed if ok and `request.resource.data.diff(resource.data).affectedKeys().hasOnly(['override'])`.
  - `devices/{t}`: create and delete if ok, and `request.resource.data.email == request.auth.token.email` on create.
  - `allow/{e}`: read only your own doc (so the app can detect "not allowed").
  - Everything else: deny.
- **Known risk to note in the code and in SETUP:** Google popup sign-in in an iOS home-screen web app on a github.io domain. If it fails on Laura's phone, the fallback is Firebase Hosting (same-site `authDomain`). Don't build the fallback now.

Done when:
- `npm run smoke` is green.
- The app loads at `http://localhost:5173/` (from `web/`) and shows the sign-in screen with no console errors.
- `npx cap sync android` succeeds.
- `cd android && ./gradlew assembleDebug` builds, if Java 21 is available. Otherwise say so.

## Task C: setup (Chris, by hand; Opus writes SETUP.md)

1. Firebase project (Spark).
2. Enable Authentication with Google.
3. Create Firestore in production mode and paste the `firestore.rules`.
4. Add `allow/<chris email>` and `allow/<laura email>`.
5. Add a web app and copy its config into `web/firebase-config.js`.
6. Cloud Messaging: generate the web push certificate (the VAPID key).
7. Add an Android app (`com.statman15.flybye`) with the keystore's SHA-1 and copy `google-services.json` into a secret.
8. Create a service account key and put it in the `FIREBASE_SA` secret.
9. Authentication → authorized domains: add `statman15.github.io`.
10. Add the remaining GitHub secrets.

## Final

- A whole-branch review.
- Then make the repo public.
- Re-enable the Daily sweep.
- Run `test`, then `windows`, then `daily`.
- Both phones sign in and get a push.
