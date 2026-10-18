// Public by design: Firebase web config is not a secret (Firestore rules are the lock).
// Firebase console -> Project settings -> Your apps -> Flybye web -> SDK setup and configuration -> Config.
export const firebaseConfig = {
  apiKey: 'AIzaSyBgTh5gxVsRGU34vNtVoeLQ8asGsLulqFo',
  authDomain: 'flybye-6e46b.firebaseapp.com',
  projectId: 'flybye-6e46b',
  storageBucket: 'flybye-6e46b.firebasestorage.app',
  messagingSenderId: '1011095385650',
  appId: '1:1011095385650:web:83727ebc2746adb7f4ae2b',
};
// The times Worker (Cloudflare). A public URL, not a secret. Empty until it is deployed: trip details then fall back to Google Flights.
export const TIMES_URL = '';
// Firebase console -> Project settings -> Cloud Messaging -> Web Push certificates -> Key pair (the public half).
export const VAPID_KEY = 'BPtYPRGXghGf8nJ4Ub1xMQfXYZY0DOGY-E-XuoULF8bmXMxUNSePER-3SHnRhVE6W0-cdqjh-0eUVmFXWLL03c0';
