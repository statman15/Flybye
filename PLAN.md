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
| What blocks a trip | An **AI labels each event** as a blocker or not, once per event, and the label is cached by event UID and updated date. **Gemini (free tier), called directly.** Event titles go to Google's API. If the call fails, the event blocks. Overrides go in `config.yaml` (`overrides: {uid_or_title: block\|ignore}`). The Sunday summary lists new labels so we can check them. |
| Destinations | **Every nonstop destination from ORD** comes back with each Explore call. The **wish list** in `config.yaml` boosts the score and is the only set of cities that can trigger an instant alert. Add or remove a city by editing that list (in the app from M3). Starting list (2026-10-17): **Denver, Key West, Miami, San Francisco** (all trip types); **Tokyo, Paris, Lisbon, Porto** (longer trips only; Porto allows 1 stop). |
| Flight data | **SerpApi `google_travel_explore` with exact `outbound_date`/`return_date`** is the sweep: **one call per window** returns every nonstop destination priced on our dates for 2 adults, plus flight time, airline and a hotel price (spike 2026-10-17). `google_flights` is only used to confirm a deal before an instant alert: it gives Google's typical range and the flight times. Travelpayouts was dropped: its data API needs a website, and its cached US fares are thin. Amadeus Self-Service closed 2026-07-17, and Skyscanner and Kiwi are for partners only. |
| Normal price | Explore has no typical range, so: (1) we store every Explore price in SQLite, and after a few weekly sweeps each route has its own history (median for its trip type and month); (2) before an instant alert, one `google_flights` call gets Google's `typical_price_range` and `price_level`. The spike returned an empty `price_history`, so we don't rely on it. |
| Budget | **Free tier, 250 searches/month**, with a hard cap of 230 in code. Each free window is re-searched **every week** with one Explore call. Longer-trip windows get two more, one with `arrival_area_id` Europe (`/m/02j9z`) and one with Asia (`/m/0j0k`), because the default Explore only covers North America. Porto gets a `google_flights` ORD–OPO call with `stops=2`. That's about 140–180 searches a month, including about 20 `google_flights` confirmations. If we hit the cap, nearest windows go first. |
| Surprise me | Comes for free: the Sunday summary includes the best-scoring non-wish-list city alongside the wish-list picks. |
| Weather | Open-Meteo. Within 16 days, the real forecast (free for non-commercial use). Further out, typical weather averaged over the last 10 years from the free historical archive, computed once per city per month and cached. |
| Alerts | **Instant** when a fare is at or below the low end of Google's typical range on a free window, **at most 2 a week**, and never the same trip twice unless it drops another 10%. Otherwise, a **Sunday top 3**. |
| Hotels | Explore's `hotel_price` comes at no extra cost, so alerts show it as a rough guide. It's probably a per-night price; check that against Google Hotels. No separate hotel searches. Events: see PARKING_LOT.md. |
| Notifications (M1) | **ntfy**: both phones run the free ntfy app and subscribe to one long random topic (kept in a secret). No account. Messages hold trip info only, never calendar details. They do say when we'd be away, so the topic name must stay secret. Later the app's own push may replace it. |
| Backend | **Not on the homelab (Chris, 2026-10-17).** A **GitHub Actions scheduled workflow** in a **private** repo runs `python -m flybye daily` every morning (cron, so it may start a few minutes late). Settings (cities, trips, weights) live in `config.yaml`, committed. Secrets come from GitHub Secrets as environment variables. The SQLite database `data/flybye.db` is committed back after each run. Python 3. The repo stays private because its data shows when we're away. |
| Apps (later) | HypertroPhy's setup: plain HTML/JS with no build step, a PWA from GitHub Pages for Laura's iPhone, and a Capacitor APK built by GitHub Actions for Chris. With no server, the plan is that the daily job writes `data/suggestions.json` and the apps read it, and commit edits to `config.yaml`, through the GitHub API using a fine-grained token limited to this repo, entered once on each phone. Settle this at M3. Pages on a private repo needs GitHub Pro, so the app shell may need its own small public repo with no data in it. |

## How the sweep works

```
iCal (shared calendar) ──► events ──► AI blocker labels (cached)
                                          │
            trip-type rules + lead times ─┴─► free windows (out/return dates)
                                                    │
         wish list × windows, under the monthly cap ─► SerpApi google_flights (nonstop, 2 adults)
                                                    │
                       price + price_insights ──► SQLite ──► score ──► ntfy (instant / Sunday)
```

**Score** (higher is better, kept simple to start): price against Google's typical range (the main factor), weather (temperature comfort, rain chance), flight time (shorter is better), and a holiday or long-weekend bonus. The weights live in `config.yaml` so they can be tuned without code changes.
<!-- ponytail: hand-tuned linear score; revisit once we've seen a few months of real suggestions -->

**Windows:** a window is blocked if a blocker event overlaps it from 3 hours before departure to 3 hours after return. Default times: weekend out Fri 17:00, back Sun 21:00. 3-day weekend: Thu 17:00 → Sun, or Fri → Mon 21:00. Longer trips: every 7-night window that fits, plus the longest stretch that fits up to 9 nights, chosen so they don't overlap. US federal holidays are computed in code, not pulled from a library.

## Milestones

Each one ends with something we both use.

1. **Backend + ntfy alerts.**
   - ✅ **Spike (2026-10-17, `spike/serpapi_spike.py`):** Explore with exact dates returned 50 nonstop destinations, all on our dates, for 2 adults. Nashville came back at $858 in both Explore and `google_flights`. `google_flights` `price_insights` gave `typical_price_range` [390, 740] and `price_level: high`, with an empty `price_history`. For a 7-night January trip, the Europe area search found CDG $1,662 and LIS $1,377 nonstop, the Asia search found NRT $2,471 nonstop, and there was no nonstop to Porto. Default Explore returns only the US, Canada, Mexico and the Bahamas.
   - Next: iCal → AI labels → windows, the daily sweep, SQLite, instant alerts plus the Sunday summary through ntfy, and the GitHub Actions workflow.
   - Tests: windows (overlaps, holidays, recurring events), the budget cap, alert limits.
   - *Done when:* both phones get a real Sunday summary from our actual calendar and wish list.
2. **Weather.** Open-Meteo forecast and typical weather in the score and the alert text. *Done when:* the Sunday summary shows the weather for each pick.
3. **The app.** It reads `data/suggestions.json` from the repo (see Apps above). Then the PWA plus APK with four screens: current suggestions, destination list, trip types and lead times, home airport. Editing the destination list and trip types writes back to the backend. *Done when:* Laura opens it from her home screen, and Chris from the APK.
4. **App push + overrides.** Web Push for the iPhone PWA (iOS 16.4+, installed to the home screen) and push for the APK, to replace or sit alongside HA. Flip an event's blocker label with one tap. *Done when:* a deal alert opens the trip in the app on both phones.

## Secrets (GitHub Secrets, never in git)

`SERPAPI_KEY`, `ICAL_URL` (the calendar's secret iCal address), `GEMINI_KEY`, `NTFY_TOPIC`.

## Open

- `hotel_price` units (per night or per stay).
