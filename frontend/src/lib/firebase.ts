import { initializeApp, getApps, getApp, FirebaseApp } from "firebase/app";
import {
  getAuth,
  Auth,
  GoogleAuthProvider,
  signInWithPopup,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  updateProfile,
  sendPasswordResetEmail,
  signOut,
  UserCredential,
} from "firebase/auth";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY || "",
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN || "",
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID || "",
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET || "",
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID || "",
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID || "",
};

export const isFirebaseConfigured = (): boolean => {
  return Boolean(
    process.env.NEXT_PUBLIC_FIREBASE_API_KEY &&
    process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID
  );
};

let app: FirebaseApp | null = null;
let auth: Auth | null = null;
let googleProvider: GoogleAuthProvider | null = null;

if (typeof window !== "undefined") {
  try {
    if (isFirebaseConfigured()) {
      app = getApps().length ? getApp() : initializeApp(firebaseConfig);
      auth = getAuth(app);
      googleProvider = new GoogleAuthProvider();
      googleProvider.setCustomParameters({ prompt: "select_account" });
    }
  } catch (err) {
    console.warn("[Firebase] Client initialization warning:", err);
  }
}

export { auth, googleProvider };

export const ensureFirebaseAuth = (): Auth => {
  if (!auth) {
    if (!isFirebaseConfigured()) {
      throw new Error(
        "Firebase is not configured. Please set NEXT_PUBLIC_FIREBASE_API_KEY and NEXT_PUBLIC_FIREBASE_PROJECT_ID in your environment."
      );
    }
    app = getApps().length ? getApp() : initializeApp(firebaseConfig);
    auth = getAuth(app);
  }
  return auth;
};

/**
 * Sign in with Google popup. Returns the Firebase ID token.
 */
export const signInWithFirebaseGoogle = async (): Promise<string> => {
  const authInstance = ensureFirebaseAuth();
  const provider = googleProvider || new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  const result: UserCredential = await signInWithPopup(authInstance, provider);
  return await result.user.getIdToken();
};

/**
 * Sign up with Email, Password, and Display Name. Returns the Firebase ID token.
 */
export const signUpWithFirebaseEmail = async (
  email: string,
  pass: string,
  displayName?: string
): Promise<string> => {
  const authInstance = ensureFirebaseAuth();
  const result = await createUserWithEmailAndPassword(authInstance, email, pass);
  if (displayName && result.user) {
    try {
      await updateProfile(result.user, { displayName });
    } catch {
      // Non-blocking
    }
  }
  return await result.user.getIdToken();
};

/**
 * Sign in with Email and Password. Returns the Firebase ID token.
 */
export const signInWithFirebaseEmail = async (
  email: string,
  pass: string
): Promise<string> => {
  const authInstance = ensureFirebaseAuth();
  const result = await signInWithEmailAndPassword(authInstance, email, pass);
  return await result.user.getIdToken();
};

/**
 * Send password reset email.
 */
export const sendFirebasePasswordReset = async (email: string): Promise<void> => {
  const authInstance = ensureFirebaseAuth();
  await sendPasswordResetEmail(authInstance, email);
};

/**
 * Sign out from Firebase.
 */
export const signOutFirebase = async (): Promise<void> => {
  if (auth) {
    await signOut(auth);
  }
};

/**
 * Formats Firebase error codes into human-readable user-friendly messages.
 */
export const formatFirebaseAuthError = (error: any): string => {
  const code = error?.code || "";
  switch (code) {
    case "auth/invalid-credential":
    case "auth/wrong-password":
    case "auth/user-not-found":
      return "Invalid email or password. Please double-check your credentials.";
    case "auth/email-already-in-use":
      return "This email is already registered. Please sign in instead.";
    case "auth/weak-password":
      return "Password is too weak. Please use at least 8 characters.";
    case "auth/invalid-email":
      return "Please enter a valid email address.";
    case "auth/popup-closed-by-user":
      return "Google sign-in popup was closed before completing.";
    case "auth/popup-blocked":
      return "Popup was blocked by your browser. Please allow popups for this site.";
    case "auth/unauthorized-domain":
      return "This domain is not authorized in Firebase Console. Please add it to Authorized Domains.";
    case "auth/network-request-failed":
      return "Network error. Please check your internet connection and try again.";
    case "auth/too-many-requests":
      return "Too many failed attempts. Please try again later or reset your password.";
    default:
      return error?.message || "Authentication failed. Please try again.";
  }
};
