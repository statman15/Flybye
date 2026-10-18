# Flybye times Worker

A tiny Cloudflare Worker: `POST /times` with `{sid, window_id, code}` and `Authorization: Bearer <Firebase ID token>`. It verifies the token, reads the space's settings and SerpApi key from Firestore as that user, calls SerpApi `google_flights` twice (outbound, then return), adds 2 to `meta/budget.used`, and returns `{outbound, return, price, booking_link}`. It stores no secrets.

Errors: 401 bad token, 403 Firestore denied (or origin not allowed), 404 no flights, 400 bad request, 502 SerpApi/Firestore error.

## Deploy (once)
1. Make a free Cloudflare account (no card).
2. Dashboard > My Profile > API Tokens > Create Token > template "Edit Cloudflare Workers". Copy the token.
3. Copy your Account ID (Workers & Pages sidebar).
4. GitHub repo > Settings > Secrets and variables > Actions: add `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.
5. Run the "Worker (test, deploy)" workflow (Actions tab > Run workflow), or push a change under `worker/`.
6. The deploy log prints the URL, `https://flybye-times.<your-subdomain>.workers.dev`. Put that URL in the app's config.

Local test: `node worker/test.mjs`.
