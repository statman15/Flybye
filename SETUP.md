# Flybye setup

Do these once, in order. Nothing runs on the homelab, and no key or email ever goes into git. The repo is public.

## 1. Firebase project (free Spark plan)
1. Go to https://console.firebase.google.com and click **Create a project**. Name it `flybye`. Analytics can be off.
2. **Build → Authentication → Get started → Sign-in method → Google → Enable**. Pick your email as the support email.
3. In **Authentication → Settings → Authorized domains**, add `statman15.github.io`.
4. **Build → Firestore Database → Create database**, in **production mode**, location `us-central1`.
5. In **Firestore → Rules**, paste the contents of `firestore.rules` from this repo and **Publish**.
6. In **Firestore → Data**, create collection `allow`. Add one document whose **ID is your Google email in lowercase** (no fields needed), then a second one with **Laura's Google email in lowercase**. These are the only accounts that can open Flybye.

## 2. Apps in Firebase
1. **Project settings (⚙) → Your apps → Web (`</>`)**. Nickname `Flybye web`, and skip Hosting. Copy the `firebaseConfig` values into `web/firebase-config.js`. These values are meant to be public, so commit that file.
2. **Project settings → Cloud Messaging → Web Push certificates → Generate key pair**. Copy the key into `VAPID_KEY` in `web/firebase-config.js`.
3. **Project settings → Your apps → Android**. Package name `com.statman15.flybye`. For **SHA-1**, use the release keystore's fingerprint (step 3.2 prints it). Download **google-services.json**. Don't commit it.
4. **Project settings → Service accounts → Generate new private key**. This downloads a JSON file. Don't commit it either; it goes into a secret below and then gets deleted.

## 3. GitHub secrets (repo → Settings → Secrets and variables → Actions)
1. Get these values:
   - `SERPAPI_KEY`: serpapi.com → Api Key
   - `GEMINI_KEY`: aistudio.google.com → Get API key
   - `ICAL_URL`: Google Calendar → ⚙ → the shared calendar → Integrate calendar → Secret address in iCal format
   - `FIREBASE_SA`: the whole service-account JSON file
   - `GOOGLE_SERVICES_JSON`: the whole google-services.json file
2. Create the APK signing key: `backend/.venv/Scripts/python tools/make-keystore.py`. It writes `~/flybye-keystore`, which holds:
   - `release.p12.b64`: use it as `KEYSTORE_B64`
   - `password.txt`: use it as `KEYSTORE_PASSWORD`

   It also prints the **SHA-1** for step 2.3. Back the folder up to your password manager. Every future APK must be signed with it, or updates won't install.

## 4. Phones
- **Chris (Android):** install the APK from the repo's **Releases**, or add the repo to Obtainium. Sign in with Google, then Settings → **Turn on alerts**.
- **Laura (iPhone, iOS 16.4 or later):** open https://statman15.github.io/Flybye/ in Safari → Share → **Add to Home Screen**. Open Flybye from the Home Screen, sign in with Google, then Settings → **Turn on alerts**, and allow notifications.
  - If Google sign-in won't finish inside the Home Screen app, that's a known iOS limit for sites on github.io. The fix is to host the web app on Firebase Hosting instead. Tell Claude.

## 5. First runs
In Actions → **Daily sweep** → Run workflow:
1. `test-notify`: both phones should get a test push.
2. `windows`: the log lists your free dates, plus how many calendar events the AI labelled.
3. `daily`: the Trips screen fills in.

After that it runs every morning on its own, and sends the week's best trips on Sundays.

## Day to day
- Change cities, trip types and lead times in the app.
- Flip any calendar event between Blocks and Free on the **Calendar** screen.
- Searches used this month are in Firestore `meta/budget`. The cap is 230 of SerpApi's free 250.
