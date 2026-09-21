"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Globe,
  Lock,
  Mail,
  User,
  ArrowRight,
  ShieldCheck,
  Loader2,
  KeyRound,
  X,
} from "lucide-react";
import { loginUser, registerUser, loginWithFirebase } from "@/lib/api";
import {
  signInWithFirebaseEmail,
  signUpWithFirebaseEmail,
  signInWithFirebaseGoogle,
  sendFirebasePasswordReset,
  formatFirebaseAuthError,
  isFirebaseConfigured,
} from "@/lib/firebase";

export default function LoginPage() {
  const router = useRouter();
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Password reset modal state
  const [showForgotModal, setShowForgotModal] = useState(false);
  const [resetEmail, setResetEmail] = useState("");
  const [resetLoading, setResetLoading] = useState(false);
  const [resetMsg, setResetMsg] = useState<string | null>(null);
  const [resetError, setResetError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccessMsg(null);
    setLoading(true);

    try {
      if (isFirebaseConfigured()) {
        if (isRegister) {
          if (!username.trim()) {
            setError("Username is required");
            setLoading(false);
            return;
          }
          const idToken = await signUpWithFirebaseEmail(email, password, username);
          setSuccessMsg("Account created! Synchronizing your workspace...");
          await loginWithFirebase(idToken);
        } else {
          const idToken = await signInWithFirebaseEmail(email, password);
          await loginWithFirebase(idToken);
        }
      } else {
        // Fallback to legacy native backend credentials
        if (isRegister) {
          if (!username.trim()) {
            setError("Username is required");
            setLoading(false);
            return;
          }
          await registerUser(email, username, password);
          setSuccessMsg("Account created! Logging you in...");
          await loginUser(email, password);
        } else {
          await loginUser(email, password);
        }
      }

      router.push("/");
      router.refresh();
    } catch (err: any) {
      const msg = formatFirebaseAuthError(err) || err.response?.data?.detail || err.message || "Authentication failed";
      setError(typeof msg === "string" ? msg : JSON.stringify(msg));
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleSignIn = async () => {
    setError(null);
    setSuccessMsg(null);
    setGoogleLoading(true);

    try {
      if (!isFirebaseConfigured()) {
        setError("Google authentication requires Firebase configuration in your environment variables.");
        setGoogleLoading(false);
        return;
      }
      const idToken = await signInWithFirebaseGoogle();
      setSuccessMsg("Signed in with Google! Preparing your intelligence feed...");
      await loginWithFirebase(idToken);
      router.push("/");
      router.refresh();
    } catch (err: any) {
      if (err?.code !== "auth/popup-closed-by-user") {
        setError(formatFirebaseAuthError(err));
      }
    } finally {
      setGoogleLoading(false);
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setResetError(null);
    setResetMsg(null);
    setResetLoading(true);

    try {
      await sendFirebasePasswordReset(resetEmail.trim());
      setResetMsg("Password reset email sent! Check your inbox for instructions.");
    } catch (err: any) {
      setResetError(formatFirebaseAuthError(err));
    } finally {
      setResetLoading(false);
    }
  };

  return (
    <div className="flex min-h-[calc(100vh-60px)] items-center justify-center bg-gray-50 px-4 py-12">
      <div className="w-full max-w-md space-y-6">
        {/* Brand header */}
        <div className="text-center">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-geo-900 text-white shadow-md">
            <Globe className="h-6 w-6 text-geo-400" />
          </div>
          <h1 className="mt-4 text-2xl font-black tracking-tight text-gray-900">
            {isRegister ? "Create an Account" : "Sign in to GeoAtlas"}
          </h1>
          <p className="mt-1.5 text-sm text-gray-500">
            {isRegister
              ? "Access real-time geopolitical intelligence and market prediction feeds"
              : "Welcome back. Monitor live macro intelligence and market impacts"}
          </p>
        </div>

        {/* Card */}
        <div className="rounded-3xl border border-gray-200 bg-white p-7 shadow-sm">
          {error && (
            <div className="mb-5 rounded-xl border border-red-200 bg-red-50 p-3 text-xs font-semibold text-red-700 animate-in fade-in">
              {error}
            </div>
          )}

          {successMsg && (
            <div className="mb-5 flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-semibold text-emerald-700 animate-in fade-in">
              <ShieldCheck className="h-4 w-4 shrink-0" />
              {successMsg}
            </div>
          )}

          {/* 1-Click Google Sign In */}
          <button
            type="button"
            onClick={handleGoogleSignIn}
            disabled={googleLoading || loading}
            className="flex w-full items-center justify-center gap-3 rounded-xl border border-gray-200 bg-white py-3 text-sm font-semibold text-gray-700 shadow-sm transition-all hover:bg-gray-50 hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-gray-900 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {googleLoading ? (
              <Loader2 className="h-4 w-4 animate-spin text-gray-500" />
            ) : (
              <svg className="h-4 w-4" viewBox="0 0 24 24">
                <path
                  fill="#4285F4"
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                />
                <path
                  fill="#34A853"
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                />
                <path
                  fill="#FBBC05"
                  d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
                />
                <path
                  fill="#EA4335"
                  d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
                />
              </svg>
            )}
            <span>{isRegister ? "Sign up with Google" : "Continue with Google"}</span>
          </button>

          {/* Divider */}
          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-200" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-white px-3 font-semibold text-gray-400">
                Or continue with email
              </span>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {isRegister && (
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-gray-500">
                  Username / Display Name
                </label>
                <div className="relative mt-1.5">
                  <User className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                  <input
                    type="text"
                    required
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="johndoe"
                    className="w-full rounded-xl border border-gray-200 bg-gray-50 py-2.5 pl-10 pr-4 text-sm text-gray-900 placeholder-gray-400 transition-colors focus:border-geo-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-geo-500"
                  />
                </div>
              </div>
            )}

            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-gray-500">
                Email
              </label>
              <div className="relative mt-1.5">
                <Mail className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@organization.com"
                  className="w-full rounded-xl border border-gray-200 bg-gray-50 py-2.5 pl-10 pr-4 text-sm text-gray-900 placeholder-gray-400 transition-colors focus:border-geo-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-geo-500"
                />
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between">
                <label className="block text-xs font-bold uppercase tracking-wider text-gray-500">
                  Password
                </label>
                {!isRegister && isFirebaseConfigured() && (
                  <button
                    type="button"
                    onClick={() => {
                      setResetEmail(email);
                      setResetMsg(null);
                      setResetError(null);
                      setShowForgotModal(true);
                    }}
                    className="text-xs font-medium text-geo-600 hover:underline"
                  >
                    Forgot password?
                  </button>
                )}
              </div>
              <div className="relative mt-1.5">
                <Lock className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full rounded-xl border border-gray-200 bg-gray-50 py-2.5 pl-10 pr-4 text-sm text-gray-900 placeholder-gray-400 transition-colors focus:border-geo-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-geo-500"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading || googleLoading}
              className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-gray-900 py-3 text-sm font-bold text-white shadow-sm transition hover:bg-black focus:outline-none focus:ring-2 focus:ring-gray-900 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Processing...
                </>
              ) : isRegister ? (
                <>
                  Create Account <ArrowRight className="h-4 w-4" />
                </>
              ) : (
                <>
                  Sign In <ArrowRight className="h-4 w-4" />
                </>
              )}
            </button>
          </form>

          <div className="mt-6 border-t border-gray-100 pt-5 text-center text-xs text-gray-500">
            {isRegister ? (
              <span>
                Already have an account?{" "}
                <button
                  type="button"
                  onClick={() => {
                    setIsRegister(false);
                    setError(null);
                  }}
                  className="font-bold text-geo-600 hover:underline"
                >
                  Sign in
                </button>
              </span>
            ) : (
              <span>
                Don&apos;t have an account?{" "}
                <button
                  type="button"
                  onClick={() => {
                    setIsRegister(true);
                    setError(null);
                  }}
                  className="font-bold text-geo-600 hover:underline"
                >
                  Create one
                </button>
              </span>
            )}
          </div>
        </div>

        <div className="text-center text-xs text-gray-400">
          <Link href="/" className="hover:text-gray-600">
            ← Back to Map & Overview
          </Link>
        </div>
      </div>

      {/* Forgot Password Modal */}
      {showForgotModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-in fade-in duration-150">
          <div className="w-full max-w-sm rounded-3xl border border-gray-200 bg-white p-6 shadow-xl">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-gray-900 font-bold text-base">
                <KeyRound className="h-5 w-5 text-geo-600" />
                Reset Password
              </div>
              <button
                type="button"
                onClick={() => setShowForgotModal(false)}
                className="rounded-full p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <p className="mt-2 text-xs text-gray-500">
              Enter your registered email address to receive a password reset link.
            </p>

            {resetError && (
              <div className="mt-3 rounded-xl border border-red-200 bg-red-50 p-2.5 text-xs text-red-700 font-medium">
                {resetError}
              </div>
            )}

            {resetMsg && (
              <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 p-2.5 text-xs text-emerald-700 font-medium">
                {resetMsg}
              </div>
            )}

            <form onSubmit={handleResetPassword} className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-gray-600">Email Address</label>
                <input
                  type="email"
                  required
                  value={resetEmail}
                  onChange={(e) => setResetEmail(e.target.value)}
                  placeholder="name@organization.com"
                  className="mt-1 w-full rounded-xl border border-gray-200 bg-gray-50 py-2 px-3 text-sm text-gray-900 focus:border-geo-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-geo-500"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowForgotModal(false)}
                  className="rounded-xl px-4 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={resetLoading || !resetEmail.trim()}
                  className="flex items-center gap-1.5 rounded-xl bg-gray-900 px-4 py-2 text-xs font-bold text-white shadow-sm hover:bg-black disabled:opacity-50"
                >
                  {resetLoading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  Send Reset Link
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
