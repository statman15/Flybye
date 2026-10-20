# Flybye — Plan

Finds getaways for Chris and Laura: cheap nonstop flights from ORD on dates when the shared Google Calendar says we're both free, with the weather taken into account. It alerts both phones.

Local folder: `C:\Users\ressl\Claude Code\Getaway_Finder` (rename to Flybye whenever).

## Why build it (checked 2026-10-17)

Google Flights' free "any dates" tracking already emails price drops for each route, and Going.com's free tier sends hand-picked continental-US deals. Neither knows our calendar, ranks by weather or flight length, or alerts both of us once. **Flybye only does that matching.** Google's own typical-price data comes with every search, so we don't copy price tracking either.

## Decisions (settled 2026-10-17)

| Area | Decision |
|---|---|
| Home airport | **ORD only.** |
| Flights | 2 adults, economy, **nonstop always** (SerpApi `stops=1`). A city can override this; **Porto** allows 1 stop (`stops=2`), because ORD has no nonstop. |
| Trip types | **Weekend:** Fri evening → Sun, 2–10 weeks out. **3-day weekend:** Thu→Sun or Fri→Mon (holiday Mondays need no vacation day), 2–12 weeks out. **Longer:** 5–9 nights, 3 weeks–4 months out. Each type can be switched on or off in config. |
| Calendar | One **shared Google Calendar**, read through its private iCal link (no Google sign-in). |
| What blocks a trip | An **AI labels each event** as a blocker or not, once per event, and the label is cached by event UID and updated date. **Gemini (free tier), called directly.** Event titles go to Google's API. If the call fails, the event blocks. Labels live in Firestore. The app's **Calendar** screen lists them, and you can flip any label with one tap; a flipped label is saved as an override, which the AI never changes. |
| Destinations | **Every nonstop destination from ORD** comes back with each Explore call. The **wish list** (edited in the app, stored in Firestore) boosts the score and is the only set of cities that can trigger an instant alert. Starting list (2026-10-17): **Denver, Key West, Miami, San Francisco** (all trip types); **Tokyo, Paris, Lisbon, Porto** (longer trips only; Porto allows 1 stop). |
| Flight data | **SerpApi `google_travel_explore` with exact `outbound_date`/`return_date`** is the sweep: **one call per window** returns every nonstop destination priced on our dates for 2 adults, plus flight time, airline and a hotel price (spike 2026-10-17). `google_flights` is only used to confirm a deal before an instant alert: it gives Google's typical range and the flight times. Travelpayouts was dropped: its data API needs a website, and its cached US fares are thin. Amadeus Self-Service closed 2026-07-17, and Skyscanner and Kiwi are for partners only. |
| Normal price | Explore has no typical range, so: (1) we store every Explore price per route in Firestore, and after a few weekly sweeps each route has its own history (median for its trip type and month); (2) before an instant alert, one `google_flights` call gets Google's `typical_price_range` and `price_level`. The spike returned an empty `price_history`, so we don't rely on it. |
| Budget | **Free tier, 250 searches/month**, with a hard cap of 230 in code. Each free window is re-searched **every week** with one Explore call. Longer-trip windows get two more, one with `arrival_area_id` Europe (`/m/02j9z`) and one with Asia (`/m/0j0k`), because the default Explore only covers North America. Porto gets a `google_flights` ORD–OPO call with `stops=2`. That's about 140–180 searches a month, including about 20 `google_flights` confirmations. If we hit the cap, nearest windows go first. |
| Surprise me | Comes for free: the suggestions (and the Sunday push) include the best-scoring non-wish-list city alongside the wish-list picks. |
| Weather | Open-Meteo. Within 16 days, the real forecast (free for non-commercial use). Further out, typical weather averaged over the last 10 years from the free historical archive, computed once per city per month and cached. |
| Alerts | **Instant** when a fare is at or below the low end of Google's typical range on a free window, **at most 2 a week**, and never the same trip twice unless it drops another 10%. Otherwise, a **Sunday top 3**. |
| Hotels | Explore's `hotel_price` comes at no extra cost, so alerts show it as a rough guide. It's probably a per-night price; check that against Google Hotels. No separate hotel searches. Events: see PARKING_LOT.md. |
| Repo | **One public repo, `statman15/Flybye`** (Chris, 2026-10-17): the daily job and the app. No keys or data in git, ever. Keys are GitHub Secrets. Firebase's web config (`apiKey` etc.) is public by design; Firestore rules are the lock. |
| Backend | **Not on the homelab.** A **GitHub Actions scheduled workflow** runs `python -m flybye daily` every morning (cron, so it may start a few minutes late). Python 3 with `firebase-admin` (Firestore + FCM) and a service-account key from `FIREBASE_SA`. |
| Data | **Firestore** (Firebase Spark, free). `config.yaml` only seeds the first settings. <br>• `settings/main`: home, trips, cities, search, alerts and score knobs (edited in the app) <br>• `labels/{key}`: title, block, why, override <br>• `routes/{code}_{kind}`: last 60 prices (seen, window, price) for the usual-price baseline <br>• `latest/{window_id}`: the newest rows for that window <br>• `suggestions/current`: ranked picks, written by the job and read by the app in one read <br>• `meta/budget`: month, used, last searched per window <br>• `meta/alerts`: alerts sent <br>• `devices/{token}`: platform, email <br>• `allow/{email}`: the two allowed accounts, so the emails stay out of git |
| Sign-in | **Google sign-in through Firebase Auth**, for our two Google accounts only. Rules: read and write only if `email_verified` and `allow/{email}` exists. The Android app uses native Google sign-in (`@capacitor-firebase/authentication`), because Google blocks sign-in inside WebViews. |
| Push | **FCM for both phones.** <br>• Android: `@capacitor-firebase/messaging` <br>• Laura's iPhone: the Firebase JS SDK in the home-screen web app (iOS 16.4+, after she adds it to the Home Screen and taps "Turn on alerts") <br>The job sends with `firebase-admin`. Pushes carry the trip line; tapping one opens the trip. ntfy is dropped. |
| Apps | HypertroPhy's setup: plain HTML/JS, no build step. **GitHub Pages** (public repo) for Laura's iPhone, plus a **Capacitor APK** built by GitHub Actions for Chris, built in Android Studio on this PC when needed (Java 21). <br>Screens: <br>• **Trips** (suggestions per free window, with a Google Flights link) <br>• **Wish list** (add or remove cities, trip types per city, nonstop or 1 stop) <br>• **Settings** (trip types, weeks ahead, home airport) <br>• **Calendar** (labels, flip with one tap) |

