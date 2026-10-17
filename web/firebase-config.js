// Public by design: Firebase web config is not a secret (Firestore rules are the lock).
// Chris: Firebase console -> Project settings -> Your apps -> Web app -> paste the values here.
export const firebaseConfig = {
  apiKey: 'REPLACE_ME',
  authDomain: 'REPLACE_ME',
  projectId: 'REPLACE_ME',
  storageBucket: 'REPLACE_ME',
  messagingSenderId: 'REPLACE_ME',
  appId: 'REPLACE_ME',
};
// Firebase console -> Project settings -> Cloud Messaging -> Web Push certificates -> Key pair.
export const VAPID_KEY = 'REPLACE_ME';
