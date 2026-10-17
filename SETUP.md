# Flybye setup

One time, in this order. Nothing runs on the homelab.

## 1. Accounts and keys
| Secret | Where |
|---|---|
| `SERPAPI_KEY` | serpapi.com → Dashboard → Api Key (free plan, 250 searches a month) |
| `GEMINI_KEY` | aistudio.google.com → Get API key (free tier) |
| `ICAL_URL` | Google Calendar on the web → ⚙ Settings → the shared calendar → **Integrate calendar** → **Secret address in iCal format** |
| `NTFY_TOPIC` | Make one up, long and random, e.g. `flybye-` plus 24 random letters. Anyone who knows it can read the alerts. |

## 2. Private GitHub repo
1. Create a **private** repo and push this folder. Its data shows when you're away, so it must stay private.
2. Repo → Settings → Secrets and variables → Actions → add the 4 secrets above.
3. Actions → **Daily sweep** → Run workflow with `test-notify` → both phones should get "Flybye test".
4. Run it with `windows` to check the free dates and the AI's calendar labels in the log, then with `daily`.

## 3. Phones (both)
Install **ntfy** (Play Store / App Store) → **+** → subscribe to the `NTFY_TOPIC` name on server `ntfy.sh`.
On iPhone, allow notifications when it asks.

## Every day after that
The workflow runs every morning on its own. On Sundays it also sends the week's best trips and any new calendar labels.
To change cities, trip types or lead times, edit `config.yaml` and push.
To force an event to block or not, add it under `overrides:` in `config.yaml`.
Searches used this month are listed in the `searches` table of `data/flybye.db`. The cap is 230, set in `config.yaml`.