## How the sweep works

```
iCal (shared calendar) ──► events ──► AI blocker labels (cached)
                                          │
            trip-type rules + lead times ─┴─► free windows (out/return dates)
                                                    │
         wish list × windows, under the monthly cap ─► SerpApi google_flights (nonstop, 2 adults)
                                                    │
                       price + price_insights ──► Firestore ──► score ──► FCM push (instant / Sunday) + app
```

**Score** (higher is better, kept simple to start): price against Google's typical range (the main factor), weather (temperature comfort, rain chance), flight time (shorter is better), and a holiday or long-weekend bonus. The weights live in `settings/main`, so they can be tuned without code changes.
<!-- ponytail: hand-tuned linear score; revisit once we've seen a few months of real suggestions -->

**Windows:** a window is blocked if a blocker event overlaps it from 3 hours before departure to 3 hours after return. Default times: weekend out Fri 17:00, back Sun 21:00. 3-day weekend: Thu 17:00 → Sun, or Fri → Mon 21:00. Longer trips: every 7-night window that fits, plus the longest stretch that fits up to 9 nights, chosen so they don't overlap. US federal holidays are computed in code, not pulled from a library.

## Milestones

Each one ends with something we both use.

1. ✅ **Backend logic (2026-10-17).** Spike, windows, calendar, AI labels, Explore sweep under the cap, deal confirmation, alert rules, summary. 49 tests. It never ran for real: ntfy was dropped before the secrets were set.
   - Spike: Explore with exact dates returned 50 nonstop destinations on our dates, for 2 adults. Nashville was $858 in both Explore and `google_flights`. `price_insights` typical range was [390, 740], with an empty `price_history`. For a 7-night January trip: the Europe area found CDG $1,662 and LIS $1,377 nonstop, the Asia area found NRT $2,471 nonstop, and Porto had no nonstop. Default Explore covers only the US, Canada, Mexico and the Bahamas.
2. **Firebase + the app (both phones).**
   - Swap SQLite for Firestore behind the same few functions. Settings come from `settings/main`. FCM replaces ntfy.
   - The workflow stops committing a database.
   - Build the app with sign-in, all four screens and push.
   - Pages deploy and the APK release, as in HypertroPhy.
   - Then make the repo public again.
   - *Done when:* we both sign in, see real suggestions, flip a label, edit the wish list, and get a push.
3. **Spaces, weather, airlines, flight times, Activity (decided 2026-10-18).** Plan: `docs/superpowers/plans/2026-10-18-m3-spaces-weather-times.md`.
   - **Spaces.** Every person gets their own space: their calendars (one or more, a trip is free only if all are free), airport, wish list, airlines, weather range, and their own SerpApi and Gemini keys. The owner can let a partner in. An admin (Chris) creates spaces.
   - **Airlines.** A prefer list (ranks higher) and an avoid list (hidden).
   - **Weather.** Each space sets an ideal high-temperature range. Trips within 16 days use the forecast; later ones use the typical weather (10-year average). It's shown on cards and used in the ranking.
   - **Flight times.** Instant on tap, through a free Cloudflare Worker that holds no secrets and acts as the user. Costs 2 searches per trip opened.
   - **Activity screen.** Runs, searches left, dates checked, errors, and why each trip ranks where it does.
   - *Done when:* Chris's brother can be invited and set up his own space, and both phones show weather, airline and times.

## Secrets (GitHub Secrets, never in git)

`SERPAPI_KEY`, `ICAL_URL` (the calendar's secret iCal address), `GEMINI_KEY`, `FIREBASE_SA` (service-account JSON).

## Open

- **Prices are per person (found 2026-10-19).** Explore's `flight_price` is per person even with `adults=2` (JAL ORD–NRT Dec 4–14: Explore $1,101, google_flights $2,109 for 2, the Google Flights link $1,055 for 1). The app shows every price per person; google_flights totals are divided by `adults`. Porto's few stored prices from before are totals for 2.

- `hotel_price` units (per night or per stay).
