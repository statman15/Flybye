# M3: spaces, weather, airlines, flight times, Activity (implementation plan)

Spec: `PLAN.md` (the "Milestone 3" section and the "Spaces" decisions). Chris settled the design on 2026-10-18. The repo is **public**, so no keys, emails or personal data go in git.

## Decisions (Chris, 2026-10-18)
- **Spaces.** Every person who uses Flybye gets their own **space**: their own calendar links (one or more, personal or shared), home airport, wish list, trip types, airlines, weather range, and **their own SerpApi and Gemini keys**. A trip window is free only if **every** calendar in the space is free.
- **Members.** The owner can let a travel partner into the space (Chris lets Laura in). Members see the same trips and all get the pushes.
- **Who can create a space.** Only an admin (Chris) can, from an Admin screen, by typing the owner's Google email. Owners can add or remove members of their own space.
- **Airlines.** Each space keeps two lists of IATA codes, a **prefer** list and an **avoid** list. Avoided airlines are hidden. Preferred airlines rank higher.
- **Weather.** Each space sets an **ideal temperature range** (°F) for daytime highs.
  - Trips that start within 16 days get the Open-Meteo forecast.
  - Later trips get the **typical** weather for that place and week: a 10-year average of highs, lows and rain from the Open-Meteo archive.
  - Weather changes the ranking, and every card shows it.
