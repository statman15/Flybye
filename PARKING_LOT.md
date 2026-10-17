# Parking Lot

## Inbox
- **Hotel prices on alerts.** One SerpApi `google_hotels` search per deal we're about to send, so the alert shows the total trip cost. Skipped for now. It probably uses the same 250 searches a month (not verified).
- **Events at the destination.** Concerts and festivals during the window, as a scoring bonus. No source picked yet.
- **Other home airports.** MDW was considered and dropped (ORD only). SerpApi accepts a comma-separated `departure_id`. Check whether that costs one search or two.
- **Flights with one stop.** We chose nonstop always. If longer trips come up empty, allow one stop for them only.
- **Paid tier ($25/mo, 1,000 searches).** Search every window every week instead of twice. Only if the free tier visibly misses deals.
- **~~Travelpayouts cheap-fare feed.~~** Dropped 2026-10-17: the data API needs a project website and a usage description, and its cached fares (2–7 days old) are thin for single US routes. SerpApi Explore covers "surprise me".
- **~~Open-Meteo climate API for typical weather.~~** Dropped 2026-10-17: it's a climate projection model, and the pricing FAQ suggests a paid plan. We use 10-year averages from the free historical archive instead.
