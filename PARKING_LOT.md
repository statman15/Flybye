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

## Known gaps (M2 review, 2026-10-17)
- **Old calendar labels never get cleaned up.** Past and cancelled events stay in `labels`, and the Calendar tab reads the whole collection. Fine for two people. Prune labels whose event is gone once the collection gets big.
- **Signing out doesn't remove the phone's push token.** Delete `devices/{token}` on sign-out, or when someone is removed from `allow/`.
- **Settings form rejects equal min and max weeks.** It also validates trip types that are switched off.
- **Shared github.io origin.** Any other Pages site on statman15.github.io runs on the same origin as Flybye's sign-in data. Restrict the Firebase web API key by HTTP referrer and app in Google Cloud. Consider a custom domain or Firebase Hosting.
- **AndroidManifest `allowBackup="true"`.** Turn it off if the sign-in session shouldn't be backed up.
- **The app's "usual" price includes today's price; the alert's doesn't.** So the "% under usual" shown can be a bit smaller than what triggered the alert.
- **A search error mid-sweep can leave `latest/{window}` holding only part of that window's results.**
- **`firebase-admin` warns that `Message.token` is deprecated (use `fid`).** Pinned below 8 for now; switch before upgrading.

## Known gaps (M3 review, 2026-10-18)
- **No automated test of `firestore.rules`.** Everything was checked by reading only. Add Firebase emulator tests for cross-space reads, admin limits and the budget +2 rule.
- **Space settings aren't range-checked by the job.** A direct Firestore write could set `weeks` past 52 or a huge `cap`, which slows that space's own run. Clamp them in `load_cfg`.
- **Removing a space leaves its labels, devices and suggestions behind**, unreachable but never deleted. A job-side cleanup of spaces whose doc is gone would fix it.
- **Labels and `latest/*` grow forever.** Prune labels for events more than 90 days old, and drop latest docs for windows that have passed.
- **Migration crash windows.** A crash between copying data and writing the space doc leaves an orphan copy. A crash during deletion leaves some v1 docs behind. Make it resumable if it's ever needed again.
- **Worker details.** It returns 401 instead of 503 when Google's signing keys can't be fetched, doesn't refetch keys early on an unknown key id, and reports a missing settings doc as 403.
- **The job re-reads `private/keys` several times per run, and `log_search` does a read plus a write per search.** Cheap to tidy if the Firestore reads ever matter.
- **The app's `DEFAULT_SETTINGS` starts new spaces with an empty wish list.** That's intended, but the comment says it mirrors config.yaml.
