# Flybye — Plan

Finds getaways for Chris and Laura: cheap nonstop flights from ORD on dates when the shared Google Calendar says we're both free, with the weather taken into account. It alerts both phones.

Local folder: `C:\Users\ressl\Claude Code\Getaway_Finder` (rename to Flybye whenever).

## Why build it (checked 2026-10-17)

Google Flights' free "any dates" tracking already emails price drops for each route, and Going.com's free tier sends hand-picked continental-US deals. Neither knows our calendar, ranks by weather or flight length, or alerts both of us once. **Flybye only does that matching.** Google's own typical-price data comes with every search, so we don't copy price tracking either.

## Decisions (settled 2026-10-17)

| Area | Decision |
|---|---|
| Home airport | **ORD only.** |
| Flights | 2 adults, economy, **nonstop always** (SerpApi `stops=1`). |
| Trip types | **Weekend:** Fri evening → Sun, 2–10 weeks out. **3-day weekend:** Thu→Sun or Fri→Mon (holiday Mondays need no vacation day), 2–12 weeks out. **Longer:** 5–9 nights, 3 weeks–4 months out. Each type can be switched on or off in config. |
| Calendar | One **shared Google Calendar**, read through its private iCal link (no Google sign-in). |
| What blocks a trip | An **AI labels each event** as a blocker or not, once per event, and the label is cached by event UID and updated date. **OmniRoute first, a Gemini key as fallback.** If both fail, the event blocks. Overrides go in `config.yaml` (`overrides: {uid_or_title: block\|ignore}`). The Sunday summary lists new labels so we can check them. |
| Destinations | Our own wish list in `config.yaml`. **Still to fill in; we'll send our cities.** Aim for 8–12 to stay inside the free tier. |
| Flight data | **SerpApi** `google_flights` (round trip in one call; the return leg only needs a second call for the details of a trip we're alerting on) and `google_travel_explore` (cheapest places). Travelpayouts was dropped: its data API needs a website, and its cached US fares are thin. Amadeus Self-Service closed 2026-07-17, and Skyscanner and Kiwi are for partners only. |
| Normal price | From Google's `price_insights` (`typical_price_range`, `price_level`, `price_history`) in each response. We still store every price in SQLite as our own history. |
| Budget | **Free tier, 250 searches/month.** Hard cap of 230/month in code, leaving room for manual tests. Each window × city is searched **when it first comes into range** and **again about 14 days before departure**. Nearest windows go first, and the rest wait for next month's quota. Move to $25/month (1,000 searches) only if real use shows missed deals. |
| Surprise me | Once a month: one `google_travel_explore` search per trip type (about 3 searches). Destinations that fit a free window show in the Sunday summary. |
| Weather | Open-Meteo. Within 16 days, the real forecast (free for non-commercial use). Further out, typical weather averaged over the last 10 years from the free historical archive, computed once per city per month and cached. |
| Alerts | **Instant** when a fare is at or below the low end of Google's typical range on a free window, **at most 2 a week**, and never the same trip twice unless it drops another 10%. Otherwise, a **Sunday top 3**. |
| Hotels / events | Not now; see PARKING_LOT.md. |
| Notifications (M1) | Home Assistant REST API → `notify.mobile_app_sm_s936u` (Chris) and `notify.mobile_app_laura_s_iphone` (Laura). Both are already set up. No Firebase in M1. |
| Backend | Homelab LXC **116 at 192.168.1.14**, copying HomelabAssistant's `deploy/` pattern (Debian 13 amd64, static IP, Pi-hole DNS 192.168.1.3, onboot, its own system user, config at `/etc/flybye/config.yaml` with mode 640, data at `/var/lib/flybye`). Python 3. |
| Apps (later) | HypertroPhy's setup: plain HTML/JS with no build step, a PWA from GitHub Pages for Laura's iPhone, and a Capacitor APK built by GitHub Actions for Chris. Laura gets **Tailscale** on her iPhone then, and the backend is served over HTTPS with Tailscale Serve, the same way OmniRoute is. |

## How the sweep works

```
iCal (shared calendar) ──► events ──► AI blocker labels (cached)
                                          │
            trip-type rules + lead times ─┴─► free windows (out/return dates)
                                                    │
         wish list × windows, under the monthly cap ─► SerpApi google_flights (nonstop, 2 adults)
                                                    │
                       price + price_insights ──► SQLite ──► score ──► HA notify (instant / Sunday)
```

**Score** (higher is better, kept simple to start): price against Google's typical range (the main factor), weather (temperature comfort, rain chance), flight time (shorter is better), and a holiday or long-weekend bonus. The weights live in `config.yaml` so they can be tuned without code changes.
<!-- ponytail: hand-tuned linear score; revisit once we've seen a few months of real suggestions -->

**Windows:** a window is blocked if a blocker event overlaps it from 3 hours before departure to 3 hours after return. Default times: weekend out Fri 17:00, back Sun 21:00. 3-day weekend: Thu 17:00 → Sun, or Fri → Mon 21:00. Longer trips: every 7-night window that fits, plus the longest stretch that fits up to 9 nights, chosen so they don't overlap. US federal holidays are computed in code, not pulled from a library.

## Milestones

Each one ends with something we both use.

1. **Backend + Home Assistant alerts.**
   - **First, a live spike:** check `google_travel_explore` with exact `outbound_date`/`return_date`. If it returns prices for many destinations at once on our dates, one call per window could replace the per-city loop (about 20 calls a month instead of about 200). Also check what `price_insights` actually returns.
   - Then: iCal → AI labels → windows, the weekly sweep (a systemd timer, Sunday morning; no web server yet), SQLite, the instant and Sunday alerts through HA, and `deploy/` scripts for LXC 116.
   - Tests: windows (overlaps, holidays, recurring events), the budget cap, alert limits.
   - *Done when:* both phones get a real Sunday summary from our actual calendar and wish list.
2. **Weather + surprise me.** Open-Meteo forecast and typical weather in the score and the alert text, plus the monthly Explore search in the Sunday summary. *Done when:* the summary shows the weather and one or more surprise ideas.
3. **The app, read-only.** A small JSON API on the backend (FastAPI, like HomelabAssistant) behind Tailscale Serve HTTPS. Then the PWA plus APK with four screens: current suggestions, destination list, trip types and lead times, home airport. Editing the destination list and trip types writes back to the backend. *Done when:* Laura opens it from her home screen over Tailscale, and Chris from the APK.
4. **App push + overrides.** Web Push for the iPhone PWA (iOS 16.4+, installed to the home screen) and push for the APK, to replace or sit alongside HA. Flip an event's blocker label with one tap. *Done when:* a deal alert opens the trip in the app on both phones.

## Secrets (in `/etc/flybye/config.yaml`, never in git)

SerpApi key, the private iCal URL, a Home Assistant long-lived token, the OmniRoute key, the Gemini key.

## Open

- The wish list (we'll send the cities).
- The M1 spike result decides the per-city loop versus one Explore call per window.
