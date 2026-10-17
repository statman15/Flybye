# Parking Lot

## Inbox
- **Exact hotel prices.** Explore already gives a rough `hotel_price` for free. One `google_hotels` search per alert would give real hotel names and totals. Only if the rough number turns out to mislead.
- **Events at the destination.** Concerts and festivals during the window, as a scoring bonus. No source picked yet.
- **Other home airports.** MDW was considered and dropped (ORD only). SerpApi accepts a comma-separated `departure_id`. Check whether that costs one search or two.
- **Flights with one stop.** We chose nonstop always. If longer trips come up empty, allow one stop for them only.
- **~~Paid tier ($25/mo).~~** Not needed: one Explore call per window searches every window every week inside the free 250.
- **~~Travelpayouts cheap-fare feed.~~** Dropped 2026-10-17: the data API needs a project website and a usage description, and its cached fares (2–7 days old) are thin for single US routes. SerpApi Explore covers "surprise me".
- **~~Open-Meteo climate API for typical weather.~~** Dropped 2026-10-17: it's a climate projection model, and the pricing FAQ suggests a paid plan. We use 10-year averages from the free historical archive instead.

## Known gaps (M1 review, 2026-10-17)
- **Same-day re-runs duplicate prices.** Running `daily` twice in one day stores the prices twice, which skews the route's usual price. Fix: a unique key on (seen, window, code).
- **Summary can repeat a city.** The top 3 might be three Denver weekends. Fix: one line per city.
- **Long trips starve late in the month.** When fewer than 4 searches are left for the day, long windows get skipped. Fine unless long trips stop showing up.
- **Event time changes keep the old label.** The cache key is uid + title. Add the event's last-modified time if a moved event gets the wrong label.
- **UTC timestamps on the runner.** `searches.at` is UTC in Actions, so the month boundary is off by up to 6 hours.
- **No phone alert when the calendar link breaks.** GitHub emails on a failed run. A one-line ntfy from `main` would be friendlier.
