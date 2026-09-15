"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Globe, Lock, Mail, User, ArrowRight, ShieldCheck } from "lucide-react";
import { loginUser, registerUser } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccessMsg(null);
    setLoading(true);

    try {
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
      router.push("/");
      router.refresh();
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || "Authentication failed";
      setError(typeof msg === "string" ? msg : JSON.stringify(msg));
    } finally {
      setLoading(false);
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
              ? "Access real-time geopolitical intelligence and prediction feeds"
              : "Welcome back. Monitor live macro intelligence and market impacts"}
          </p>
        </div>

        {/* Card */}
        <div className="rounded-3xl border border-gray-200 bg-white p-7 shadow-sm">
          {error && (
            <div className="mb-5 rounded-xl border border-red-200 bg-red-50 p-3 text-xs font-semibold text-red-700">
              {error}
            </div>
          )}

          {successMsg && (
            <div className="mb-5 flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-semibold text-emerald-700">
              <ShieldCheck className="h-4 w-4" />
              {successMsg}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {isRegister && (
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-gray-500">
                  Username
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
              <label className="block text-xs font-bold uppercase tracking-wider text-gray-500">
                Password
              </label>
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
              disabled={loading}
              className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-gray-900 py-3 text-sm font-bold text-white shadow-sm transition hover:bg-black focus:outline-none focus:ring-2 focus:ring-gray-900 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? (
                "Processing..."
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
                  onClick={() => setIsRegister(false)}
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
                  onClick={() => setIsRegister(true)}
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
    </div>
  );
}
