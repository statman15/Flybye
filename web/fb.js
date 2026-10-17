// The only file that talks to the Firebase SDK. One pinned version, straight from Google's CDN (no build step).
// smoke.mjs swaps these four URLs for an in-memory fake.
import { initializeApp } from 'https://www.gstatic.com/firebasejs/12.19.0/firebase-app.js';
import { getAuth, onAuthStateChanged, signInWithPopup, signInWithCredential, GoogleAuthProvider, signOut }
  from 'https://www.gstatic.com/firebasejs/12.19.0/firebase-auth.js';
import { getFirestore, doc, getDoc, getDocs, collection, setDoc, updateDoc, deleteDoc }
  from 'https://www.gstatic.com/firebasejs/12.19.0/firebase-firestore.js';
import { firebaseConfig, VAPID_KEY } from './firebase-config.js';

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export const db = getFirestore(app);
export { onAuthStateChanged, signInWithPopup, signInWithCredential, GoogleAuthProvider, signOut, doc, getDoc, getDocs, collection, setDoc, updateDoc, deleteDoc };

// Web push token for the home-screen web app (permission is already granted by the caller). Returns null when this browser can't do web push.
export async function webPushToken(registration) {
  const { isSupported, getMessaging, getToken } = await import('https://www.gstatic.com/firebasejs/12.19.0/firebase-messaging.js');
  if (!(await isSupported())) return null;
  return getToken(getMessaging(app), { vapidKey: VAPID_KEY, serviceWorkerRegistration: registration });
}