- **Flight times.** Times show **instantly, on tap**. A free Cloudflare Worker acts as a minimal CORS proxy between the app and SerpApi (SerpApi doesn't allow browser calls).
  - It holds **no secrets**. The app sends the user's Firebase ID token.
  - The Worker verifies the token, then reads the space's SerpApi key from Firestore **as that user**, so the security rules apply.
  - It calls SerpApi `google_flights`: outbound first, then the return leg via `departure_token`. That's 2 searches per trip opened, counted in the space's budget.
- **Activity screen.** It shows:
  - the last run and the next run
  - searches used and left this month
  - which windows were checked and when
  - errors
  - how many events the AI labelled and blocked (the list is on the Calendar tab)
  - why each trip ranks where it does: a breakdown of its score

## Firestore v2 (the shared contract)

Every email is stored **lowercase**. `sid` is a random id.

```
admins/{email}                     {}   (Chris, created by hand)
spaces/{sid}                       {name, owner: email, members: [email...], created: ISO}
spaces/{sid}/private/keys          {serpapi: str, gemini: str, calendars: [{name, url}]}
spaces/{sid}/settings/main         v1 settings_main shape plus:
                                   airlines: {prefer: [IATA], avoid: [IATA]},
                                   weather: {min_f: int, max_f: int}      (default 65-85)
spaces/{sid}/labels/{id}           as in v1 (key, title, start, all_day, block, why, src, at, override)
spaces/{sid}/suggestions/current   as in v1, but each Pick also has:
                                   weather: {kind: "forecast"|"typical", hi_f, lo_f, rain_pct} | null,
                                   score: {total, under_pct, hours, wish, holiday, weather, airline},
                                   airline_code
spaces/{sid}/latest/{window_id}    as in v1; rows also carry lat, lon, airline_code
spaces/{sid}/routes/{code}_{kind}  as in v1
spaces/{sid}/meta/budget           {month, used, last}   (v1 shape; the Worker also adds +2 per times lookup)
spaces/{sid}/meta/alerts           as in v1
spaces/{sid}/meta/summary          as in v1
spaces/{sid}/meta/activity         {last_run: ISO, next_run: ISO, month, used, cap,
                                    windows: [{id, searched_at|null, picks: int}],
                                    labelled: int, blocking: int, errors: [str]  (newest 20)}
spaces/{sid}/devices/{token}       {platform, email, at}
climate/{code}_{MM}                {hi_f, lo_f, rain_pct, years: 10, at}   (shared, not personal; job only)
```
The v1 top-level `settings`, `labels`, `suggestions`, `latest`, `routes`, `meta`, `devices` and `allow` are **migrated** into one space and then deleted (Task A, step 6).

**Score:** `total = under_pct - hour_penalty*hours + wish + holiday + weather + airline`.
- `weather` = `weather_bonus` (10) when hi_f is inside [min_f, max_f]. Otherwise subtract 1 point per °F outside, capped at 20. Then subtract `rain_pct/10`.
- `airline` = `airline_bonus` (8) when the airline is on the prefer list.
- Avoided airlines are removed before scoring.
- The weights live in settings `score: {..., weather_bonus: 10, airline_bonus: 8}`.

**Weather data:**
- Coordinates come from Explore's `gps_coordinates` (now stored on each row).
- The forecast comes from `api.open-meteo.com/v1/forecast` (daily `temperature_2m_max`, `temperature_2m_min`, `precipitation_probability_max`, °F). Average it over the trip's days. Cache it for one run in memory.
- Typical weather comes from `archive-api.open-meteo.com/v1/archive`, using the same dates in each of the last 10 years for that city and month. Cache the result in `climate/{code}_{MM}` for 180 days.
- If either call fails, `weather` is null and the weather term is 0. A failure never blocks a run.

**Push:** unchanged, but it only goes to that space's `devices`. Link: `APP_URL#trip=<encoded window|code>&space=<sid>`.

## Task A: backend (agent 1)
Files: `backend/`, `config.yaml`, `.github/workflows/daily.yml`, `tools/migrate_v1.py`.
1. `store.Store(fs, sid)`: every path is under `spaces/{sid}`. Add `Store.spaces(fs)`, which lists sids, plus `keys()` for `private/keys`.
2. `__main__.daily`:
   - Loop over all spaces. Each space has its own try/except, so one bad space never stops the others.
   - Errors go into that space's `meta/activity.errors`.
   - Each space uses its own calendars: fetch every URL and merge the events. Blockers are the union.
   - The Gemini and SerpApi keys come from `keys()`, not env vars. `serp.http_get` and `ai.http_chat` take the key as a parameter.
   - A space with no SerpApi key gets windows and labels, but no search. Its activity error says "Add a SerpApi key in Settings".
3. Airlines: drop avoided airlines when storing rows, and add the score term. The weather module is `weather.py`, using stdlib urllib.
4. Write `meta/activity` and the score breakdown on every pick.
5. The `windows` CI output is per space, counts only, and identifies the space by sid, never by name or email.
6. `tools/migrate_v1.py` (run once from a workflow_dispatch command `migrate`):
   - Create a space named "Chris & Laura" with `owner` and `members` taken from the existing `allow/` docs. The owner is the email given in `--owner`, so no email lands in git.
   - Copy every v1 collection into the space.
   - Write `private/keys` from the env vars `SERPAPI_KEY`, `GEMINI_KEY` and `ICAL_URL`.
   - Create `admins/{owner}`.
   - Delete the v1 docs only after verifying that each copy reads back equal.
   - It must be idempotent: if a space with that owner already exists, exit with a clear message.
7. Workflow: keep `SERPAPI_KEY`, `GEMINI_KEY` and `ICAL_URL` only for the `migrate` command, and add `migrate` to the dispatch choices. The schedule stays once a day.
8. Tests: port everything to the per-space fake. Add tests for:
   - two spaces isolated (budget, labels, devices)
   - multiple calendars (union of blockers)
   - the avoid filter and the prefer bonus
   - the weather term (inside the range, outside it, rain) using fake HTTP
   - the climate cache hit
   - the activity doc shape
   - a missing SerpApi key
   - migration (copy, verify, delete, idempotent)

Done when the suite is green and there's no top-level v1 path left in `store.py`.

## Task B: app (agent 2)
Files: `web/`, `smoke.mjs`, `firestore.rules`, `android/` (only if needed).
1. **Space selection:**
   - After sign-in, query `spaces where members array-contains <email>`.
   - None: show "No Flybye space for this account yet. Ask the person who invited you."
   - One: open it.
   - Several: show a picker, and remember the choice in localStorage.
   - Admins see an **Admin** entry: a list of spaces, plus **New space** (name and owner email) and remove.
2. **Setup:** a space with no `private/keys` (or no calendars) opens a setup screen. The rest of the app stays reachable.
   - **Calendars:** add, name and remove calendar links, with an explanation of where Google's secret iCal address is. Validate that each link starts with `https://`.
   - **Keys:** SerpApi and Gemini fields, each with a "where to get it" link.
   - **Basics:** home airport, weather range, and a link to Wish list.
3. **Settings additions:**
   - Airlines: prefer and avoid chips by IATA code (2 letters/digits, validated), with common names shown for the top US airlines.
   - Weather range: min and max °F, where min must be below max.
   - **Members** (owner only): add or remove a member email.
   - Keys and calendars, editable.
4. **Trips cards:**
   - Weather line: "Forecast 78°/64° · 20% rain" or "Typically 45°/18° · 30% rain".
   - The airline name.
   - A "Why this rank" toggle that shows the score breakdown.
   - Tapping a card opens **trip details**. It calls the Worker (`TIMES_URL` in `firebase-config.js`, a placeholder for now) and shows the outbound and return flights: departure and arrival times, flight numbers, airline and duration.
   - Show a spinner. If the Worker isn't configured or fails, fall back to the Google Flights link with a short explanation.
   - Cache the result per trip in localStorage for 6 hours.
5. **Activity tab:** render `meta/activity` (run times in local time, a searches-used bar, windows checked, errors) plus a link to Calendar.
6. **`firestore.rules` v2**, as in the contract:
   - Membership comes from `get(/spaces/$(sid)).data.members`.
   - `list` on spaces needs `email in resource.data.members`.
   - Only admins can create a space.
   - The owner can change `members` and `name` only.
   - Members can read and write `private/keys` and `settings`. They can read the rest.
   - On labels, members can update only `override` (null or bool).
   - On devices, members can create, update and delete with an email match.
   - On `meta/budget`, members may update **only** `used`, and only by increasing it by exactly 2 (the Worker's times lookup, done as the user). Everything else is read-only.
   - `admins/{email}`: a user can read only their own doc.
   - `climate`: no client access.
7. Smoke test:
   - Extend the fake for spaces: no space, one space, picker, setup flow, Admin create, members, airlines and weather validation, the Activity render, and trip details with a faked Worker response and with the fallback.
   - Still fails on any console error.
   - Escape all Firestore and Worker text.

## Task C: times Worker (agent 3)
Files: `worker/` (`worker.js`, `wrangler.toml`, `README.md`, `test.mjs`), `.github/workflows/worker.yml`.
- `POST /times` with JSON `{sid, window_id, code}` and `Authorization: Bearer <Firebase ID token>`.
- CORS is allowed only for `https://statman15.github.io`, plus `capacitor://localhost`, `https://localhost` and `http://localhost` (the Capacitor and dev origins).
- Verify the ID token with WebCrypto, with no dependencies:
  - RS256 against Google's securetoken JWKS. Cache the keys per the response's `Cache-Control`.
  - `aud` = the project id, `iss` = `https://securetoken.google.com/<project>`, `exp` in the future, `email_verified` true.
- Read `spaces/{sid}/settings/main` (home, stops) and `spaces/{sid}/private/keys` (serpapi) through the Firestore REST API **with the user's ID token**, so the rules decide.
- Call SerpApi `google_flights` with the space's home, `code`, the dates from `window_id`, adults and stops. Take the cheapest itinerary's outbound legs. Then make a second call with its `departure_token` for the return legs.
- Increment `meta/budget.used` by 2 through a Firestore REST commit with a `fieldTransforms` increment, as the user, so the rule allows exactly +2.
- Return `{outbound: [{airline, flight_number, dep, arr, from, to, duration}], return: [...], price, booking_link}`.
- No secret is stored anywhere. Project id `flybye-6e46b` lives in `wrangler.toml` vars.
- Never log tokens or keys.
- `test.mjs`: unit-test JWT validation (expired, wrong aud or iss, bad signature, using a locally generated key), window_id parsing and CORS rejection.
- `worker.yml` deploys with `wrangler deploy` on pushes to `worker/`, using secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. It skips with a notice if they're unset.

## Chris, by hand (after the build)
- A Cloudflare account, free with no card. Create an API token with the "Edit Cloudflare Workers" template, then add `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` as secrets.
- Run the `migrate` workflow once.
- His brother gets a space from the Admin screen, then adds his own keys and calendars.

## Order and merge
A, B and C run in parallel in their own worktrees. Opus then:
1. merges them
2. puts the Worker URL into `firebase-config.js`
3. runs a whole-branch review and fixes what it finds
4. runs `migrate`, then `daily`
5. checks both phones
